#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_final_shorts.py — 업로드 영상에 자막·후킹바·출처를 입혀 쇼츠를 완성한다.

핵심 규칙:
  - 원본 음성 절대 제거 금지
  - AI TTS 미사용
  - 수정된 자막(edited_script_text) 우선 사용
  - 상단 검정바: 흰색 첫줄 + 노란색 강조줄
  - 하단 고정: 출처 채널명 + "제품은 프로필 링크"
"""

import io
import os
import subprocess
import traceback
from datetime import datetime
from pathlib import Path


# ── 유틸리티 ─────────────────────────────────────────────────────────────────

def _run(cmd, log_fn=None):
    try:
        subprocess.run(
            cmd, check=True, capture_output=True,
            text=True, encoding="utf-8", errors="replace",
        )
    except FileNotFoundError:
        raise RuntimeError(f"명령을 찾을 수 없습니다: {cmd[0]}")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"명령 실패: {(e.stderr or e.stdout or '')[-2000:]}")


def _duration(ffprobe, path):
    try:
        r = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def _fmt_ass(s):
    s = max(0.0, float(s))
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    sec = s - h * 3600 - m * 60
    return f"{h}:{m:02d}:{sec:05.2f}"


def _esc_ass_text(text):
    return (text or "").replace("\\", "\\\\").replace("{", "(").replace("}", ")")


def _esc_path_for_vf(path):
    """ffmpeg -vf 필터에서 쓸 경로 이스케이프 (Windows/Linux 공통)."""
    return path.replace("\\", "/").replace(":", "\\:")


def _find_korean_font():
    import platform
    candidates = {
        "Windows": [
            r"C:\Windows\Fonts\malgunbd.ttf",
            r"C:\Windows\Fonts\malgun.ttf",
            r"C:\Windows\Fonts\NanumGothicBold.ttf",
            r"C:\Windows\Fonts\NanumGothic.ttf",
        ],
        "Darwin":  ["/System/Library/Fonts/AppleSDGothicNeo.ttc"],
        "Linux":   ["/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"],
    }.get(platform.system(), [])
    for p in candidates:
        if os.path.exists(p):
            return p
    return None


def _font_name(path):
    if not path:
        return "Sans"
    mapping = {
        "malgunbd":         "Malgun Gothic",
        "malgun":           "Malgun Gothic",
        "NanumGothicBold":  "NanumGothic",
        "NanumGothic":      "NanumGothic",
        "AppleSDGothicNeo": "Apple SD Gothic Neo",
    }
    return mapping.get(Path(path).stem, Path(path).stem)


# ── ASS 자막 빌드 ─────────────────────────────────────────────────────────────

def build_ass(timed_lines, hook_line1, hook_line2, source_channel,
              total_duration, font_name, cfg):
    """
    5레이어 ASS 자막 파일 생성.

    레이아웃 (1080x1920 기준):
      [상단 검정바 0~220px]
        Hook1 (흰색 굵은)   — an8, MarginV=22
        Hook2 (노란색 굵은) — an8, MarginV=120
      [중앙~하단]
        Body (흰색 본문)    — an2, MarginV=380
      [하단 검정바 1805~1920px]
        Source (작은 흰색)  — an2, MarginV=115
        Fixed  (하늘색)     — an2, MarginV=58
    """
    sub = cfg.get("subtitle", {})
    ow       = sub.get("outline_width", 4)
    sh       = sub.get("shadow", 1)
    body_sz  = sub.get("body_font_size",  60)
    hook_sz  = sub.get("hook_font_size",  64)
    small_sz = sub.get("small_font_size", 44)

    def style_line(name, size, color, align, margin_v, bold=1):
        return (
            f"Style: {name},{font_name},{size},"
            f"{color},&H00FFFFFF,&H00000000,&H96000000,"
            f"{bold},0,0,0,100,100,0,0,1,{ow},{sh},"
            f"{align},60,60,{margin_v},1"
        )

    ass = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1080",
        "PlayResY: 1920",
        "WrapStyle: 1",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        style_line("Hook1",  hook_sz,  "&H00FFFFFF", 8, 22),
        style_line("Hook2",  hook_sz,  "&H0000FFFF", 8, 120),
        style_line("Body",   body_sz,  "&H00FFFFFF", 2, 380),
        style_line("Source", small_sz, "&H00FFFFFF", 2, 115),
        style_line("Fixed",  small_sz, "&H00EEFFFF", 2, 58),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    def dlg(s, e, style, text):
        return (
            f"Dialogue: 0,{_fmt_ass(s)},{_fmt_ass(e)},"
            f"{style},,0,0,0,,{_esc_ass_text(text)}"
        )

    if hook_line1:
        ass.append(dlg(0, total_duration, "Hook1", hook_line1))
    if hook_line2:
        ass.append(dlg(0, total_duration, "Hook2", hook_line2))

    for start, end, text in timed_lines:
        text = text.strip()
        if text:
            ass.append(dlg(start, end, "Body", text))

    if source_channel:
        ass.append(dlg(0, total_duration, "Source", f"출처  {source_channel}"))
    ass.append(dlg(0, total_duration, "Fixed", "제품은 프로필 링크"))

    return "\n".join(ass) + "\n"


# ── 영상 트림 ─────────────────────────────────────────────────────────────────

def trim_video(ffmpeg, src, end_sec, dst, log_fn=None):
    if log_fn is None:
        log_fn = print
    _run([
        ffmpeg, "-y", "-loglevel", "error",
        "-i", src,
        "-t", f"{end_sec:.3f}",
        "-c", "copy",
        dst,
    ])
    log_fn(f"[생성] 앞 {end_sec:.1f}초로 트림 완료")


# ── 썸네일 미리보기 (PIL only, ffmpeg 불필요) ─────────────────────────────────

def render_thumbnail_preview(
    hook_line1,
    hook_line2,
    frame_path="",
    font_path=None,
    tw=360,
    th=640,
):
    """
    PIL로 썸네일 미리보기를 렌더링해 PNG bytes를 반환.
    ffmpeg 없이 PIL만 사용 — 실시간 미리보기용.
    frame_path: 첫 프레임 이미지 경로 (없으면 어두운 배경 사용)
    """
    try:
        from PIL import Image, ImageDraw, ImageFont

        # 기반 이미지 (첫 프레임 또는 다크 배경)
        img = Image.new("RGB", (tw, th), (18, 18, 28))
        if frame_path and os.path.exists(frame_path):
            try:
                fr = Image.open(frame_path).convert("RGB")
                fw, fh = fr.size
                ratio = max(tw / fw, th / fh)
                fr = fr.resize((int(fw * ratio), int(fh * ratio)), Image.LANCZOS)
                ox = (tw - fr.size[0]) // 2
                oy = (th - fr.size[1]) // 2
                img.paste(fr, (ox, oy))
            except Exception:
                pass

        # 검정바 오버레이
        ov = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
        od = ImageDraw.Draw(ov)
        bar_h = max(50, int(th * 0.115))   # 상단 바 높이
        bot_h = max(30, int(th * 0.063))   # 하단 바 높이
        od.rectangle([(0, 0), (tw, bar_h)], fill=(0, 0, 0, 210))
        od.rectangle([(0, th - bot_h), (tw, th)], fill=(0, 0, 0, 180))
        img = Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")

        draw = ImageDraw.Draw(img)

        # 폰트
        fs = max(14, int(tw * 0.067))
        if font_path is None:
            font_path = _find_korean_font()
        try:
            if font_path and os.path.exists(font_path):
                fnt1 = ImageFont.truetype(font_path, fs)
                fnt2 = ImageFont.truetype(font_path, fs)
            else:
                fnt1 = fnt2 = ImageFont.load_default()
        except Exception:
            fnt1 = fnt2 = ImageFont.load_default()

        y1 = max(4, int(th * 0.010))
        y2 = max(4, int(th * 0.063))

        def draw_text_centered(text, y, font, color):
            try:
                b = draw.textbbox((0, 0), text, font=font)
                x = max(4, (tw - (b[2] - b[0])) // 2)
            except Exception:
                x = 4
            draw.text((x, y), text, font=font, fill=color)

        if hook_line1:
            draw_text_centered(hook_line1, y1, fnt1, "white")
        if hook_line2:
            draw_text_centered(hook_line2, y2, fnt2, "#FFEB3B")

        # 하단 고정 문구 (미리보기용)
        try:
            fnt_s = ImageFont.truetype(font_path, max(10, int(fs * 0.6))) if font_path and os.path.exists(str(font_path)) else ImageFont.load_default()
        except Exception:
            fnt_s = ImageFont.load_default()
        draw_text_centered("제품은 프로필 링크", th - max(20, int(bot_h * 0.45)), fnt_s, "#AAEEFF")

        buf = io.BytesIO()
        img.save(buf, "PNG")
        return buf.getvalue()
    except Exception:
        return None


# ── 썸네일 저장 ──────────────────────────────────────────────────────────────

def make_thumbnail(ffmpeg, video_path, hook_line1, hook_line2, out_path,
                   font_path, tw=1080, th=1920, log_fn=None):
    if log_fn is None:
        log_fn = print
    try:
        from PIL import Image, ImageDraw, ImageFont

        tmp = Path(out_path).with_suffix(".thumb_raw.jpg")
        _run([
            ffmpeg, "-y", "-loglevel", "error",
            "-ss", "0.5", "-i", video_path,
            "-frames:v", "1", "-q:v", "2",
            "-vf", f"scale={tw}:{th}:force_original_aspect_ratio=increase,crop={tw}:{th}",
            str(tmp),
        ])

        img = Image.new("RGB", (tw, th), (10, 10, 10))
        if tmp.exists():
            fr = Image.open(tmp).convert("RGB")
            fw, fh = fr.size
            ratio = max(tw / fw, th / fh)
            fr = fr.resize((int(fw * ratio), int(fh * ratio)), Image.LANCZOS)
            ox = (tw - fr.size[0]) // 2
            oy = (th - fr.size[1]) // 2
            img.paste(fr, (ox, oy))
            try:
                tmp.unlink()
            except Exception:
                pass

        ov = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
        od = ImageDraw.Draw(ov)
        od.rectangle([(0, 0), (tw, 220)], fill=(0, 0, 0, 210))
        od.rectangle([(0, th - 120), (tw, th)], fill=(0, 0, 0, 180))
        img = Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")

        draw = ImageDraw.Draw(img)
        try:
            fnt1 = ImageFont.truetype(font_path, 72) if font_path else ImageFont.load_default()
            fnt2 = ImageFont.truetype(font_path, 72) if font_path else ImageFont.load_default()
        except Exception:
            fnt1 = fnt2 = ImageFont.load_default()

        def draw_centered(text, y, font, color):
            try:
                b = draw.textbbox((0, 0), text, font=font)
                x = max(0, (tw - (b[2] - b[0])) // 2)
            except Exception:
                x = 0
            draw.text((x, y), text, font=font, fill=color)

        if hook_line1:
            draw_centered(hook_line1, 18, fnt1, "white")
        if hook_line2:
            draw_centered(hook_line2, 112, fnt2, "#FFEB3B")

        img.save(str(out_path), "PNG")
        log_fn("[생성] 썸네일 완료")

    except Exception as e:
        log_fn(f"[생성] 썸네일 실패 (계속 진행): {e}")


# ── 결과 텍스트 파일 ──────────────────────────────────────────────────────────

def write_output_texts(out_dir, celeb_name, product_name, hook_line1, hook_line2,
                       source_channel, edited_subtitle_text, auto_subtitle_text="",
                       edited_script_text="", thumb_line1="", thumb_line2=""):
    out_dir = Path(out_dir)

    # title.txt
    titles = [
        hook_line2 or f"{celeb_name} {product_name}",
        f"{celeb_name} 찐템 {product_name}",
        f"이거 알면 늦어 {product_name}",
    ]
    (out_dir / "title.txt").write_text(
        "\n".join(f"{i+1}. {t}" for i, t in enumerate(titles)) + "\n",
        encoding="utf-8",
    )

    # auto_subtitle.txt
    if auto_subtitle_text:
        (out_dir / "auto_subtitle.txt").write_text(
            auto_subtitle_text.strip() + "\n", encoding="utf-8",
        )

    # edited_subtitle.txt (호환성 유지)
    (out_dir / "edited_subtitle.txt").write_text(
        edited_subtitle_text.strip() + "\n", encoding="utf-8",
    )

    # edited_script.txt (새 파일: 대사 수정본)
    script_final = edited_script_text.strip() if edited_script_text.strip() else edited_subtitle_text.strip()
    if script_final:
        (out_dir / "edited_script.txt").write_text(
            script_final + "\n", encoding="utf-8",
        )

    # thumbnail_text.txt (썸네일 문구)
    t1 = thumb_line1.strip() if thumb_line1.strip() else hook_line1
    t2 = thumb_line2.strip() if thumb_line2.strip() else hook_line2
    if t1 or t2:
        (out_dir / "thumbnail_text.txt").write_text(
            f"{t1}\n{t2}\n", encoding="utf-8",
        )

    # description.txt
    src_line = f"\n출처: {source_channel}" if source_channel else ""
    script_body = script_final or edited_subtitle_text.strip()
    desc = (
        f"{celeb_name}이 직접 쓰는 {product_name}\n\n"
        f"{script_body}\n\n"
        f"제품은 프로필 링크에서 확인하세요"
        f"{src_line}\n\n"
        f"#{celeb_name} #{product_name} #쇼츠 #찐템 #연예인추천"
    )
    (out_dir / "description.txt").write_text(desc, encoding="utf-8")


# ── 메인 함수 ─────────────────────────────────────────────────────────────────

def make_final_short(
    video_path,
    edited_subtitle_text,
    whisper_segments,
    hook_line1,
    hook_line2,
    source_channel,
    celeb_name,
    product_name,
    out_dir,
    auto_subtitle_text="",
    trim_end=None,
    config=None,
    log_fn=None,
    edited_script_text="",   # 대사 수정본 — 있으면 자막으로 우선 사용
    thumb_line1="",          # 썸네일 첫줄 — 비면 hook_line1 사용
    thumb_line2="",          # 썸네일 강조줄 — 비면 hook_line2 사용
):
    """
    업로드된 영상에 자막·후킹바·출처를 입혀 final_short.mp4를 생성한다.

    우선순위:
      자막 텍스트: edited_script_text > edited_subtitle_text
      썸네일 문구: thumb_line1/2 > hook_line1/2

    반환: {"success": bool, "final_mp4": str, "thumbnail": str, "error": str}
    """
    if log_fn is None:
        log_fn = print
    if config is None:
        config = {}

    ffmpeg  = config.get("ffmpeg_path", "ffmpeg")
    ffprobe = config.get("ffprobe_path", "ffprobe")
    tw = config.get("video", {}).get("target_width", 1080)
    th = config.get("video", {}).get("target_height", 1920)

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    result = {"success": False, "final_mp4": "", "thumbnail": "", "error": ""}

    try:
        font_path = _find_korean_font()
        font_nm   = _font_name(font_path)
        fonts_dir = str(Path(font_path).parent) if font_path else None

        src = str(video_path)

        # ── 1) 트림 ──────────────────────────────────────────────────────────
        if trim_end and trim_end > 0:
            trimmed = str(out_dir / "_trimmed.mp4")
            log_fn(f"[생성] 앞 {trim_end:.1f}초로 트림...")
            trim_video(ffmpeg, src, trim_end, trimmed, log_fn)
            src = trimmed

        # ── 2) 영상 길이 ──────────────────────────────────────────────────────
        total_dur = _duration(ffprobe, src)
        if total_dur <= 0:
            total_dur = 30.0
        log_fn(f"[생성] 영상 길이: {total_dur:.1f}초")

        # ── 3) 자막 텍스트 결정 (edited_script_text 우선) ─────────────────────
        subtitle_source = edited_script_text.strip() if edited_script_text.strip() else edited_subtitle_text
        lines = [l for l in subtitle_source.splitlines() if l.strip()]
        if not lines:
            raise ValueError("자막 내용이 비어 있습니다. 대사를 입력해주세요.")
        log_fn(f"[생성] 자막 소스: {'편집 대사' if edited_script_text.strip() else '자막 편집본'} ({len(lines)}줄)")

        # ── 4) 자막 타이밍 할당 ───────────────────────────────────────────────
        from subtitle_extractor import assign_timing
        timed = assign_timing(lines, whisper_segments, total_dur)
        log_fn(f"[생성] {len(lines)}줄 → 타이밍 할당 완료")

        # ── 5) ASS 자막 생성 ──────────────────────────────────────────────────
        ass_text = build_ass(
            timed_lines=timed,
            hook_line1=hook_line1,
            hook_line2=hook_line2,
            source_channel=source_channel,
            total_duration=total_dur,
            font_name=font_nm,
            cfg=config,
        )
        ass_path = str(out_dir / "subtitle.ass")
        Path(ass_path).write_text(ass_text, encoding="utf-8")
        log_fn("[생성] subtitle.ass 생성 완료")

        # ── 6) ffmpeg 필터 구성 ───────────────────────────────────────────────
        ass_esc = _esc_path_for_vf(ass_path)
        ass_f   = f"ass=\'{ass_esc}\'"
        if fonts_dir:
            fd_esc = _esc_path_for_vf(fonts_dir)
            ass_f  = f"ass=\'{ass_esc}\'\:fontsdir=\'{fd_esc}\'"

        vf = ",".join([
            f"scale={tw}:{th}:force_original_aspect_ratio=increase",
            f"crop={tw}:{th}",
            "setsar=1",
            "fps=30",
            f"drawbox=x=0:y=0:w={tw}:h=222:color=black@0.90:t=fill",
            f"drawbox=x=0:y={th - 122}:w={tw}:h=122:color=black@0.75:t=fill",
            ass_f,
        ])

        # ── 7) 최종 영상 합성 (원본 음성 그대로) ─────────────────────────────
        final_path = str(out_dir / "final_short.mp4")
        log_fn("[생성] 최종 영상 합성 중 (원본 음성 유지)...")
        _run([
            ffmpeg, "-y", "-loglevel", "error",
            "-i", src,
            "-vf", vf,
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-c:a", "aac", "-b:a", "192k",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            final_path,
        ])
        log_fn(f"[생성] final_short.mp4 완료 ({total_dur:.1f}초)")

        # ── 8) 썸네일 ─────────────────────────────────────────────────────────
        t1 = thumb_line1.strip() if thumb_line1.strip() else hook_line1
        t2 = thumb_line2.strip() if thumb_line2.strip() else hook_line2
        thumb_path = str(out_dir / "thumbnail.png")
        make_thumbnail(
            ffmpeg=ffmpeg,
            video_path=final_path,
            hook_line1=t1,
            hook_line2=t2,
            out_path=thumb_path,
            font_path=font_path,
            tw=tw, th=th,
            log_fn=log_fn,
        )

        # ── 9) 텍스트 결과물 ──────────────────────────────────────────────────
        write_output_texts(
            out_dir=out_dir,
            celeb_name=celeb_name,
            product_name=product_name,
            hook_line1=hook_line1,
            hook_line2=hook_line2,
            source_channel=source_channel,
            edited_subtitle_text=subtitle_source,
            auto_subtitle_text=auto_subtitle_text,
            edited_script_text=edited_script_text,
            thumb_line1=thumb_line1,
            thumb_line2=thumb_line2,
        )
        log_fn("[생성] 텍스트 결과물 저장 완료")

        # ── 10) 임시 파일 정리 ────────────────────────────────────────────────
        if trim_end:
            try:
                (out_dir / "_trimmed.mp4").unlink(missing_ok=True)
            except Exception:
                pass

        result["success"]   = True
        result["final_mp4"] = final_path
        result["thumbnail"] = thumb_path
        log_fn("[생성] 모든 단계 완료!")

    except Exception as e:
        tb = traceback.format_exc()
        log_fn(f"[오류] {e}")
        result["error"] = str(e)
        try:
            (out_dir / "error_log.txt").write_text(
                f"{datetime.now()}\n{e}\n{tb}", encoding="utf-8"
            )
        except Exception:
            pass

    return result
