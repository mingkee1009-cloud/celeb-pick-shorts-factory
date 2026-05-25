#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
find_original_video.py — 출처 채널 추적 방식 원본 영상 탐색 모듈

핵심 원칙:
  1) 쇼츠 제목·설명·해시태그·자막·고정댓글에서 출처 채널을 추출한다.
  2) 출처 채널이 있으면 그 채널 중심으로만 검색한다.
  3) 출처가 없으면 no_source=True 반환 — 일반 검색 절대 금지.
  4) 의사/피부과/리뷰/쇼핑 채널은 제외한다.
  5) 쇼츠(≤60s)는 -50점 패널티로 원본 후보 하위로 밀어낸다.
"""

import re
import time


# ── 연예인 이름 사전 ────────────────────────────────────────────────────────────
CELEB_DICT = {
    "고준희", "백예린", "장원영", "카리나", "윈터", "닝닝", "지젤",
    "안유진", "이서", "레이", "가을", "리즈", "원희",
    "아이유", "태연", "제니", "지수", "로제", "리사",
    "수지", "강민경", "이사배", "한소희", "고현정",
    "설현", "나연", "지효", "모모", "사나", "미나", "다현", "채영",
    "솔라", "문별", "화사", "휘인",
    "슬기", "조이", "예리", "웬디", "아이린",
    "소미", "청하", "선미",
    "히카루", "사쿠라", "채원", "유나", "예나", "민주",
    "권은비", "김채원", "최예나", "조유리",
    "김세정", "기은세", "전소미",
    "뷔", "지민", "정국", "진", "슈가", "제이홉", "남준",
    "카이", "찬열", "수호", "시우민",
    "태용", "재현", "해찬", "런쥔", "마크", "도영",
    "전지현", "김태희", "박민영", "문가영", "박신혜",
    "김고은", "손예진", "공효진", "이민정", "이영애",
    "신민아", "한가인", "이하늬", "엄정화", "이나영",
    "박소담", "김다미", "전여빈", "이주영",
    "박봄", "산다라", "공민지", "이채연",
    "솔지", "혜린", "정화",
    "김정난", "김혜수", "전도연", "이정은", "나문희",
    "오나라", "라미란", "염정아", "박소현", "이효리",
}

# 조사 목록
JOSA = (
    "한테서", "에게서", "이랑", "한테", "에게", "으로", "로",
    "는", "은", "이", "가", "도", "와", "과", "의", "을", "를", "랑",
)

# 노이즈 단어 블랙리스트
NOISE_WORDS = {
    "기초", "제품", "피부", "화장품", "루틴", "선크림", "앰플",
    "보습", "모공", "잡티", "스킨", "로션", "크림", "세럼", "에센스",
    "클렌징", "파운데이션", "쿠션", "마스카라", "뷰티", "메이크업",
    "뷰티템", "파우치",
    "간식", "다이어트", "식단", "먹방", "칼로리", "단백질", "저당",
    "제로", "탄수화물", "샐러드", "닭가슴살", "저당간식",
    "너무", "정말", "진짜", "완전", "그냥", "이거", "이게",
    "좋아서", "좋은", "좋아", "싫어", "최고", "최애",
    "많이", "빨리", "항상", "매일", "계속",
    "사용", "관리", "추천", "소개", "광고", "협찬", "구매",
    "내돈내산", "직구", "후기", "리뷰", "언박싱", "하울",
    "구독", "좋아요", "알림", "댓글",
    "아이템", "찐템", "추천템", "패션템", "생활템",
    "브이로그", "브이", "쇼츠", "영상", "유튜브",
    "연예인", "아이돌", "배우", "가수", "모델", "셀럽",
    "방송", "드라마",
    "저번", "이번", "지난", "오늘", "어제", "내일",
    "우리", "여기", "거기", "이런", "저런",
    "핵심", "포인트", "꿀팁",
}

# ── 출처 표시 패턴 (우선순위 순) ─────────────────────────────────────────────
SOURCE_EXPLICIT_PATTERNS = [
    # 1순위 (score=90): 명시적 출처 레이블
    r"출처\s*[:：]\s*([^\n#@]{2,30})",
    r"원본\s*[:：]\s*([^\n#@]{2,30})",
    r"영상\s*출처\s*[:：]\s*([^\n#@]{2,30})",
    r"원본\s*영상\s*[:：]\s*([^\n#@]{2,30})",
    r"source\s*[:：]\s*([^\n#@]{2,30})",
    r"from\s*[:：]\s*([^\n#@]{2,30})",
    r"full\s*(?:video|ver(?:sion)?)\s*[:：]\s*([^\n#@]{2,30})",
    r"원본\s*링크\s*[:：]\s*([^\n#@]{2,30})",
    r"공식\s*채널\s*[:：]\s*([^\n#@]{2,30})",
    # 2순위 (score=70): 인라인 출처 문구 — [ \t] 만 허용, \n 금지
    r"(?:출처|원본|source|from|영상출처)[ \t]+([가-힣a-zA-Z0-9_\- \t]{2,20}?)(?:[ \t]|$|#|@|\n)",
    r"(?:유튜브|youtube)\s*[：:]\s*([^\n#@]{2,25})",
    r"(?:채널|channel)\s*[：:]\s*([^\n#@]{2,25})",
    r"공식\s*([가-힣a-zA-Z0-9_\-\s]{2,20}?)(?:\s|$|#|@|\n)",
    # 3순위 (score=60): @멘션
    r"@([a-zA-Z0-9가-힣_\-]{2,25})",
]

# 명시적 레이블 인덱스 범위
_IDX_LABEL_END  = 9    # [0:9] → score=90
_IDX_INLINE_END = 13   # [9:13] → score=70
# [-1] → score=60 (@멘션)

# ── 제외 채널 패턴 ────────────────────────────────────────────────────────────
EXCLUDE_CHANNEL_PATTERNS = [
    r"의사", r"피부과", r"성형", r"병원", r"클리닉", r"닥터", r"doctor", r"dr\.",
    r"건강", r"헬스", r"nutrition", r"영양",
    r"리뷰", r"review", r"하울", r"haul", r"unboxing", r"언박싱",
    r"쇼핑", r"shopping", r"스토어", r"store", r"몰", r"mall",
    r"광고", r"sponsor",
    r"뉴스", r"news", r"정보", r"info",
]


# ── 조사 제거 ───────────────────────────────────────────────────────────────────
def _strip_josa(word: str) -> str:
    for j in sorted(JOSA, key=len, reverse=True):
        if word.endswith(j) and len(word) - len(j) >= 2:
            return word[: -len(j)]
    return word


def _is_valid_celeb_name(name: str) -> bool:
    if not name:
        return False
    if name in NOISE_WORDS:
        return False
    if len(name) < 2 or len(name) > 5:
        return False
    if len(set(name)) == 1:
        return False
    return True


# ── 출처 채널 추출 ────────────────────────────────────────────────────────────
def extract_source_channels(meta: dict) -> list:
    """
    쇼츠 메타데이터에서 출처 채널 후보를 우선순위 순으로 추출한다.
    반환: [(채널명, 신뢰도점수), ...]  신뢰도 내림차순
    검색 범위: 제목 + 설명 + 자막 + 고정댓글
    """
    desc     = meta.get("description", "") or ""
    subs     = meta.get("subtitles_text", "") or ""
    title    = meta.get("title", "") or ""
    channel  = meta.get("channel", "") or ""
    tags     = meta.get("hashtags", []) or []
    comments = meta.get("pinned_comments", "") or ""   # 고정댓글

    # 전체 검색 대상 텍스트
    full = f"{desc}\n{subs}\n{title}\n{comments}"

    sources: dict[str, int] = {}

    def _add(name: str, score: int):
        name = name.strip().strip("：: \t\n")
        if name.startswith("http") or name.startswith("www"):
            return
        if not name or len(name) < 2:
            return
        if name.lower() == channel.lower():
            return
        if name in NOISE_WORDS:
            return
        sources[name] = max(sources.get(name, 0), score)

    # 1순위 (score=90): 명시적 레이블
    for pat in SOURCE_EXPLICIT_PATTERNS[:_IDX_LABEL_END]:
        for m in re.finditer(pat, full, re.IGNORECASE | re.MULTILINE):
            _add(m.group(1), 90)

    # 2순위 (score=70): 인라인 출처 문구
    for pat in SOURCE_EXPLICIT_PATTERNS[_IDX_LABEL_END:_IDX_INLINE_END]:
        for m in re.finditer(pat, full, re.IGNORECASE | re.MULTILINE):
            _add(m.group(1), 70)

    # 3순위 (score=60): @멘션
    for m in re.finditer(SOURCE_EXPLICIT_PATTERNS[-1], full, re.IGNORECASE):
        _add(m.group(1), 60)

    # 4순위 (score=50): 해시태그 중 연예인 이름 포함
    for tag in tags:
        for celeb in CELEB_DICT:
            if celeb in tag and tag != celeb:
                _add(tag, 50)
                break

    # 5순위 (score=40): 제목·설명에 등장하는 연예인 이름
    for celeb in CELEB_DICT:
        if celeb in title or celeb in desc:
            _add(celeb, 40)

    ranked = sorted(sources.items(), key=lambda x: x[1], reverse=True)
    return ranked[:5]


# ── 연예인 이름 추출 ────────────────────────────────────────────────────────────
CELEB_TRIGGER_PATTERNS = [
    r"([가-힣]{2,5})(?:이|가|은|는|도)\s+(?:추천|픽|루틴|쓰는|먹는|바르는|좋아하는|즐겨)",
    r"([가-힣]{2,5})(?:이|가|은|는|도)\s+(?:직접|매일|애용|사용)",
    r"([가-힣]{2,5})\s*(?:PICK|Pick|pick|픽|추천|루틴|하울|먹방|일상|브이로그)",
    r"([가-힣]{2,5})\s*(?:이|가)\s+",
]


def extract_celeb_names(title: str, desc: str, subs: str, hashtags: list) -> list:
    found, seen = [], set()

    def _add(name: str):
        name = _strip_josa(name.strip())
        if name and name not in seen and _is_valid_celeb_name(name):
            found.append(name)
            seen.add(name)

    # CELEB_DICT 직접 매칭 (가장 정확)
    for candidate in CELEB_DICT:
        if candidate in title or candidate in subs:
            _add(candidate)

    # 트리거 패턴 (제목에서만, CELEB_DICT 또는 3자 이하)
    for pat in CELEB_TRIGGER_PATTERNS:
        for m in re.finditer(pat, title):
            name = _strip_josa(m.group(1))
            if not _is_valid_celeb_name(name):
                continue
            if name in CELEB_DICT or len(name) <= 3:
                _add(name)

    # 설명·해시태그에서 CELEB_DICT 매칭
    for candidate in CELEB_DICT:
        if candidate in desc:
            _add(candidate)
    for tag in hashtags:
        tag_clean = _strip_josa(tag)
        if tag_clean in CELEB_DICT:
            _add(tag_clean)

    return found[:5]


# ── 채널 유사도 ────────────────────────────────────────────────────────────────
def channel_similarity(source: str, candidate: str) -> int:
    """
    출처 채널명과 후보 채널명의 유사도를 0~100 점수로 반환한다.
      완전 일치(공백 포함/제거)  100
      한쪽이 포함 관계            80
      연예인 이름 공유            60
      자카드 ≥ 0.5               0~40
      무관                       0
    """
    if not source or not candidate:
        return 0

    s = source.lower().strip()
    c = candidate.lower().strip()

    if not s or not c:
        return 0

    # 완전 일치
    if s == c:
        return 100

    # 포함 관계 (원본 포함)
    if s in c or c in s:
        return 80

    # 공백 제거 후 비교
    s_norm = s.replace(" ", "")
    c_norm = c.replace(" ", "")
    if s_norm and c_norm:
        if s_norm == c_norm:
            return 100
        if s_norm in c_norm or c_norm in s_norm:
            return 80

    # 연예인 이름 공유
    for celeb in CELEB_DICT:
        celeb_l = celeb.lower()
        if celeb_l in s and celeb_l in c:
            return 60

    # 자카드 유사도 (문자 집합, 공백 제거)
    s_set = set(s_norm)
    c_set = set(c_norm)
    if s_set and c_set:
        jaccard = len(s_set & c_set) / len(s_set | c_set)
        if jaccard >= 0.5:
            return int(jaccard * 40)

    return 0


def _is_excluded_channel(channel: str) -> bool:
    cl = channel.lower()
    for pat in EXCLUDE_CHANNEL_PATTERNS:
        if re.search(pat, cl, re.IGNORECASE):
            return True
    return False


# ── 검색 쿼리 생성 ────────────────────────────────────────────────────────────
def build_source_queries(source_channel: str, celeb_names: list,
                         product_keyword: str) -> list:
    """
    출처 채널 중심의 검색 쿼리를 생성한다.
    인용부호를 사용해 정확도를 높인다.
    """
    q: list[str] = []
    src = source_channel.strip()
    celebs = celeb_names[:2]
    prod = product_keyword.strip()

    # 인용부호 포함 쿼리 (정확 검색)
    for celeb in celebs:
        if prod:
            q.append(f'"{src}" "{celeb}" "{prod}"')
        q.append(f'"{src}" "{celeb}"')

    if prod:
        q.append(f'"{src}" "{prod}"')

    # 원본/full video 쿼리
    q.append(f'"{src}" 원본')
    q.append(f'"{src}" full video')

    # 연예인 + 채널 역순 쿼리
    for celeb in celebs:
        if prod:
            q.append(f'"{celeb}" "{prod}" "{src}"')
        q.append(f'"{celeb}" "{src}"')

    # 비인용부호 폴백
    q.append(src)
    for celeb in celebs:
        q.append(f"{src} {celeb}")

    # 중복 제거
    seen: set[str] = set()
    result: list[str] = []
    for item in q:
        item = item.strip()
        if item and item not in seen:
            seen.add(item)
            result.append(item)

    return result[:12]


# ── 원본 가능성 점수 ───────────────────────────────────────────────────────────
def score_original(
    entry: dict,
    source_channels: list,
    celeb_names: list,
    product_keyword: str,
) -> tuple:
    """
    (score, ch_sim) 반환.
    점수 기준:
      채널명이 출처 채널과 완전 일치   +100
      채널명에 출처 채널명 일부 포함   +80
      채널명에 연예인 이름 포함        +60 (ch_sim<60 일 때 보정)
      제목에 연예인 이름               +30
      제목에 제품명 완전 일치          +30
      제목에 제품 키워드 포함          +20
      영상 길이 3분+                  +20
      영상 길이 60초 이하              -50
    """
    title        = (entry.get("title") or "").lower()
    channel      = (entry.get("channel") or entry.get("uploader") or "")
    channel_low  = channel.lower()
    dur          = entry.get("duration") or 0

    # 출처 채널 유사도
    ch_sim = 0
    for src_name, _ in source_channels:
        sim = channel_similarity(src_name, channel)
        ch_sim = max(ch_sim, sim)

    # 채널명에 연예인 이름 포함 보정 (출처 채널 점수가 낮을 때)
    if ch_sim < 60:
        for name in celeb_names:
            if name and name.lower() in channel_low:
                ch_sim = max(ch_sim, 60)
                break

    score = ch_sim

    # 제목에 연예인 이름
    for name in celeb_names:
        if name and name.lower() in title:
            score += 30
            break

    # 제목에 제품명
    pk = product_keyword.lower().strip()
    if pk and pk in title:
        score += 30
    elif pk:
        for word in pk.split():
            if len(word) >= 2 and word in title:
                score += 20
                break

    # 길이 보너스/패널티
    if dur >= 180:
        score += 20
    elif 0 < dur <= 60:
        score -= 50

    return max(score, 0), ch_sim


# ── 메타데이터 추출 ───────────────────────────────────────────────────────────
def get_shorts_metadata(url: str, log_fn=None, fetch_comments: bool = True):
    if log_fn is None:
        log_fn = print
    try:
        import yt_dlp
    except ImportError:
        log_fn("[원본 찾기] yt-dlp 없음")
        return None

    opts = {
        "quiet": True, "no_warnings": True,
        "skip_download": True,
        "writesubtitles": False, "writeautomaticsub": False,
        "subtitleslangs": ["ko", "en"],
        "ignoreerrors": True,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        if info is None:
            return None

        desc     = info.get("description") or ""
        hashtags = re.findall(r"#([\w가-힣]+)", desc)
        sub_text = _extract_subtitle_text(info)

        meta = {
            "id":              info.get("id", ""),
            "title":           info.get("title", ""),
            "channel":         info.get("channel") or info.get("uploader", ""),
            "channel_id":      info.get("channel_id") or info.get("uploader_id", ""),
            "description":     desc,
            "duration":        info.get("duration") or 0,
            "hashtags":        hashtags,
            "subtitles_text":  sub_text,
            "view_count":      info.get("view_count") or 0,
            "thumbnail":       info.get("thumbnail", ""),
            "url":             f"https://www.youtube.com/watch?v={info.get('id','')}",
            "pinned_comments": "",
        }

        # 고정댓글 수집 (실패해도 진행)
        if fetch_comments:
            try:
                comment_text = _fetch_pinned_comments(url, log_fn)
                meta["pinned_comments"] = comment_text
            except Exception as e:
                log_fn(f"[원본 찾기] 고정댓글 수집 실패 (무시): {e}")

        return meta

    except Exception as e:
        log_fn(f"[원본 찾기] 메타데이터 조회 실패: {e}")
        return None


def _fetch_pinned_comments(url: str, log_fn=None) -> str:
    """고정댓글 또는 상단 댓글 5개를 가져와 텍스트로 반환."""
    if log_fn is None:
        log_fn = print
    try:
        import yt_dlp
        opts = {
            "quiet": True, "no_warnings": True,
            "skip_download": True,
            "getcomments": True,
            "extractor_args": {
                "youtube": {"max_comments": ["5", "5", "0", "0"]}
            },
            "ignoreerrors": True,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        if not info:
            return ""
        comments = info.get("comments") or []
        texts = []
        for c in comments[:5]:
            t = (c.get("text") or "").strip()
            if t:
                texts.append(t)
        result = "\n".join(texts)
        if result:
            log_fn(f"[원본 찾기] 댓글 {len(texts)}개 수집")
        return result
    except Exception:
        return ""


def _extract_subtitle_text(info: dict) -> str:
    sub_text = ""
    for key in ("subtitles", "automatic_captions"):
        subs = info.get(key, {})
        if not subs:
            continue
        for lang in ("ko", "ko-KR", "en"):
            if lang not in subs:
                continue
            for entry in (subs[lang] or []):
                if isinstance(entry, dict) and "data" in entry:
                    sub_text += entry["data"] + " "
    return sub_text.strip()


# ── 키워드 종합 추출 ───────────────────────────────────────────────────────────
def extract_keywords(meta: dict) -> dict:
    title    = meta.get("title", "") or ""
    desc     = meta.get("description", "") or ""
    subs     = meta.get("subtitles_text", "") or ""
    tags     = meta.get("hashtags", []) or []

    celeb_candidates = extract_celeb_names(title, desc, subs, tags)
    source_channels  = extract_source_channels(meta)

    product_hints = []
    for tag in tags:
        tag_c = _strip_josa(tag)
        if (tag_c not in NOISE_WORDS
                and tag_c not in celeb_candidates
                and tag_c not in CELEB_DICT
                and 2 <= len(tag_c) <= 10):
            product_hints.append(tag_c)

    return {
        "celeb_candidates": celeb_candidates,
        "product_hints":    product_hints[:5],
        "source_channels":  source_channels,
        "hashtags":         tags[:10],
        "title":            title,
        "channel":          meta.get("channel", ""),
        "celeb_found":      len(celeb_candidates) > 0,
        "source_found":     len(source_channels) > 0,
    }


# ── 메인 함수 ─────────────────────────────────────────────────────────────────
def find_original_candidates(
    shorts_url: str,
    product_keyword: str = "",
    manual_source_channel: str = "",
    max_results: int = 10,
    log_fn=None,
) -> dict:
    """
    쇼츠 URL을 받아 출처 채널 기반으로 원본 후보 목록을 반환한다.

    반환값:
      meta, keywords, queries, candidates, error,
      no_source (True=출처 못 찾음 → UI에서 수동 입력 요청)
    """
    if log_fn is None:
        log_fn = print

    log_fn("[원본 찾기] 쇼츠 메타데이터 수집 중...")
    meta = get_shorts_metadata(shorts_url, log_fn=log_fn, fetch_comments=True)
    if meta is None:
        return {"meta": None, "keywords": {}, "queries": [],
                "candidates": [], "error": "쇼츠 정보를 가져올 수 없습니다.",
                "no_source": False}

    log_fn(f"[원본 찾기] 제목: {meta['title'][:60]}")
    log_fn(f"[원본 찾기] 채널: {meta['channel']} | 길이: {meta['duration']}s")

    kw = extract_keywords(meta)
    log_fn(f"[원본 찾기] 연예인: {kw['celeb_candidates']}")
    log_fn(f"[원본 찾기] 출처 채널 후보: {[s for s, _ in kw['source_channels']]}")

    # 출처 채널 확정 (수동 입력 우선)
    source_channels = kw["source_channels"]
    if manual_source_channel.strip():
        manual = manual_source_channel.strip()
        log_fn(f"[원본 찾기] 수동 출처 채널 사용: {manual}")
        source_channels = [(manual, 95)] + [
            (n, s) for n, s in source_channels if n != manual
        ]
        kw["source_channels"] = source_channels

    if not source_channels:
        log_fn("[원본 찾기] 출처 채널을 찾지 못했습니다.")
        return {
            "meta": meta, "keywords": kw, "queries": [],
            "candidates": [], "error": None, "no_source": True,
        }

    # 검색 쿼리 생성
    primary_source = source_channels[0][0]
    queries = build_source_queries(
        primary_source, kw["celeb_candidates"], product_keyword
    )
    for src_name, src_score in source_channels[1:3]:
        if src_score >= 60:
            for q in build_source_queries(src_name, kw["celeb_candidates"], product_keyword)[:3]:
                if q not in queries:
                    queries.append(q)

    log_fn(f"[원본 찾기] 쿼리 {len(queries)}개 생성")

    try:
        import yt_dlp
    except ImportError:
        return {"meta": meta, "keywords": kw, "queries": queries,
                "candidates": [], "error": "yt-dlp 없음", "no_source": False}

    seen_ids   = {meta["id"]}
    candidates = []
    rejected   = 0

    for query in queries:
        log_fn(f"[원본 찾기] 검색: {query}")
        try:
            with yt_dlp.YoutubeDL({
                "quiet": True, "no_warnings": True,
                "extract_flat": True, "ignoreerrors": True,
                "skip_download": True,
            }) as ydl:
                info = ydl.extract_info(f"ytsearch15:{query}", download=False)
                if not info or "entries" not in info:
                    continue
                for entry in (info["entries"] or []):
                    if not entry:
                        continue
                    vid_id = entry.get("id", "")
                    if not vid_id or vid_id in seen_ids:
                        continue
                    seen_ids.add(vid_id)

                    ch = entry.get("channel") or entry.get("uploader") or ""

                    # 제외 채널 필터
                    if _is_excluded_channel(ch):
                        rejected += 1
                        continue

                    dur = entry.get("duration") or 0
                    score, ch_sim = score_original(
                        entry, source_channels, kw["celeb_candidates"], product_keyword
                    )

                    # 출처 채널과 무관한 채널 제외
                    min_sim = 20 if manual_source_channel else 40
                    if ch_sim < min_sim:
                        rejected += 1
                        continue

                    thumb = (entry.get("thumbnail") or
                             f"https://img.youtube.com/vi/{vid_id}/hqdefault.jpg")

                    candidates.append({
                        "id":           vid_id,
                        "title":        entry.get("title", "제목 없음"),
                        "channel":      ch,
                        "duration":     dur,
                        "duration_str": _fmt_dur(dur),
                        "thumbnail":    thumb,
                        "url":          f"https://www.youtube.com/watch?v={vid_id}",
                        "view_count":   entry.get("view_count") or 0,
                        "score":        score,
                        "ch_sim":       ch_sim,
                        "is_shorts":    0 < dur <= 60,
                    })
        except Exception as e:
            log_fn(f"[원본 찾기] 쿼리 실패: {e}")
        time.sleep(0.3)

    log_fn(f"[원본 찾기] 무관 채널 제외: {rejected}개")
    candidates.sort(key=lambda x: x["score"], reverse=True)
    top = candidates[:max_results]
    log_fn(f"[원본 찾기] 원본 후보 {len(top)}개 반환")

    return {
        "meta":       meta,
        "keywords":   kw,
        "queries":    queries,
        "candidates": top,
        "error":      None,
        "no_source":  False,
    }


def _fmt_dur(seconds) -> str:
    if not seconds:
        return "알 수 없음"
    try:
        seconds = int(seconds)
    except Exception:
        return "알 수 없음"
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
