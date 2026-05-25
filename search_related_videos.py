#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
search_related_videos.py  — 상품 기준 연예인 픽템 검색
같은 상품을 언급한 여러 연예인 후보 영상을 찾는다.
"""

import re
import time
from pathlib import Path

CELEB_SIGNAL_WORDS = [
    "연예인", "아이돌", "배우", "여배우", "남배우", "가수",
    "모델", "셀럽", "방송", "브이로그", "추천템", "찐템",
    "픽", "루틴",
]


def _format_duration(seconds):
    if not seconds:
        return "알 수 없음"
    try:
        seconds = int(seconds)
    except (ValueError, TypeError):
        return "알 수 없음"
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _check_downloadable(url):
    try:
        import yt_dlp
        opts = {"quiet": True, "no_warnings": True, "simulate": True,
                "skip_download": True, "ignoreerrors": True}
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info is not None
    except Exception:
        return False


def _entry_texts(entry):
    return (
        (entry.get("title") or "").lower(),
        (entry.get("channel") or entry.get("uploader") or "").lower(),
        (entry.get("description") or "").lower(),
    )


# ── 상품 중심 검색 쿼리 생성 ────────────────────────────────────────────────────

def build_search_queries(product_keyword):
    """상품명 기준 12개 쿼리를 반환한다."""
    return [
        f"{product_keyword} 연예인",
        f"{product_keyword} 아이돌",
        f"{product_keyword} 배우",
        f"{product_keyword} 여배우",
        f"{product_keyword} 가수",
        f"{product_keyword} 추천",
        f"{product_keyword} 찐템",
        f"{product_keyword} 먹방",
        f"{product_keyword} 식단",
        f"{product_keyword} 다이어트",
        f"{product_keyword} 브이로그",
        f"{product_keyword} 방송",
    ]


# ── 필터 ────────────────────────────────────────────────────────────────────────

def _has_product(entry, product_keyword):
    """제목 또는 설명에 상품명 또는 분리된 키워드가 있으면 True."""
    title, _, desc = _entry_texts(entry)
    pk = product_keyword.lower()
    if pk in title or pk in desc:
        return True
    for word in product_keyword.split():
        w = word.lower()
        if len(w) >= 2 and (w in title or w in desc):
            return True
    return False


# ── 점수 계산 ────────────────────────────────────────────────────────────────────

def calc_score(entry, product_keyword):
    """
    상품명 제목 포함  +60
    상품명 설명 포함  +40
    키워드 단어 제목  +40
    키워드 단어 설명  +25
    연예인 단어 제목  +20 (최초 1회)
    연예인 단어 설명  +10 (최초 1회)
    쇼츠(<=60s)       +10
    """
    title, channel, desc = _entry_texts(entry)
    pk = product_keyword.lower()
    score = 0

    if pk in title:
        score += 60
    if pk in desc:
        score += 40

    for word in product_keyword.split():
        w = word.lower()
        if len(w) >= 2:
            if w in title:
                score += 40
            if w in desc:
                score += 25

    for sw in CELEB_SIGNAL_WORDS:
        if sw in title:
            score += 20
            break
    for sw in CELEB_SIGNAL_WORDS:
        if sw in desc:
            score += 10
            break

    if 0 < (entry.get("duration") or 0) <= 60:
        score += 10

    return score


# ── 분류 ────────────────────────────────────────────────────────────────────────

def _classify_group(entry, product_keyword):
    """exact / keyword / reference"""
    title, _, desc = _entry_texts(entry)
    pk = product_keyword.lower()
    if pk in title:
        return "exact"
    for word in product_keyword.split():
        if len(word) >= 2 and word.lower() in title:
            return "keyword"
    return "reference"


def detect_celeb_signals(entry):
    """제목·설명에서 연예인 관련 단어를 최대 3개 반환."""
    title, channel, desc = _entry_texts(entry)
    found = []
    for sw in CELEB_SIGNAL_WORDS:
        if sw in title or sw in desc:
            found.append(sw)
    return found[:3]


def detect_matched_keywords(entry, product_keyword):
    """제목에서 매칭된 상품 키워드를 반환."""
    title, _, _ = _entry_texts(entry)
    matched = []
    pk = product_keyword.lower()
    if pk in title:
        matched.append(product_keyword)
    else:
        for word in product_keyword.split():
            if len(word) >= 2 and word.lower() in title:
                matched.append(word)
    return matched


# ── 메인 검색 함수 ──────────────────────────────────────────────────────────────

def search_product_videos(product_keyword, max_results=15,
                          score_threshold=60, log_fn=None):
    """
    상품명 기준으로 유튜브를 검색한다.
    필터: 제목 또는 설명에 상품명/키워드가 반드시 포함.
    """
    if log_fn is None:
        log_fn = print
    try:
        import yt_dlp
    except ImportError:
        log_fn("[검색] yt-dlp 없음")
        return []

    queries = build_search_queries(product_keyword)
    seen_ids = set()
    candidates = []
    rejected = 0

    for query in queries:
        log_fn(f"[상품 검색] 쿼리: {query}")
        try:
            with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True,
                                    "extract_flat": True, "ignoreerrors": True,
                                    "skip_download": True}) as ydl:
                info = ydl.extract_info(f"ytsearch10:{query}", download=False)
                if not info or "entries" not in info:
                    continue
                for entry in (info["entries"] or []):
                    if not entry:
                        continue
                    vid_id = entry.get("id", "")
                    if not vid_id or vid_id in seen_ids:
                        continue
                    seen_ids.add(vid_id)
                    dur = entry.get("duration") or 0
                    if dur and (dur < 30 or dur > 7200):
                        continue
                    if not _has_product(entry, product_keyword):
                        rejected += 1
                        continue
                    score = calc_score(entry, product_keyword)
                    if score < score_threshold:
                        continue
                    candidates.append({
                        "id": vid_id,
                        "title": entry.get("title", "제목 없음"),
                        "channel": entry.get("channel") or entry.get("uploader", "채널 미확인"),
                        "duration": dur,
                        "duration_str": _format_duration(dur),
                        "thumbnail": entry.get("thumbnail") or
                                     f"https://img.youtube.com/vi/{vid_id}/hqdefault.jpg",
                        "url": f"https://www.youtube.com/watch?v={vid_id}",
                        "downloadable": None,
                        "view_count": entry.get("view_count") or 0,
                        "score": score,
                        "group": _classify_group(entry, product_keyword),
                        "celeb_signals": detect_celeb_signals(entry),
                        "matched_keywords": detect_matched_keywords(entry, product_keyword),
                    })
        except Exception as e:
            log_fn(f"[상품 검색] 쿼리 실패: {e}")
        time.sleep(0.4)

    log_fn(f"[상품 검색] 상품 미포함 제외: {rejected}개")
    candidates.sort(key=lambda x: x["score"], reverse=True)
    results = candidates[:max_results]
    for item in results:
        try:
            item["downloadable"] = _check_downloadable(item["url"])
        except Exception:
            item["downloadable"] = False
    log_fn(f"[상품 검색] 최종 {len(results)}개 반환")
    return results


# ── 단일 URL 조회 ────────────────────────────────────────────────────────────────

def get_video_info(url, log_fn=None):
    if log_fn is None:
        log_fn = print
    try:
        import yt_dlp
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True,
                                "extract_flat": False, "skip_download": True}) as ydl:
            info = ydl.extract_info(url, download=False)
            if info is None:
                return None
            vid_id = info.get("id", "")
            dur = info.get("duration") or 0
            return {
                "id": vid_id,
                "title": info.get("title", "제목 없음"),
                "channel": info.get("channel") or info.get("uploader", "채널 미확인"),
                "duration": dur,
                "duration_str": _format_duration(dur),
                "thumbnail": info.get("thumbnail") or
                             f"https://img.youtube.com/vi/{vid_id}/hqdefault.jpg",
                "url": f"https://www.youtube.com/watch?v={vid_id}",
                "downloadable": True,
                "view_count": info.get("view_count") or 0,
                "score": 999,
                "group": "reference",
                "celeb_signals": [],
                "matched_keywords": [],
                "_manually_added": True,
            }
    except Exception as e:
        log_fn(f"[정보조회] 실패: {e}")
        return None


def save_results_csv(results, out_path):
    try:
        import csv
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        fields = ["score", "group", "id", "title", "channel",
                  "duration_str", "url", "downloadable", "view_count"]
        with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for row in results:
                writer.writerow({k: row.get(k, "") for k in fields})
    except Exception as e:
        print(f"[CSV] 실패: {e}")


# ── 하위 호환 래퍼 (app.py 가 구버전 함수를 import 해도 동작) ──────────────────

def search_youtube_videos(celeb_name, product_keyword, max_results=10,
                          score_threshold=50, log_fn=None):
    """구버전 호환 — 상품 중심 검색으로 내부 위임."""
    return search_product_videos(product_keyword, max_results=max_results,
                                  score_threshold=score_threshold, log_fn=log_fn)


def search_youtube_videos_product_mode(product_keyword, celeb_name="",
                                       category="", max_results=15,
                                       score_threshold=60, log_fn=None):
    """구버전 호환 — 상품 중심 검색으로 내부 위임."""
    return search_product_videos(product_keyword, max_results=max_results,
                                  score_threshold=score_threshold, log_fn=log_fn)


# 구버전 호환 상수
CATEGORY_KEYWORDS = {}
