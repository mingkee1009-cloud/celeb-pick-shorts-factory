#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
subtitle_extractor.py -- faster-whisper 기반 자막 자동 추출 모듈

영상 -> WAV 음성 추출 -> faster-whisper 음성 인식 -> 세그먼트 목록 반환

openai-whisper 대비 장점:
  - torch 의존성 없음 (Streamlit Cloud 호환)
  - int8 양자화로 메모리 사용 최소화
  - tiny 모델 약 75MB (CPU 실행)
"""

import subprocess
from pathlib import Path


# -- 음성 추출 -----------------------------------------------------------------

def extract_audio_wav(
    video_path: str,
    out_wav: str,
    ffmpeg: str = "ffmpeg",
    log_fn=None,
) -> bool:
    """영상에서 16kHz 모노 WAV 추출 (Whisper 입력 형식)."""
    if log_fn is None:
        log_fn = print
    try:
        r = subprocess.run(
            [
                ffmpeg, "-y", "-loglevel", "error",
                "-i", str(video_path),
                "-ar", "16000", "-ac", "1", "-vn",
                str(out_wav),
            ],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )
        ok = Path(out_wav).exists() and Path(out_wav).stat().st_size > 0
        if ok:
            log_fn("[자막] 음성 추출 완료")
        else:
            log_fn(f"[자막] 음성 추출 실패: {r.stderr[-400:]}")
        return ok
    except Exception as e:
        log_fn(f"[자막] ffmpeg 오류: {e}")
        return False


# -- faster-whisper 자막 추출 --------------------------------------------------

def extract_subtitles(
    video_path: str,
    ffmpeg: str = "ffmpeg",
    model_size: str = "tiny",   # tiny(75MB) / base(145MB) / small(488MB)
    language: str = "ko",
    log_fn=None,
) -> dict:
    """
    faster-whisper 로 영상 음성을 자막으로 변환한다.
    torch 불필요 -- Streamlit Cloud 무료 티어 호환.

    반환:
        {
            "success"  : bool,
            "segments" : [{"start": float, "end": float, "text": str}, ...],
            "full_text": str,
            "error"    : str,
        }
    """
    if log_fn is None:
        log_fn = print

    result: dict = {
        "success": False, "segments": [], "full_text": "", "error": "",
    }

    # faster-whisper 설치 확인
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        result["error"] = (
            "faster-whisper 미설치\n"
            "설치: pip install faster-whisper"
        )
        log_fn(f"[자막] {result['error']}")
        return result

    tmp_wav = Path(video_path).parent / "_whisper_tmp.wav"

    try:
        # 1) 음성 추출
        log_fn("[자막] 음성 추출 중...")
        if not extract_audio_wav(str(video_path), str(tmp_wav), ffmpeg, log_fn):
            result["error"] = "음성 추출 실패 -- ffmpeg 를 확인하세요."
            return result

        # 2) 모델 로딩 (CPU, int8 양자화 -- 메모리 최소화)
        log_fn(f"[자막] faster-whisper '{model_size}' 모델 로딩 중...")
        model = WhisperModel(
            model_size,
            device="cpu",
            compute_type="int8",   # 메모리 절약
        )

        # 3) 음성 인식
        log_fn("[자막] 음성 인식 중 (잠시 기다려주세요)...")
        segments_gen, _info = model.transcribe(
            str(tmp_wav),
            language=language,
            beam_size=5,
            word_timestamps=False,
            condition_on_previous_text=True,
        )

        # 4) 세그먼트 정리
        segments: list[dict] = []
        texts: list[str] = []
        for seg in segments_gen:
            text = (seg.text or "").strip()
            if not text:
                continue
            segments.append({
                "start": round(float(seg.start), 2),
                "end":   round(float(seg.end),   2),
                "text":  text,
            })
            texts.append(text)

        result["success"]   = True
        result["segments"]  = segments
        result["full_text"] = "\n".join(texts)
        log_fn(f"[자막] 인식 완료 -- {len(segments)}개 구간")

    except Exception as e:
        result["error"] = str(e)
        log_fn(f"[자막] 오류: {e}")

    finally:
        try:
            if tmp_wav.exists():
                tmp_wav.unlink()
        except Exception:
            pass

    return result


# -- 자막 없을 때 균등 분배 헬퍼 -----------------------------------------------

def distribute_lines(
    lines: list[str],
    total_duration: float,
    gap: float = 0.05,
) -> list[dict]:
    """
    Whisper 없이 자막 줄을 균등 분배한다.
    반환: [{"start": float, "end": float, "text": str}, ...]
    """
    if not lines:
        return []
    dur_each = max(0.5, (total_duration - gap * (len(lines) - 1)) / len(lines))
    result = []
    cursor = 0.0
    for i, line in enumerate(lines):
        end = cursor + dur_each
        if i == len(lines) - 1:
            end = total_duration
        result.append({
            "start": round(cursor, 2),
            "end":   round(end, 2),
            "text":  line,
        })
        cursor = end + gap
    return result


# -- 타이밍 할당 (Whisper 세그먼트 vs 균등 분배) --------------------------------

def assign_timing(
    lines: list[str],
    segments: list[dict],
    total_duration: float,
) -> list[tuple[float, float, str]]:
    """
    줄 수 == 세그먼트 수 -> Whisper 타이밍 사용
    줄 수 다름          -> 균등 분배
    """
    clean = [l.strip() for l in lines if l.strip()]
    if not clean:
        return []

    if segments and len(segments) == len(clean):
        return [(s["start"], s["end"], l) for s, l in zip(segments, clean)]

    segs = distribute_lines(clean, total_duration)
    return [(s["start"], s["end"], s["text"]) for s in segs]
