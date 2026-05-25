#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze_video.py
다운로드된 영상을 분석해 4컷 구성에 필요한 구간을 자동으로 찾는다.

반환 구조:
    {
        "cut1": {"start": 0.5, "end": 2.0,  "label": "얼굴 후킹 컷"},
        "cut2": {"start": 3.0, "end": 8.0,  "label": "분위기 컷"},
        "cut3": {"start": 12.0, "end": 22.0, "label": "제품 언급 컷"},
        "cut4": None,   # 제품 이미지 컷은 외부에서 처리
        "product_mention_start": 12.0,
        "product_mention_end": 22.0,
        "confidence": "high"   # high / medium / low
    }
"""

import re
import subprocess
import json
from pathlib import Path


# ---------------------------------------------------------------------------
# ffprobe / ffmpeg 헬퍼
# ---------------------------------------------------------------------------

def _run(cmd: list[str]) -> str:
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )
        return r.stdout.strip()
    except Exception:
        return ""


def get_video_duration(video_path: str, ffprobe: str = "ffprobe") -> float:
    out = _run([
        ffprobe, "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_path),
    ])
    try:
        return float(out)
    except ValueError:
        return 0.0


def extract_frame(
    video_path: str, at_sec: float, out_path: str, ffmpeg: str = "ffmpeg"
) -> bool:
    """영상에서 특정 시각 프레임을 JPG로 저장."""
    r = subprocess.run(
        [
            ffmpeg, "-y", "-loglevel", "error",
            "-ss", f"{at_sec:.3f}", "-i", str(video_path),
            "-frames:v", "1", "-q:v", "2", str(out_path),
        ],
        capture_output=True,
    )
    return Path(out_path).exists() and Path(out_path).stat().st_size > 0


# ---------------------------------------------------------------------------
# 음성 → 텍스트 (Whisper, 없으면 스킵)
# ---------------------------------------------------------------------------

def _transcribe_with_whisper(video_path: str, log_fn) -> list[dict] | None:
    """
    whisper가 설치되어 있으면 음성 인식을 수행하고
    단어별 타임스탬프 목록을 반환한다.
    반환: [{"text": "...", "start": 0.0, "end": 0.5}, ...]
    없으면 None 반환.
    """
    try:
        import whisper
    except ImportError:
        log_fn("[분석] whisper 없음 — 제품 언급 구간 자동 감지 비활성화")
        return None

    try:
        log_fn("[분석] Whisper 음성 인식 시작 (시간이 걸릴 수 있습니다)...")
        model = whisper.load_model("base")
        result = model.transcribe(
            str(video_path),
            language="ko",
            word_timestamps=True,
            verbose=False,
        )
        segments = []
        for seg in result.get("segments", []):
            segments.append({
                "text": seg.get("text", "").strip(),
                "start": float(seg.get("start", 0)),
                "end": float(seg.get("end", 0)),
            })
        log_fn(f"[분석] Whisper 인식 완료 — {len(segments)}개 구간")
        return segments
    except Exception as e:
        log_fn(f"[분석] Whisper 오류: {e}")
        return None


def _find_product_segments(
    segments: list[dict],
    product_keywords: list[str],
) -> list[dict]:
    """
    자막 구간에서 제품 키워드가 포함된 구간을 찾는다.
    연속된 구간은 병합하고, 앞뒤 1초 여유를 둔다.
    """
    if not segments or not product_keywords:
        return []

    hit_indices = []
    for i, seg in enumerate(segments):
        text = seg["text"]
        for kw in product_keywords:
            if kw and kw.lower() in text.lower():
                hit_indices.append(i)
                break

    if not hit_indices:
        return []

    # 연속 구간 병합
    merged = []
    group = [hit_indices[0]]
    for idx in hit_indices[1:]:
        if idx - group[-1] <= 3:   # 3개 구간 이내면 같은 블록
            group.append(idx)
        else:
            merged.append(group)
            group = [idx]
    merged.append(group)

    result = []
    for grp in merged:
        start = max(0.0, segments[grp[0]]["start"] - 1.0)
        end = segments[grp[-1]]["end"] + 1.0
        text_combined = " ".join(segments[i]["text"] for i in grp)
        result.append({"start": start, "end": end, "text": text_combined})

    # 길이 기준 내림차순 정렬 (가장 긴 언급 구간이 핵심 컷)
    result.sort(key=lambda x: x["end"] - x["start"], reverse=True)
    return result


# ---------------------------------------------------------------------------
# 4컷 자동 분석
# ---------------------------------------------------------------------------

def analyze_4cuts(
    video_path: str,
    product_keyword: str,
    celeb_name: str = "",
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
    manual_product_start: float | None = None,
    manual_product_end: float | None = None,
    log_fn=None,
) -> dict:
    """
    영상을 분석해 4컷 구성 정보를 반환한다.

    manual_product_start / manual_product_end 가 있으면 Whisper 없이
    해당 구간을 제품 컷으로 강제 지정한다.
    """
    if log_fn is None:
        log_fn = print

    video_path = str(video_path)
    total_dur = get_video_duration(video_path, ffprobe)
    if total_dur <= 0:
        log_fn("[분석] 영상 길이를 읽을 수 없습니다.")
        total_dur = 60.0

    log_fn(f"[분석] 영상 길이: {total_dur:.1f}초")

    # -------------------------------------------------------------------------
    # 제품 언급 구간 결정
    # -------------------------------------------------------------------------
    confidence = "low"
    product_start = None
    product_end = None

    # 1) 수동 지정 우선
    if manual_product_start is not None and manual_product_end is not None:
        product_start = float(manual_product_start)
        product_end = float(manual_product_end)
        confidence = "high"
        log_fn(f"[분석] 수동 지정 구간: {product_start:.1f}s ~ {product_end:.1f}s")

    else:
        # 2) Whisper 자동 인식
        keywords = [kw.strip() for kw in product_keyword.split() if kw.strip()]
        keywords.append(product_keyword)

        segments = _transcribe_with_whisper(video_path, log_fn)
        if segments:
            hits = _find_product_segments(segments, keywords)
            if hits:
                best = hits[0]   # 가장 긴 언급 구간
                product_start = best["start"]
                product_end = best["end"]
                confidence = "high"
                log_fn(f"[분석] 제품 언급 구간: {product_start:.1f}s ~ {product_end:.1f}s")
            else:
                log_fn("[분석] 정확한 제품 키워드 미발견 — 영상 중반부를 기본 컷으로 사용")
                confidence = "low"
        else:
            log_fn("[분석] 음성 인식 불가 — 영상 중반부를 기본 컷으로 사용")
            confidence = "low"

    # Whisper 실패 또는 키워드 미발견 시 휴리스틱 기본값
    if product_start is None:
        # 영상 40%~75% 구간을 제품 언급 구간으로 가정
        product_start = total_dur * 0.40
        product_end = min(total_dur * 0.75, product_start + 15.0)

    # 제품 컷(3컷) 길이 보정: 7~10초
    cut3_len = product_end - product_start
    if cut3_len < 7.0:
        product_end = product_start + 7.0
    elif cut3_len > 15.0:
        product_end = product_start + 10.0

    # 전체 영상 범위 초과 방지
    product_end = min(product_end, total_dur)
    product_start = max(0.0, product_start)

    # -------------------------------------------------------------------------
    # 1컷: 얼굴 후킹 컷 (영상 초반 또는 제품 언급 직전에서 1.5~2초)
    # -------------------------------------------------------------------------
    cut1_start = max(0.0, min(product_start - 5.0, total_dur * 0.05))
    cut1_end = cut1_start + 2.0
    # 제품 컷과 겹치지 않도록
    if cut1_end > product_start:
        cut1_start = 0.0
        cut1_end = 2.0

    # -------------------------------------------------------------------------
    # 2컷: 분위기 컷 (1컷 직후 ~ 제품 언급 직전, 4~6초)
    # -------------------------------------------------------------------------
    cut2_start = cut1_end
    cut2_end = cut2_start + 5.0
    if cut2_end >= product_start:
        cut2_end = max(cut2_start + 2.0, product_start - 0.5)

    # -------------------------------------------------------------------------
    # 결과 딕셔너리
    # -------------------------------------------------------------------------
    result = {
        "cut1": {
            "start": round(cut1_start, 2),
            "end": round(cut1_end, 2),
            "label": "얼굴 후킹 컷",
            "target_duration": 2.0,
        },
        "cut2": {
            "start": round(cut2_start, 2),
            "end": round(cut2_end, 2),
            "label": "분위기 컷",
            "target_duration": 5.0,
        },
        "cut3": {
            "start": round(product_start, 2),
            "end": round(product_end, 2),
            "label": "제품 언급 컷",
            "target_duration": 9.0,
        },
        "cut4": {
            "start": 0,
            "end": 5.0,
            "label": "제품 이미지 컷",
            "target_duration": 5.0,
            "is_image_card": True,
        },
        "product_mention_start": round(product_start, 2),
        "product_mention_end": round(product_end, 2),
        "total_duration": round(total_dur, 2),
        "confidence": confidence,
    }

    log_fn(f"[분석] 4컷 분석 완료 (신뢰도={confidence})")
    log_fn(f"  1컷: {result['cut1']['start']}s ~ {result['cut1']['end']}s (얼굴 후킹)")
    log_fn(f"  2컷: {result['cut2']['start']}s ~ {result['cut2']['end']}s (분위기)")
    log_fn(f"  3컷: {result['cut3']['start']}s ~ {result['cut3']['end']}s (제품 언급)")
    log_fn(f"  4컷: 제품 이미지/텍스트 카드")

    return result


# ---------------------------------------------------------------------------
# 후킹 자막 자동 생성
# ---------------------------------------------------------------------------

HOOK_TEMPLATES = {
    "연예인 찐템 소개형": [
        "{celeb}이 실제로 쓰는 {product}",
        "{celeb} 찐애용 {product}",
        "{celeb}도 챙겨 먹는 {product}",
    ],
    "아이돌 피부템 소개형": [
        "{celeb} 피부 비결이 {product}",
        "{celeb}이 파우치에 넣는 {product}",
        "아이돌 피부 뒤에 {product}",
    ],
    "동안 관리템 소개형": [
        "{celeb} 동안 비결 {product}",
        "{celeb}이 매일 챙기는 {product}",
        "나이를 거스르는 {celeb}의 {product}",
    ],
    "연예인 식단템 소개형": [
        "{celeb} 다이어트 필수 {product}",
        "{celeb}이 식단할 때 챙기는 {product}",
        "{celeb} 몸매 비결 {product}",
    ],
    "셀럽 일상템 소개형": [
        "{celeb} 일상에서 쓰는 {product}",
        "{celeb} 추천 {product}",
        "셀럽들이 먼저 찾는 {product}",
    ],
}

DEFAULT_HOOK_TEMPLATES = [
    "{celeb}이 쓰는 {product}",
    "{celeb} 추천 {product}",
    "{celeb}의 찐템 {product}",
]


def generate_hook_texts(celeb_name: str, product_keyword: str, style: str) -> list[str]:
    """후킹 자막 후보를 최대 3개 반환."""
    templates = HOOK_TEMPLATES.get(style, DEFAULT_HOOK_TEMPLATES)
    result = []
    for tpl in templates:
        text = tpl.format(celeb=celeb_name, product=product_keyword)
        result.append(text)
    return result


# ---------------------------------------------------------------------------
# 대본 자동 생성
# ---------------------------------------------------------------------------

SCRIPT_TEMPLATES = {
    "연예인 찐템 소개형": (
        "{celeb}이 다이어트할 때 챙겨 먹는 찐템이 있다는데\n"
        "이건 계속 재주문한다는 말까지 나온 제품입니다\n"
        "맛은 포기하지 않고 식단 부담은 줄이는 느낌이라\n"
        "관리할 때 찾는 사람이 많다고 합니다\n"
        "굶어서 빼는 게 아니라 챙겨 먹으면서 관리하는 루틴\n"
        "정보는 하단 링크에서 확인하세요"
    ),
    "아이돌 피부템 소개형": (
        "{celeb} 파우치에 꼭 들어있다는 {product}\n"
        "무대 조명 아래서도 빛나는 피부 비결이라는데\n"
        "자극 없이 촉촉하게 정돈되는 느낌이라\n"
        "무대 준비하면서도 챙긴다고 합니다\n"
        "아이돌이 먼저 찾는 이유가 있는 제품\n"
        "정보는 하단 링크에서 확인하세요"
    ),
    "동안 관리템 소개형": (
        "{celeb} 나이를 모르는 사람들이 많은 이유가 있다는데\n"
        "매일 빠지지 않고 챙기는 {product}이 그 비결이라고 합니다\n"
        "특별한 게 아니라 꾸준한 루틴이라는 느낌\n"
        "관리하는 분들 사이에서 이미 유명한 제품\n"
        "나이 들어도 관리하는 사람은 다르다는 걸 보여주는 아이템\n"
        "정보는 하단 링크에서 확인하세요"
    ),
    "연예인 식단템 소개형": (
        "{celeb}이 다이어트할 때 식단에 꼭 넣는 {product}\n"
        "굶는 게 아니라 채워 먹으면서 유지하는 방식이라는데\n"
        "부담 없이 즐기면서도 체중 관리가 된다는 후기가 많습니다\n"
        "식단이 힘든 분들에게 먼저 찾게 되는 제품\n"
        "연예인 식단 루틴의 핵심이 이거라고 합니다\n"
        "정보는 하단 링크에서 확인하세요"
    ),
    "셀럽 일상템 소개형": (
        "{celeb} 일상에서 빠지지 않는 {product}이 화제입니다\n"
        "무심하게 쓰는 것처럼 보이지만 늘 챙기는 아이템이라는데\n"
        "셀럽들 사이에서 먼저 알려진 이유가 있다고 합니다\n"
        "평범해 보이지만 쓸수록 차이가 나는 제품\n"
        "일상에서 조용히 루틴이 된 셀럽 필수템\n"
        "정보는 하단 링크에서 확인하세요"
    ),
}

DEFAULT_SCRIPT_TEMPLATE = (
    "{celeb}이 자주 찾는다는 {product}이 화제입니다\n"
    "실제로 써본 분들 사이에서 입소문이 난 제품이라는데\n"
    "부담 없이 꾸준히 챙길 수 있다는 점이 인기 비결이라고 합니다\n"
    "유명인이 먼저 찾는 이유가 있는 제품\n"
    "관심 있으신 분들 많다고 합니다\n"
    "정보는 하단 링크에서 확인하세요"
)


def generate_script(celeb_name: str, product_keyword: str, style: str) -> str:
    """스타일에 맞는 대본을 자동 생성한다."""
    template = SCRIPT_TEMPLATES.get(style, DEFAULT_SCRIPT_TEMPLATE)
    return template.format(celeb=celeb_name, product=product_keyword)


# ---------------------------------------------------------------------------
# 썸네일 문구 생성
# ---------------------------------------------------------------------------

THUMBNAIL_TEMPLATES = {
    "연예인 찐템 소개형": ("{celeb}이 먹고 반한", "{product}"),
    "아이돌 피부템 소개형": ("피부 좋은 아이돌", "파우치에 꼭 있는 것"),
    "동안 관리템 소개형": ("{celeb} 관리비결", "매일 챙기는 이것"),
    "연예인 식단템 소개형": ("{celeb} 식단템", "이거 왜 유명해"),
    "셀럽 일상템 소개형": ("{celeb} 추천템", "이거 왜 유명해"),
}

DEFAULT_THUMBNAIL = ("{celeb} 추천", "{product}")


def generate_thumbnail_texts(celeb_name: str, product_keyword: str, style: str) -> tuple[str, str]:
    """썸네일 메인·서브 문구를 반환."""
    main_tpl, sub_tpl = THUMBNAIL_TEMPLATES.get(style, DEFAULT_THUMBNAIL)
    main = main_tpl.format(celeb=celeb_name, product=product_keyword)
    sub = sub_tpl.format(celeb=celeb_name, product=product_keyword)
    return main, sub


if __name__ == "__main__":
    # 테스트
    cuts = analyze_4cuts(
        "downloads/test.mp4",
        "저당간식",
        "고준희",
        log_fn=print,
    )
    print(json.dumps(cuts, ensure_ascii=False, indent=2))
