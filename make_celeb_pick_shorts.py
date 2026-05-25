#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_celeb_pick_shorts.py
4컷 구조 쇼츠 자동 생성 엔진

4컷 구성:
  1컷: 연예인 얼굴 크게 (1.5~2초) + 강한 후킹 자막
  2컷: 연예인 분위기 영상 (4~6초)
  3컷: 제품 언급/사용 장면 (7~10초) — 원본 음성 기본 OFF, 선택 옵션으로만 켬
  4컷: 제품 이미지 또는 텍스트 카드 (4~6초)

기존 make_shorts.py 의 핵심 유틸리티를 재사용한다.
"""

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path


# ---------------------------------------------------------------------------
# 유틸리티 (기존 make_shorts.py 의 함수 재사용)
# ---------------------------------------------------------------------------

def fmt_ass_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds - h * 3600 - m * 60
    return f"{h}:{m:02d}:{s:05.2f}"


def ass_escape(text: str) -> str:
    return (text or "").replace("\\", "\\\\").replace("{", "(").replace("}", ")")


def wrap_korean(text: str, max_chars: int = 16) -> str:
    if not text:
        return ""
    text = text.strip()
    if len(text) <= max_chars:
        return text
    words = text.split(" ")
    lines, cur = [], ""
    for w in words:
        if len(cur) + len(w) + 1 <= max_chars:
            cur = (cur + " " + w).strip()
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return "\\N".join(lines)


def find_korean_font() -> str | None:
    import platform
    candidates = {
        "Windows": [
            r"C:\Windows\Fonts\malgunbd.ttf",
            r"C:\Windows\Fonts\malgun.ttf",
            r"C:\Windows\Fonts\NanumGothicBold.ttf",
            r"C:\Windows\Fonts\NanumGothic.ttf",
        ],
        "Darwin": [
            "/System/Library/Fonts/AppleSDGothicNeo.ttc",
        ],
        "Linux": [
            "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
        ],
    }.get(platform.system(), [])
    for p in candidates:
        if os.path.exists(p):
            return p
    return None


def font_name_from_path(path: str) -> str:
    if not path:
        return "Sans"
    mapping = {
        "malgun": "Malgun Gothic",
        "malgunbd": "Malgun Gothic",
        "NanumGothicBold": "NanumGothic",
        "NanumGothic": "NanumGothic",
        "AppleSDGothicNeo": "Apple SD Gothic Neo",
    }
    stem = Path(path).stem
    return mapping.get(stem, stem)


def run_cmd(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            cmd, check=check, capture_output=True,
            text=True, encoding="utf-8", errors="replace",
        )
    except FileNotFoundError as e:
        raise RuntimeError(f"명령을 찾을 수 없습니다: {cmd[0]} ({e})")
    except subprocess.CalledProcessError as e:
        msg = (e.stderr or e.stdout or str(e))[-3000:]
        raise RuntimeError(f"명령 실패 ({cmd[0]}): {msg}")


def ffprobe_duration(ffprobe: str, path: str) -> float:
    try:
        r = run_cmd([
            ffprobe, "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        ])
        return float(r.stdout.strip())
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# 클립 자르기
# ---------------------------------------------------------------------------

def cut_clip(
    ffmpeg: str,
    src: str,
    start_sec: float,
    end_sec: float,
    dst: str,
    keep_audio: bool = True,
) -> None:
    duration = max(0.5, end_sec - start_sec)
    cmd = [
        ffmpeg, "-y", "-loglevel", "error",
        "-ss", f"{start_sec:.3f}", "-i", str(src),
        "-t", f"{duration:.3f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
    ]
    if keep_audio:
        cmd += ["-c:a", "aac", "-b:a", "192k"]
    else:
        cmd += ["-an"]
    cmd += ["-pix_fmt", "yuv420p", "-movflags", "+faststart", str(dst)]
    run_cmd(cmd)


# ---------------------------------------------------------------------------
# TTS 생성
# ---------------------------------------------------------------------------

async def _edge_tts_save(text: str, out_path: str, voice: str, rate: str, volume: str):
    import edge_tts
    comm = edge_tts.Communicate(text=text, voice=voice, rate=rate, volume=volume)
    await comm.save(str(out_path))


def generate_tts(
    text: str,
    out_path: str,
    voice: str = "ko-KR-SunHiNeural",
    rate: str = "-5%",
    volume: str = "+0%",
    log_fn=None,
) -> bool:
    if log_fn is None:
        log_fn = print
    text = (text or "").strip()
    if not text:
        return False
    try:
        asyncio.run(_edge_tts_save(text, out_path, voice, rate, volume))
        if Path(out_path).exists() and Path(out_path).stat().st_size > 0:
            log_fn("[TTS] edge-tts 생성 완료")
            return True
    except Exception as e:
        log_fn(f"[TTS] edge-tts 실패: {e}")
    try:
        from gtts import gTTS
        gTTS(text=text, lang="ko").save(str(out_path))
        if Path(out_path).exists() and Path(out_path).stat().st_size > 0:
            log_fn("[TTS] gTTS 폴백 생성 완료")
            return True
    except Exception as e:
        log_fn(f"[TTS] gTTS도 실패: {e}")
    return False


# ---------------------------------------------------------------------------
# 제품 이미지 카드 생성
# ---------------------------------------------------------------------------

def make_product_card(
    product_name: str,
    out_path: str,
    product_image_path: str | None,
    width: int = 1080,
    height: int = 1920,
    duration: float = 5.0,
    ffmpeg: str = "ffmpeg",
    log_fn=None,
) -> str:
    """
    제품 이미지가 있으면 이미지를 활용한 카드 영상,
    없으면 텍스트만 있는 카드 영상을 생성한다.
    반환: 생성된 mp4 경로
    """
    if log_fn is None:
        log_fn = print

    from PIL import Image, ImageDraw, ImageFont
    import tempfile

    font_path = find_korean_font()

    img = Image.new("RGB", (width, height), (15, 15, 15))
    draw = ImageDraw.Draw(img)

    if product_image_path and Path(product_image_path).exists():
        try:
            prod_img = Image.open(product_image_path).convert("RGBA")
            # 중앙 정사각형 영역에 맞게 리사이즈
            max_size = int(width * 0.75)
            prod_img.thumbnail((max_size, max_size), Image.LANCZOS)
            pw, ph = prod_img.size
            px = (width - pw) // 2
            py = int(height * 0.25)
            # 배경 이미지에 흰색 카드 영역
            card_bg = Image.new("RGB", (pw + 40, ph + 40), (255, 255, 255))
            img.paste(card_bg, (px - 20, py - 20))
            img.paste(prod_img, (px, py), prod_img if prod_img.mode == "RGBA" else None)
            log_fn("[카드] 제품 이미지 삽입 완료")
        except Exception as e:
            log_fn(f"[카드] 이미지 삽입 실패: {e}")

    # 상품명 텍스트
    try:
        font_main = ImageFont.truetype(font_path, 90) if font_path else ImageFont.load_default()
        font_sub = ImageFont.truetype(font_path, 52) if font_path else ImageFont.load_default()
    except Exception:
        font_main = ImageFont.load_default()
        font_sub = ImageFont.load_default()

    # 상품명 (하단)
    prod_lines = product_name if len(product_name) <= 10 else f"{product_name[:10]}\n{product_name[10:]}"
    bbox = draw.multiline_textbbox((0, 0), prod_lines, font=font_main)
    tw = bbox[2] - bbox[0]
    tx = (width - tw) // 2
    ty = int(height * 0.72)

    outline_w = 5
    for dx in range(-outline_w, outline_w + 1, 2):
        for dy in range(-outline_w, outline_w + 1, 2):
            if dx == 0 and dy == 0:
                continue
            draw.multiline_text((tx + dx, ty + dy), prod_lines, font=font_main, fill=(0, 0, 0), align="center")
    draw.multiline_text((tx, ty), prod_lines, font=font_main, fill="#FFEB3B", align="center")

    # 안내 문구
    guide = "정보는 하단 링크에서 확인하세요"
    bbox2 = draw.textbbox((0, 0), guide, font=font_sub)
    gw = bbox2[2] - bbox2[0]
    gx = (width - gw) // 2
    gy = int(height * 0.88)
    draw.text((gx, gy), guide, font=font_sub, fill="#FFFFFF")

    # 이미지 저장
    tmp_img = Path(out_path).with_suffix(".card_tmp.png")
    img.save(str(tmp_img), "PNG")

    # 정지 이미지 → mp4 변환
    cmd = [
        ffmpeg, "-y", "-loglevel", "error",
        "-loop", "1",
        "-framerate", "30",
        "-i", str(tmp_img),
        "-t", f"{duration:.2f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-an",
        str(out_path),
    ]
    run_cmd(cmd)
    try:
        tmp_img.unlink()
    except Exception:
        pass

    return str(out_path)


# ---------------------------------------------------------------------------
# ASS 자막 생성 (4컷 전용)
# ---------------------------------------------------------------------------

def build_4cut_ass(
    script_lines: list[str],
    hook_text: str,
    cut_times: list[tuple[float, float]],  # [(s,e), (s,e), (s,e), (s,e)]
    total_duration: float,
    font_name: str,
    config: dict,
    link_text: str = "정보는 하단 링크에서 확인하세요",
) -> str:
    """
    4컷 전용 ASS 자막.
    - 1컷: 후킹 자막 (대형 + 형광)
    - 2~3컷: 대본 내용
    - 4컷: 링크 안내
    """
    sub_cfg = config.get("subtitle", {})
    primary = sub_cfg.get("primary_color", "&H00FFFFFF")
    outline = sub_cfg.get("outline_color", "&H00000000")
    outline_w = sub_cfg.get("outline_width", 4)
    shadow = sub_cfg.get("shadow", 1)
    margin_v = sub_cfg.get("margin_v", 280)
    base_size = sub_cfg.get("font_size", 64)
    hook_size = sub_cfg.get("hook_font_size", 84)
    link_size = sub_cfg.get("link_font_size", 60)
    max_chars = sub_cfg.get("max_chars_per_line", 16)

    def style_line(name, size, align_v, margin_v_, bold=1, primary_c=None):
        pc = primary_c or primary
        return (
            f"Style: {name},{font_name},{size},{pc},{pc},"
            f"{outline},&H64000000,{bold},0,0,0,100,100,0,0,1,{outline_w},"
            f"{shadow},{align_v},60,60,{margin_v_},1"
        )

    ass = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1080",
        "PlayResY: 1920",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        style_line("Default", base_size, 2, margin_v),
        style_line("Hook", hook_size, 2, margin_v + 60, primary_c="&H0000FFFF"),
        style_line("Link", link_size, 2, margin_v, primary_c="&H0000F0FF"),
        style_line("Bar", 0, 7, 0),   # 상단 검정바
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    def dialogue(start, end, style, text):
        wrapped = ass_escape(wrap_korean(text, max_chars))
        return f"Dialogue: 0,{fmt_ass_time(start)},{fmt_ass_time(end)},{style},,0,0,0,,{wrapped}"

    # 1컷 후킹
    c1s, c1e = cut_times[0]
    ass.append(dialogue(c1s, c1e, "Hook", hook_text))

    # 2~3컷 대본
    c2s, c2e = cut_times[1]
    c3s, c3e = cut_times[2]
    mid_end = c3e
    mid_lines = [l for l in script_lines if l.strip() and "하단 링크" not in l]

    if mid_lines:
        total_chars = sum(max(1, len(l)) for l in mid_lines)
        mid_start = c2s
        cursor = mid_start
        for i, line in enumerate(mid_lines):
            share = max(1, len(line)) / total_chars
            seg_len = (mid_end - mid_start) * share
            seg_end = cursor + seg_len if i < len(mid_lines) - 1 else mid_end
            ass.append(dialogue(cursor, seg_end, "Default", line))
            cursor = seg_end

    # 4컷 링크 안내
    c4s, c4e = cut_times[3]
    ass.append(dialogue(c4s, c4e, "Link", link_text))

    return "\n".join(ass) + "\n"


# ---------------------------------------------------------------------------
# 4컷 영상 합성
# ---------------------------------------------------------------------------

def concat_clips_with_audio(
    ffmpeg: str,
    clip_paths: list[str],  # [cut1.mp4, cut2.mp4, cut3.mp4, cut4.mp4]
    tts_path: str | None,
    ass_path: str,
    out_path: str,
    target_w: int,
    target_h: int,
    total_duration: float,
    tts_volume: float = 1.0,
    orig_volume: float = 0.25,  # 3컷 원본 음성
    cut3_keep_orig_audio: bool = False,  # 기본값: 원본 음성 OFF
    fonts_dir: str | None = None,
    log_fn=None,
) -> None:
    """
    4개 클립을 순서대로 concat 하고 TTS + 자막을 입혀 최종 mp4를 생성한다.
    cut3(index=2)는 원본 음성을 일부 살릴 수 있다.
    """
    if log_fn is None:
        log_fn = print

    ass_esc = ass_path.replace("\\", "/").replace(":", "\\:")

    n = len(clip_paths)
    cmd = [ffmpeg, "-y", "-loglevel", "error"]
    for cp in clip_paths:
        cmd += ["-i", str(cp)]

    # TTS
    tts_idx = None
    if tts_path and Path(tts_path).exists():
        cmd += ["-i", str(tts_path)]
        tts_idx = n

    # 비디오: 각 클립을 9:16 으로 정규화 후 concat
    scale_filter = (
        f"scale=w='if(gte(iw/ih,{target_w}/{target_h}),-2,{target_w})':"
        f"h='if(gte(iw/ih,{target_w}/{target_h}),{target_h},-2)':flags=lanczos,"
        f"crop={target_w}:{target_h},setsar=1,fps=30"
    )

    filter_parts = []
    for i in range(n):
        filter_parts.append(f"[{i}:v]{scale_filter}[v{i}]")

    concat_v_in = "".join(f"[v{i}]" for i in range(n))
    filter_parts.append(f"{concat_v_in}concat=n={n}:v=1:a=0[vraw]")

    # ASS 자막
    ass_filter = f"ass='{ass_esc}'"
    if fonts_dir:
        fd_esc = fonts_dir.replace("\\", "/").replace(":", "\\:")
        ass_filter = f"ass='{ass_esc}':fontsdir='{fd_esc}'"
    filter_parts.append(f"[vraw]{ass_filter}[v]")

    # 오디오
    audio_streams = []

    # cut3 원본 음성 (있는 경우)
    if cut3_keep_orig_audio and n >= 3:
        cut3_dur = ffprobe_duration(ffprobe="ffprobe", path=clip_paths[2])
        # cut3의 음성을 적절한 볼륨으로
        filter_parts.append(
            f"[2:a]volume={orig_volume:.2f},aresample=44100[a_orig]"
        )
        # cut3가 시작되는 시점 계산
        cut1_dur = ffprobe_duration(ffprobe="ffprobe", path=clip_paths[0])
        cut2_dur = ffprobe_duration(ffprobe="ffprobe", path=clip_paths[1])
        cut3_offset_ms = int((cut1_dur + cut2_dur) * 1000)
        filter_parts.append(
            f"[a_orig]adelay={cut3_offset_ms}|{cut3_offset_ms}[a_orig_d]"
        )
        audio_streams.append("[a_orig_d]")

    # TTS
    if tts_idx is not None:
        filter_parts.append(
            f"[{tts_idx}:a]volume={tts_volume:.2f},aresample=44100[a_tts]"
        )
        audio_streams.append("[a_tts]")

    if audio_streams:
        if len(audio_streams) == 1:
            filter_parts.append(f"{audio_streams[0]}aresample=44100[a]")
        else:
            mix_in = "".join(audio_streams)
            filter_parts.append(
                f"{mix_in}amix=inputs={len(audio_streams)}:dropout_transition=0:normalize=0[a]"
            )
        a_map = ["-map", "[a]"]
    else:
        # 무음
        filter_parts.append(f"aevalsrc=0:d={total_duration:.3f}[a]")
        a_map = ["-map", "[a]"]

    filter_complex = ";".join(filter_parts)

    cmd += [
        "-filter_complex", filter_complex,
        "-map", "[v]",
    ] + a_map + [
        "-t", f"{total_duration:.3f}",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(out_path),
    ]

    run_cmd(cmd)


# ---------------------------------------------------------------------------
# 썸네일 생성
# ---------------------------------------------------------------------------

def make_thumbnail(
    ffmpeg: str,
    source_video: str,
    label_main: str,
    label_sub: str,
    out_path: str,
    font_path: str | None,
    target_w: int = 1080,
    target_h: int = 1920,
    log_fn=None,
) -> None:
    if log_fn is None:
        log_fn = print

    from PIL import Image, ImageDraw, ImageFont

    # 프레임 캡처 (영상 초반 10% 지점 — 얼굴이 크게 보이는 컷)
    tmp_frame = Path(out_path).with_suffix(".thumb_tmp.jpg")
    try:
        dur = ffprobe_duration("ffprobe", source_video)
        snap_at = max(0.1, dur * 0.05)
        run_cmd([
            ffmpeg, "-y", "-loglevel", "error",
            "-ss", f"{snap_at:.2f}", "-i", str(source_video),
            "-frames:v", "1", "-q:v", "2", str(tmp_frame),
        ])
    except Exception as e:
        log_fn(f"[썸네일] 프레임 추출 실패: {e}")

    img = Image.new("RGB", (target_w, target_h), (12, 12, 12))
    if tmp_frame.exists():
        try:
            frame = Image.open(tmp_frame).convert("RGB")
            fw, fh = frame.size
            ratio = max(target_w / fw, target_h / fh)
            new_size = (int(fw * ratio), int(fh * ratio))
            frame = frame.resize(new_size, Image.LANCZOS)
            offset = ((target_w - new_size[0]) // 2, (target_h - new_size[1]) // 2)
            img.paste(frame, offset)
        except Exception as e:
            log_fn(f"[썸네일] 프레임 합성 실패: {e}")
        finally:
            try:
                tmp_frame.unlink()
            except Exception:
                pass

    # 상단 검정바
    overlay = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.rectangle([(0, 0), (target_w, int(target_h * 0.12))], fill=(0, 0, 0, 220))
    od.rectangle([(0, int(target_h * 0.70)), (target_w, target_h)], fill=(0, 0, 0, 170))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")

    draw = ImageDraw.Draw(img)

    try:
        font_main = ImageFont.truetype(font_path or "arial.ttf", 120) if font_path else ImageFont.load_default()
        font_sub = ImageFont.truetype(font_path or "arial.ttf", 58) if font_path else ImageFont.load_default()
    except Exception:
        font_main = ImageFont.load_default()
        font_sub = ImageFont.load_default()

    # 메인 문구
    main_wrap = wrap_korean(label_main, max_chars=8).replace("\\N", "\n")
    bbox = draw.multiline_textbbox((0, 0), main_wrap, font=font_main, spacing=10)
    tw = bbox[2] - bbox[0]
    mx = (target_w - tw) // 2
    my = int(target_h * 0.72)
    for dx in range(-6, 7, 2):
        for dy in range(-6, 7, 2):
            if dx == 0 and dy == 0:
                continue
            draw.multiline_text((mx + dx, my + dy), main_wrap, font=font_main, fill="black", spacing=10, align="center")
    draw.multiline_text((mx, my), main_wrap, font=font_main, fill="#FFEB3B", spacing=10, align="center")

    # 서브 문구
    if label_sub:
        sub_wrap = wrap_korean(label_sub, max_chars=14).replace("\\N", "\n")
        bbox2 = draw.multiline_textbbox((0, 0), sub_wrap, font=font_sub)
        sw = bbox2[2] - bbox2[0]
        sx = (target_w - sw) // 2
        sy = int(target_h * 0.88)
        draw.multiline_text((sx, sy), sub_wrap, font=font_sub, fill="#FFFFFF", spacing=8, align="center")

    img.save(out_path, "PNG")
    log_fn("[썸네일] 생성 완료")


# ---------------------------------------------------------------------------
# 결과물 텍스트 파일 저장
# ---------------------------------------------------------------------------

def write_output_texts(
    out_dir: Path,
    celeb_name: str,
    product_keyword: str,
    style: str,
    script: str,
    hook_texts: list[str],
    thumbnail_main: str,
    thumbnail_sub: str,
    cut_info: dict,
    product_link: str = "",
    hashtags: str = "",
) -> None:
    # title.txt
    titles = hook_texts[:3] if hook_texts else [f"{celeb_name} {product_keyword}"]
    (out_dir / "title.txt").write_text(
        "\n".join(f"{i+1}. {t}" for i, t in enumerate(titles)) + "\n",
        encoding="utf-8",
    )

    # script.txt
    (out_dir / "script.txt").write_text(script.strip() + "\n", encoding="utf-8")

    # description.txt
    desc_lines = [
        f"{celeb_name}이 자주 찾는다는 {product_keyword}을 소개합니다.",
        "",
        script.strip(),
        "",
    ]
    if product_link:
        desc_lines.append(f"제품 링크: {product_link}")
    desc_lines.append("제품 정보는 영상 하단 링크에서 확인할 수 있습니다.")
    desc_lines.append("쿠팡 파트너스 활동을 통해 일정액의 수수료를 제공받을 수 있습니다.")
    if hashtags:
        desc_lines.append("")
        desc_lines.append(hashtags)
    else:
        desc_lines.append("")
        desc_lines.append(f"#{celeb_name} #{product_keyword} #쇼츠 #찐템 #연예인추천")
    (out_dir / "description.txt").write_text("\n".join(desc_lines) + "\n", encoding="utf-8")

    # cut_info.txt
    ci_lines = [
        f"스타일: {style}",
        f"연예인: {celeb_name}",
        f"제품: {product_keyword}",
        "",
        "--- 4컷 구성 ---",
    ]
    for k in ("cut1", "cut2", "cut3", "cut4"):
        info = cut_info.get(k, {})
        label = info.get("label", k)
        s = info.get("start", "-")
        e = info.get("end", "-")
        ci_lines.append(f"{k}: {label} ({s}s ~ {e}s)")
    ci_lines.append(f"\n분석 신뢰도: {cut_info.get('confidence', 'unknown')}")
    (out_dir / "cut_info.txt").write_text("\n".join(ci_lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# 메인 엔트리포인트
# ---------------------------------------------------------------------------

def make_shorts(
    video_path: str,
    celeb_name: str,
    product_keyword: str,
    style: str,
    out_dir: str,
    cut_info: dict,
    script: str,
    hook_texts: list[str],
    thumbnail_main: str,
    thumbnail_sub: str,
    product_image_path: str | None = None,
    product_link: str = "",
    keep_orig_audio_cut3: bool = False,  # 기본값: 원본 음성 OFF
    config: dict | None = None,
    log_fn=None,
) -> dict:
    """
    메인 쇼츠 생성 함수.
    반환: {"success": bool, "final_mp4": str, "thumbnail": str, "error": str}
    """
    if log_fn is None:
        log_fn = print

    if config is None:
        config_path = Path(__file__).parent / "config.json"
        if config_path.exists():
            config = json.loads(config_path.read_text(encoding="utf-8"))
        else:
            config = {}

    ffmpeg = config.get("ffmpeg_path", "ffmpeg")
    ffprobe_bin = config.get("ffprobe_path", "ffprobe")
    target_w = config.get("video", {}).get("target_width", 1080)
    target_h = config.get("video", {}).get("target_height", 1920)
    tts_cfg = config.get("tts", {})

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    result = {"success": False, "final_mp4": "", "thumbnail": "", "error": ""}

    try:
        # 1) 4컷 클립 자르기
        log_fn("[생성] 1단계: 4컷 클립 자르기")
        clip_paths = []
        clip_durations = []

        for idx, cut_key in enumerate(["cut1", "cut2", "cut3"]):
            info = cut_info.get(cut_key, {})
            s = float(info.get("start", 0))
            e = float(info.get("end", s + info.get("target_duration", 5)))
            dst = str(out_dir / f"_clip{idx+1}.mp4")
            keep_audio = (cut_key == "cut3") and keep_orig_audio_cut3
            cut_clip(ffmpeg, video_path, s, e, dst, keep_audio=keep_audio)
            clip_paths.append(dst)
            dur = ffprobe_duration(ffprobe_bin, dst)
            clip_durations.append(dur)
            log_fn(f"  {cut_key}: {s:.1f}s~{e:.1f}s → {dur:.1f}초 클립")

        # 2) 제품 이미지 카드 (4컷)
        log_fn("[생성] 2단계: 제품 이미지 카드 생성")
        cut4_dur = float(cut_info.get("cut4", {}).get("target_duration", 5.0))
        card_path = str(out_dir / "_clip4.mp4")
        make_product_card(
            product_name=product_keyword,
            out_path=card_path,
            product_image_path=product_image_path,
            width=target_w,
            height=target_h,
            duration=cut4_dur,
            ffmpeg=ffmpeg,
            log_fn=log_fn,
        )
        clip_paths.append(card_path)
        clip_durations.append(cut4_dur)

        total_duration = sum(clip_durations)
        log_fn(f"[생성] 전체 예상 길이: {total_duration:.1f}초")

        # 3) TTS 생성
        log_fn("[생성] 3단계: TTS 생성")
        tts_path = str(out_dir / "_voice.mp3")
        tts_ok = generate_tts(
            text=script,
            out_path=tts_path,
            voice=tts_cfg.get("voice", "ko-KR-SunHiNeural"),
            rate=tts_cfg.get("rate", "-5%"),
            volume=tts_cfg.get("volume", "+0%"),
            log_fn=log_fn,
        )

        # TTS 길이 기준으로 total_duration 재조정
        if tts_ok:
            tts_dur = ffprobe_duration(ffprobe_bin, tts_path)
            if tts_dur > 0:
                total_duration = max(total_duration, tts_dur + 0.3)
                total_duration = min(total_duration, 28.0)   # 상한선

        # 4) ASS 자막 생성
        log_fn("[생성] 4단계: ASS 자막 생성")
        font_path = find_korean_font()
        font_name = font_name_from_path(font_path)

        # cut_times: 각 컷의 전체 타임라인에서의 시작/종료
        cut_times = []
        cursor = 0.0
        for dur in clip_durations:
            cut_times.append((cursor, cursor + dur))
            cursor += dur

        script_lines = [l for l in script.split("\n") if l.strip()]
        ass_text = build_4cut_ass(
            script_lines=script_lines,
            hook_text=hook_texts[0] if hook_texts else f"{celeb_name} 찐템",
            cut_times=cut_times,
            total_duration=total_duration,
            font_name=font_name,
            config=config,
        )
        ass_path = str(out_dir / "_sub.ass")
        Path(ass_path).write_text(ass_text, encoding="utf-8")

        # 5) 최종 합성
        log_fn("[생성] 5단계: 최종 영상 합성")
        final_path = str(out_dir / "final_short.mp4")
        fonts_dir = str(Path(font_path).parent) if font_path else None

        concat_clips_with_audio(
            ffmpeg=ffmpeg,
            clip_paths=clip_paths,
            tts_path=tts_path if tts_ok else None,
            ass_path=ass_path,
            out_path=final_path,
            target_w=target_w,
            target_h=target_h,
            total_duration=total_duration,
            tts_volume=config.get("audio", {}).get("tts_volume", 1.0),
            orig_volume=config.get("audio", {}).get("original_volume", 0.25),
            cut3_keep_orig_audio=keep_orig_audio_cut3,
            fonts_dir=fonts_dir,
            log_fn=log_fn,
        )
        log_fn(f"[생성] final_short.mp4 완료 ({total_duration:.1f}초)")

        # 6) 썸네일
        log_fn("[생성] 6단계: 썸네일 생성")
        thumb_path = str(out_dir / "thumbnail.png")
        make_thumbnail(
            ffmpeg=ffmpeg,
            source_video=clip_paths[0],  # 얼굴 컷으로 썸네일
            label_main=thumbnail_main,
            label_sub=thumbnail_sub,
            out_path=thumb_path,
            font_path=font_path,
            target_w=target_w,
            target_h=target_h,
            log_fn=log_fn,
        )

        # 7) 텍스트 결과물
        log_fn("[생성] 7단계: 텍스트 파일 저장")
        write_output_texts(
            out_dir=out_dir,
            celeb_name=celeb_name,
            product_keyword=product_keyword,
            style=style,
            script=script,
            hook_texts=hook_texts,
            thumbnail_main=thumbnail_main,
            thumbnail_sub=thumbnail_sub,
            cut_info=cut_info,
            product_link=product_link,
        )

        # 8) 임시 클립 정리
        for cp in clip_paths + [ass_path, tts_path]:
            try:
                if Path(cp).exists():
                    Path(cp).unlink()
            except Exception:
                pass

        result["success"] = True
        result["final_mp4"] = final_path
        result["thumbnail"] = thumb_path
        log_fn("[생성] 모든 단계 완료!")

    except Exception as e:
        tb = traceback.format_exc()
        log_fn(f"[오류] {e}\n{tb}")
        result["error"] = str(e)
        # 에러 로그 저장
        err_log = out_dir / "error_log.txt"
        err_log.write_text(
            f"{datetime.now()}\n{str(e)}\n{tb}", encoding="utf-8"
        )

    return result
