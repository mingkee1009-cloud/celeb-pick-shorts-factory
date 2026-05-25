#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
app.py -- 연예인 픽템 쇼츠 자막 공장 (최종 확정판)

기본 흐름:
  1) 편집 완료 영상 업로드 + 미리보기
  2) 기본 정보 입력 (연예인명 · 제품명 · 상단 문구 · 출처)
  3) 자막 자동 추출 (Whisper) + 대사 수정
  4) 썸네일 문구 수정 + 미리보기
  5) 최종 영상 만들기

원칙:
  - 원본 음성 절대 유지
  - AI 음성 미사용
  - 자동 컷 편집 없음
  - edited_script.txt 존재 시 자동 대사 무시
"""

import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from subtitle_extractor import extract_subtitles
from make_final_shorts import make_final_short, render_thumbnail_preview

# -- 경로 설정 -----------------------------------------------------------------
CONFIG_PATH = ROOT / "config.json"
OUTPUT_DIR  = ROOT / "output"
INPUT_DIR   = ROOT / "input"
TEMP_DIR    = ROOT / ".tmp"
for _d in (OUTPUT_DIR, INPUT_DIR, TEMP_DIR):
    _d.mkdir(exist_ok=True)

MAX_SHORT_SEC  = 30.0
MAX_LINE_CHARS = 22


# -- 유틸 ---------------------------------------------------------------------
def load_config() -> dict:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return {}


def check_deps() -> list:
    missing = []
    if shutil.which("ffmpeg") is None:
        missing.append("ffmpeg")
    if shutil.which("ffprobe") is None:
        missing.append("ffprobe")
    try:
        from PIL import Image  # noqa
    except ImportError:
        missing.append("Pillow")
    return missing


def slugify(text: str, max_len: int = 30) -> str:
    text = re.sub(r'[^a-zA-Z0-9가-힣_\-]+', "_", (text or "item"))
    return text.strip("._")[:max_len] or "item"


def add_log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    st.session_state.log_lines.append(f"[{ts}] {msg}")


def get_video_duration(video_path: str, ffprobe: str = "ffprobe") -> float:
    try:
        r = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", video_path],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def capture_first_frame(video_path: str, ffmpeg: str, out_path: str) -> bool:
    """영상 첫 프레임을 360x640 이미지로 추출 (썸네일 미리보기용)."""
    try:
        subprocess.run([
            ffmpeg, "-y", "-loglevel", "error",
            "-ss", "0.3", "-i", video_path,
            "-frames:v", "1", "-q:v", "4",
            "-vf", "scale=360:640:force_original_aspect_ratio=increase,crop=360:640",
            out_path,
        ], capture_output=True, timeout=15)
        return Path(out_path).exists() and Path(out_path).stat().st_size > 0
    except Exception:
        return False


# -- Streamlit 설정 ------------------------------------------------------------
st.set_page_config(
    page_title="연예인 픽템 쇼츠 자막 공장",
    page_icon="🎬",
    layout="wide",
)

st.markdown("""
<style>
.title-box {
    background: linear-gradient(135deg,#0f0c29,#302b63,#24243e);
    border-radius:16px; padding:24px 36px; margin-bottom:18px; text-align:center;
}
.title-box h1 { color:#FFEB3B; font-size:1.9rem; margin:0; font-weight:900; }
.title-box p  { color:#aaa; margin:6px 0 0; font-size:0.9rem; }
.step-header {
    font-size:1.05rem; font-weight:700; color:#90CAF9;
    border-left:4px solid #90CAF9; padding:4px 12px;
    background:rgba(144,202,249,.08); border-radius:0 8px 8px 0;
    margin:22px 0 10px;
}
.stat-chip {
    display:inline-block; background:#1e2a3a; border:1px solid #2d4a6a;
    border-radius:20px; padding:3px 12px; font-size:0.82rem;
    color:#90CAF9; margin:2px 4px 2px 0;
}
.warn-chip {
    display:inline-block; background:#3a1e00; border:1px solid #ff8800;
    border-radius:20px; padding:3px 12px; font-size:0.82rem;
    color:#ffaa44; margin:2px 4px 2px 0;
}
.line-ok   { color:#66bb6a; font-size:0.85rem; }
.line-warn { color:#ffa726; font-size:0.85rem; }
.line-over { color:#ef5350; font-size:0.85rem; font-weight:700; }
.thumb-frame {
    border:2px solid #303060; border-radius:10px; overflow:hidden; background:#0a0a18;
}
.result-box {
    background:linear-gradient(135deg,#0a2a0a,#0a3a0a);
    border:2px solid #4CAF50; border-radius:12px; padding:16px; margin-top:12px;
}
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div class="title-box">
  <h1>🎬 연예인 픽템 쇼츠 자막 공장</h1>
  <p>영상 업로드 → 자막 추출 & 대사 수정 → 썸네일 확인 → 최종 쇼츠 완성</p>
</div>
""", unsafe_allow_html=True)

# 의존성 확인
_missing = check_deps()
if _missing:
    st.error(
        "필수 도구 없음: " + ", ".join(_missing) + "\n\n"
        "ffmpeg/ffprobe: https://ffmpeg.org/download.html\n"
        "Pillow: pip install Pillow"
    )
    st.stop()

config   = load_config()
_ffmpeg  = config.get("ffmpeg_path",  "ffmpeg")
_ffprobe = config.get("ffprobe_path", "ffprobe")

# -- 세션 상태 초기화 ----------------------------------------------------------
_defaults = [
    ("uploaded_video_path", ""),
    ("video_duration",       0.0),
    ("whisper_segments",     []),
    ("auto_subtitle_text",   ""),
    ("subtitle_extracted",   False),
    ("generation_done",      False),
    ("final_mp4",            ""),
    ("thumbnail_path",       ""),
    ("out_dir",              ""),
    ("log_lines",            []),
    ("trim_end",             None),
    ("frame_path",           ""),
    ("orig_result",        None),
    ("orig_manual_channel", ""),
    ("search_results",     []),
    ("searched",           False),
]
for _k, _v in _defaults:
    if _k not in st.session_state:
        st.session_state[_k] = _v
if "script_editor" not in st.session_state:
    st.session_state["script_editor"] = ""


# ============================================================================
# STEP 1: 영상 업로드 & 미리보기
# ============================================================================
st.markdown('<div class="step-header">① 영상 업로드 & 미리보기</div>',
            unsafe_allow_html=True)

col_up, col_prev = st.columns([1, 1])

with col_up:
    uploaded_file = st.file_uploader(
        "편집 완료 영상 업로드",
        type=["mp4", "mov", "webm", "m4v"],
        help="직접 편집 완료된 세로(9:16) 영상을 올려주세요.",
    )

    if uploaded_file is not None:
        save_path = INPUT_DIR / uploaded_file.name
        prev_name = Path(st.session_state.uploaded_video_path).name if st.session_state.uploaded_video_path else ""
        if prev_name != uploaded_file.name:
            with open(save_path, "wb") as _f:
                _f.write(uploaded_file.read())
            st.session_state.uploaded_video_path = str(save_path)
            st.session_state.video_duration = get_video_duration(str(save_path), _ffprobe)
            st.session_state.subtitle_extracted = False
            st.session_state.auto_subtitle_text = ""
            st.session_state["script_editor"] = ""
            st.session_state.generation_done = False
            frame_out = str(TEMP_DIR / "frame_preview.jpg")
            ok = capture_first_frame(str(save_path), _ffmpeg, frame_out)
            st.session_state.frame_path = frame_out if ok else ""

        dur = st.session_state.video_duration
        st.success(f"✅ **{uploaded_file.name}** ({dur:.1f}초)")

        if dur > MAX_SHORT_SEC:
            st.warning(f"영상이 {dur:.1f}초입니다. 쇼츠는 30~60초 권장합니다.")
            trim_opt = st.radio(
                "길이 처리",
                ["앞 30초만 사용", "전체 사용", "직접 지정 (초)"],
                horizontal=True, key="trim_opt",
            )
            if trim_opt == "앞 30초만 사용":
                st.session_state.trim_end = MAX_SHORT_SEC
            elif trim_opt == "전체 사용":
                st.session_state.trim_end = None
            else:
                st.session_state.trim_end = st.number_input(
                    "사용할 끝 시간 (초)",
                    min_value=1.0, max_value=float(dur),
                    value=min(MAX_SHORT_SEC, dur), step=1.0, key="trim_custom",
                )
        else:
            st.session_state.trim_end = None

    elif st.session_state.uploaded_video_path:
        st.info(f"이전 업로드: {Path(st.session_state.uploaded_video_path).name}")

with col_prev:
    vp = st.session_state.uploaded_video_path
    if vp and Path(vp).exists():
        st.video(vp)
        dur = st.session_state.video_duration
        eff = st.session_state.trim_end or dur
        st.caption(f"전체 {dur:.1f}초 | 사용 {eff:.1f}초")
    else:
        st.markdown(
            "<div style='background:#0d1117;border:1px dashed #30363d;border-radius:8px;"
            "height:200px;display:flex;align-items:center;justify-content:center;"
            "color:#555;font-size:0.9rem;'>영상 미리보기</div>",
            unsafe_allow_html=True,
        )


# ============================================================================
# STEP 2: 기본 정보 입력
# ============================================================================
st.markdown('<div class="step-header">② 기본 정보 입력</div>',
            unsafe_allow_html=True)

col_a, col_b = st.columns([1, 1])
with col_a:
    celeb_name = st.text_input("🌟 연예인 이름 *", placeholder="예: 고준희")
    product_name = st.text_input("🛍️ 제품명 *", placeholder="예: 썬크림")
    source_channel = st.text_input(
        "📌 출처 채널명",
        placeholder="예: 고준희 GO",
        help="하단에 '출처 [채널명]'으로 표시됩니다.",
    )
with col_b:
    hook_line1 = st.text_input(
        "📢 상단 첫 줄 문구 (흰색)",
        placeholder="예: 이렇게 맛있다고",
        help="상단 검정바 첫 번째 줄",
    )
    hook_line2 = st.text_input(
        "✨ 상단 강조 문구 (노란색)",
        placeholder="예: 고준희 다이어트 레시피 대공개",
        help="상단 검정바 두 번째 줄",
    )
    _hl1 = hook_line1 or "(첫 줄)"
    _hl2 = hook_line2 or "(강조 줄)"
    st.markdown(
        f"<div style='background:#0d1117;border:1px solid #30363d;border-radius:6px;"
        f"padding:8px 12px;font-size:0.82rem;margin-top:6px;'>"
        f"<span style='color:#fff;font-weight:700;'>▌ {_hl1}</span><br>"
        f"<span style='color:#FFEB3B;font-weight:700;'>▌ {_hl2}</span>"
        f"</div>",
        unsafe_allow_html=True,
    )


# ============================================================================
# STEP 3: 자막 자동 추출 & 대사 수정
# ============================================================================
st.markdown('<div class="step-header">③ 자막 자동 추출 & 대사 수정</div>',
            unsafe_allow_html=True)

video_ready = bool(
    st.session_state.uploaded_video_path
    and Path(st.session_state.uploaded_video_path).exists()
)

col_ebtn, col_etip = st.columns([1, 2])
with col_ebtn:
    extract_btn = st.button(
        "🎙️ 자막 자동 추출 (Whisper)",
        disabled=not video_ready,
        type="primary",
        key="btn_extract",
    )
with col_etip:
    st.caption(
        "Whisper로 영상 음성을 자동 텍스트 변환합니다. "
        "추출 후 아래 편집창에서 자유롭게 수정하세요. "
        "openai-whisper 미설치 시 직접 입력도 가능합니다."
    )

if extract_btn and video_ready:
    st.session_state.log_lines = []
    _log_area = st.empty()
    _prog = st.progress(0, text="Whisper 실행 중...")

    def _log_ex(msg: str):
        add_log(msg)
        _log_area.code("\n".join(st.session_state.log_lines[-8:]), language=None)

    _prog.progress(30, text="음성 추출 & 변환 중... (잠시 기다려주세요)")
    _res = extract_subtitles(
        video_path=st.session_state.uploaded_video_path,
        ffmpeg=_ffmpeg,
        log_fn=_log_ex,
    )
    _prog.progress(100, text="완료")

    if _res["success"]:
        st.session_state.auto_subtitle_text = _res["full_text"]
        st.session_state.whisper_segments   = _res["segments"]
        st.session_state.subtitle_extracted = True
        st.session_state["script_editor"]   = _res["full_text"]
        st.success(f"✅ 추출 완료 -- {len(_res['segments'])}개 구간 인식")
        add_log(f"Whisper: {len(_res['segments'])}구간 추출 완료")
        st.rerun()
    else:
        st.warning(
            f"자동 추출 실패: {_res['error']}\n\n"
            "아래 편집창에 직접 자막을 입력해주세요."
        )
        try:
            import whisper  # noqa
        except ImportError:
            st.info("openai-whisper 설치: pip install openai-whisper")

# -- 대사 편집창 ---------------------------------------------------------------
st.markdown("**✏️ 대사 수정** -- 한 줄 = 한 자막. Enter로 줄바꿈합니다.")

script_text: str = st.text_area(
    "대사 내용",
    key="script_editor",
    height=280,
    placeholder=(
        "자동 추출 후 여기서 자유롭게 수정하세요.\n\n"
        "예시:\n"
        "고준희가 다이어트할 때 꼭 챙긴다는 거\n"
        "이게 진짜 맛있으면서 저칼로리야\n"
        "매일 먹어도 안 질려"
    ),
    label_visibility="collapsed",
)

# -- 자막 통계 & 경고 ----------------------------------------------------------
if script_text.strip():
    _lines = [l for l in script_text.splitlines() if l.strip()]
    _total_chars = sum(len(l) for l in _lines)
    _eff_dur = st.session_state.trim_end or st.session_state.video_duration or 30.0
    _sec_per = _eff_dur / max(1, len(_lines))
    _long    = [(i + 1, l) for i, l in enumerate(_lines) if len(l) > MAX_LINE_CHARS]
    _use_wh  = (
        st.session_state.whisper_segments
        and len(st.session_state.whisper_segments) == len(_lines)
    )

    st.markdown(
        f'<span class="stat-chip">📝 {len(_lines)}줄</span>'
        f'<span class="stat-chip">🔤 {_total_chars}자</span>'
        f'<span class="stat-chip">⏱ 줄당 약 {_sec_per:.1f}초</span>'
        + ('<span class="stat-chip">🎙 Whisper 타이밍</span>' if _use_wh
           else '<span class="stat-chip">📐 균등 분배</span>'),
        unsafe_allow_html=True,
    )

    if _long:
        st.markdown(
            f'<span class="warn-chip">⚠️ {len(_long)}줄이 {MAX_LINE_CHARS}자 초과'
            ' -- 줄바꿈을 추가하면 자막이 더 잘 읽힙니다.</span>',
            unsafe_allow_html=True,
        )

    # 자막 미리보기
    with st.expander("🔍 자막 미리보기 (줄별 길이 확인)", expanded=False):
        _html = ""
        for _i2, _line in enumerate(_lines[:20], 1):
            _lc = len(_line)
            if _lc > MAX_LINE_CHARS + 5:
                _cls = "line-over"; _badge = f" ⚠️({_lc}자)"
            elif _lc > MAX_LINE_CHARS:
                _cls = "line-warn"; _badge = f" ({_lc}자)"
            else:
                _cls = "line-ok";   _badge = f" ({_lc}자)"
            _html += f'<div class="{_cls}"><b>{_i2:02d}.</b> {_line}{_badge}</div>'
        if len(_lines) > 20:
            _html += f'<div style="color:#666;">... 외 {len(_lines)-20}줄</div>'
        st.markdown(_html, unsafe_allow_html=True)

    # 저장 버튼
    if st.button("💾 대사 저장 (edited_script.txt)", key="btn_save_script"):
        _tmp_script = TEMP_DIR / "edited_script.txt"
        _tmp_script.write_text(script_text.strip() + "\n", encoding="utf-8")
        st.success(f"저장 완료")
else:
    if video_ready:
        st.caption("위 '자막 자동 추출'을 클릭하거나 직접 대사를 입력하세요.")


# ============================================================================
# STEP 4: 썸네일 문구 수정 & 미리보기
# ============================================================================
st.markdown('<div class="step-header">④ 썸네일 문구 수정 & 미리보기</div>',
            unsafe_allow_html=True)

col_te, col_tp = st.columns([1, 1])

with col_te:
    st.markdown("**썸네일에 표시할 문구**")
    st.caption("기본값은 상단 바 문구와 같습니다. 썸네일만 다르게 바꿀 수 있습니다.")

    # 첫 진입 시 hook 값으로 초기화
    if not st.session_state.get("thumb_l1_key"):
        st.session_state["thumb_l1_key"] = hook_line1
    if not st.session_state.get("thumb_l2_key"):
        st.session_state["thumb_l2_key"] = hook_line2

    thumb_l1 = st.text_input(
        "📌 썸네일 첫 줄 (흰색)", key="thumb_l1_key",
        placeholder="예: 이렇게 맛있다고",
    )
    thumb_l2 = st.text_input(
        "📌 썸네일 강조 줄 (노란색)", key="thumb_l2_key",
        placeholder="예: 고준희 다이어트 레시피 대공개",
    )

    _t1_final = thumb_l1.strip() or hook_line1
    _t2_final = thumb_l2.strip() or hook_line2

    st.markdown("---")
    st.markdown("**하단 고정 문구** (변경 불가)")
    _src_disp = source_channel or "(채널명 미입력)"
    st.markdown(
        f"<div style='color:#ccc;font-size:0.85rem;padding:4px 0;'>"
        f"출처  {_src_disp}</div>"
        f"<div style='color:#aef;font-size:0.85rem;padding:4px 0;'>제품은 프로필 링크</div>",
        unsafe_allow_html=True,
    )

with col_tp:
    st.markdown("**🖼️ 썸네일 미리보기** (실시간)")
    _prev_bytes = render_thumbnail_preview(
        hook_line1=_t1_final,
        hook_line2=_t2_final,
        frame_path=st.session_state.frame_path,
        tw=360, th=640,
    )
    if _prev_bytes:
        st.markdown('<div class="thumb-frame">', unsafe_allow_html=True)
        st.image(_prev_bytes, use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)
        st.caption("실제 썸네일은 1080×1920px로 저장됩니다.")
    else:
        st.info("썸네일 미리보기 생성 불가 (Pillow 확인)")


# ============================================================================
# STEP 5: 최종 영상 만들기
# ============================================================================
st.markdown('<div class="step-header">⑤ 최종 영상 만들기</div>',
            unsafe_allow_html=True)

_can_make = video_ready and bool(celeb_name) and bool(product_name) and bool(script_text.strip())

if not video_ready:
    st.caption("① 영상을 먼저 업로드해주세요.")
elif not celeb_name or not product_name:
    st.caption("② 연예인 이름과 제품명을 입력해주세요.")
elif not script_text.strip():
    st.caption("③ 자막을 추출하거나 직접 입력해주세요.")

make_btn = st.button(
    "🎬 최종 영상 만들기",
    type="primary",
    disabled=not _can_make,
    key="btn_make",
)

if make_btn and _can_make:
    st.session_state.generation_done = False
    st.session_state.log_lines       = []
    _log_area2 = st.empty()
    _prog2     = st.progress(0, text="준비 중...")

    def _log2(msg: str):
        add_log(msg)
        _log_area2.code("\n".join(st.session_state.log_lines[-12:]), language=None)

    _date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    _folder   = f"{_date_str}_{slugify(celeb_name)}_{slugify(product_name)}"
    _out_dir  = OUTPUT_DIR / _folder
    _prog2.progress(15, text="영상 합성 중...")

    _res2 = make_final_short(
        video_path=st.session_state.uploaded_video_path,
        edited_subtitle_text=script_text,
        whisper_segments=st.session_state.whisper_segments,
        hook_line1=hook_line1,
        hook_line2=hook_line2,
        source_channel=source_channel,
        celeb_name=celeb_name,
        product_name=product_name,
        out_dir=str(_out_dir),
        auto_subtitle_text=st.session_state.auto_subtitle_text,
        trim_end=st.session_state.trim_end,
        config=config,
        log_fn=_log2,
        edited_script_text=script_text,
        thumb_line1=thumb_l1,
        thumb_line2=thumb_l2,
    )
    _prog2.progress(100, text="완료")

    if _res2["success"]:
        st.session_state.generation_done = True
        st.session_state.final_mp4       = _res2["final_mp4"]
        st.session_state.thumbnail_path  = _res2["thumbnail"]
        st.session_state.out_dir         = str(_out_dir)
        st.success("🎉 최종 영상 생성 완료!")
        st.rerun()
    else:
        st.error(f"생성 실패: {_res2['error']}")
        add_log(f"[오류] {_res2['error']}")


# -- 결과물 표시 ---------------------------------------------------------------
if st.session_state.generation_done:
    _odir = Path(st.session_state.out_dir)
    st.markdown("---")
    st.markdown("### ✅ 완성 결과물")
    col_v2, col_t2 = st.columns([2, 1])

    with col_v2:
        _mp4 = st.session_state.final_mp4
        if _mp4 and Path(_mp4).exists():
            st.markdown("**🎬 완성 쇼츠**")
            st.video(_mp4)
            with open(_mp4, "rb") as _f:
                st.download_button(
                    "⬇️ final_short.mp4 다운로드",
                    data=_f,
                    file_name=f"final_short_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4",
                    mime="video/mp4",
                    type="primary",
                )

    with col_t2:
        _th = st.session_state.thumbnail_path
        if _th and Path(_th).exists():
            st.markdown("**🖼️ 썸네일**")
            st.image(_th, use_container_width=True)
            with open(_th, "rb") as _f:
                st.download_button(
                    "⬇️ thumbnail.png 다운로드",
                    data=_f, file_name="thumbnail.png", mime="image/png",
                )

    with st.expander("📄 생성된 텍스트 파일 보기"):
        for _fname, _label in [
            ("edited_script.txt",  "대사 수정본"),
            ("edited_subtitle.txt","자막 편집본"),
            ("auto_subtitle.txt",  "원본 자막 (Whisper)"),
            ("title.txt",          "제목 후보"),
            ("description.txt",    "설명문"),
            ("thumbnail_text.txt", "썸네일 문구"),
        ]:
            _fp = _odir / _fname
            if _fp.exists():
                st.markdown(f"**{_label}** (`{_fname}`)")
                st.code(_fp.read_text(encoding="utf-8"), language=None)

    st.markdown(
        f'<div class="result-box">📁 저장 위치: <code>{_odir}</code></div>',
        unsafe_allow_html=True,
    )


# ============================================================================
# 고급 옵션 (기본 화면에서 숨김)
# ============================================================================
with st.expander("⚙️ 고급 옵션 -- 원본 찾기 / 후보 영상 검색 (접기)", expanded=False):
    st.caption("기본 작업(업로드 → 자막 → 완성)에서는 사용하지 않아도 됩니다.")
    _atab1, _atab2 = st.tabs(["🔍 원본 영상 찾기", "📊 후보 영상 검색"])

    with _atab1:
        st.markdown("#### 참고 쇼츠 → 원본 영상 자동 탐색")
        try:
            from find_original_video import find_original_candidates as _foc
        except ImportError:
            _foc = None
            st.warning("find_original_video.py 없음")
        try:
            from search_related_videos import get_video_info as _gvi_orig
        except ImportError:
            _gvi_orig = None

        _su_col, _sb_col = st.columns([4, 1])
        with _su_col:
            _shorts_url = st.text_input(
                "쇼츠 URL", key="adv_shorts_url",
                placeholder="https://www.youtube.com/shorts/...",
                label_visibility="collapsed",
            )
        with _sb_col:
            _orig_btn = st.button(
                "🔎 원본 찾기", key="adv_orig_btn",
                disabled=not (_shorts_url.strip() and _foc),
            )
        _manual_ch = st.text_input(
            "📺 채널명 직접 입력",
            value=st.session_state.orig_manual_channel,
            key="adv_manual_ch",
            placeholder="예: 고준희Official",
        )
        st.session_state.orig_manual_channel = _manual_ch

        if _orig_btn and _foc:
            _olog = []
            with st.spinner("분석 중..."):
                _ores = _foc(
                    shorts_url=_shorts_url.strip(),
                    manual_source_channel=_manual_ch,
                    max_results=8,
                    log_fn=_olog.append,
                )
            st.session_state.orig_result = _ores
            for _m in _olog: add_log(_m)

        _or = st.session_state.orig_result
        if _or:
            if _or.get("error"):
                st.error(_or["error"])
            elif _or.get("no_source"):
                st.warning("출처를 찾지 못했습니다. 채널명을 직접 입력해주세요.")
            else:
                _srcs  = _or.get("keywords", {}).get("source_channels", [])
                _cands = _or.get("candidates", [])
                if _srcs:
                    _chips = " ".join(
                        f'<span style="background:#4A148C33;color:#CE93D8;'
                        f'border:1px solid #CE93D8;border-radius:12px;'
                        f'padding:2px 8px;font-size:0.78rem;">📌 {n} ({s}점)</span>'
                        for n, s in _srcs
                    )
                    st.markdown(f"<div>감지된 출처: {_chips}</div>", unsafe_allow_html=True)
                for _i, _c in enumerate(_cands):
                    _sc = _c["score"]
                    _cc = "#4CAF50" if _sc >= 70 else "#FF9800" if _sc >= 40 else "#888"
                    _ca2, _cb2, _cc2 = st.columns([0.5, 1.5, 3])
                    with _cb2:
                        st.image(_c["thumbnail"], use_container_width=True)
                    with _cc2:
                        st.markdown(f"**{_c['title'][:60]}**")
                        st.caption(f"{_c['channel']} | {_c['duration_str']}")
                        st.markdown(
                            f'<span style="color:{_cc};font-size:0.85rem;">● {_sc}점</span>',
                            unsafe_allow_html=True,
                        )
                        st.markdown(f"[YouTube에서 보기]({_c['url']})")
                    st.divider()

    with _atab2:
        st.markdown("#### 상품 기준 연예인 후보 영상 검색")
        try:
            from search_related_videos import search_product_videos as _spv
        except ImportError:
            _spv = None
            st.warning("search_related_videos.py 없음")

        _adv_prod = st.text_input("상품명", key="adv_product", placeholder="예: 저당간식")
        _adv_sbtn = st.button(
            "🔍 후보 검색", key="adv_search_btn",
            disabled=not (_adv_prod and _spv),
        )
        if _adv_sbtn and _spv:
            _sr = _spv(_adv_prod, max_results=12, log_fn=add_log)
            st.session_state.search_results = _sr[:16]

        if st.session_state.search_results:
            st.markdown(f"**검색 결과 {len(st.session_state.search_results)}개**")
            for _v in st.session_state.search_results[:8]:
                _vc1, _vc2 = st.columns([1, 4])
                with _vc1:
                    if _v.get("thumbnail"):
                        st.image(_v["thumbnail"], use_container_width=True)
                with _vc2:
                    st.markdown(f"**{_v['title'][:70]}**")
                    st.caption(f"{_v.get('channel','')} | {_v.get('duration_str','')}")
                    st.markdown(f"[YouTube에서 보기]({_v.get('url','')})")
                st.divider()


# -- 사이드바 ------------------------------------------------------------------
with st.sidebar:
    st.markdown("### 📋 진행 로그")
    if st.session_state.log_lines:
        st.code("\n".join(st.session_state.log_lines[-30:]), language=None)
    else:
        st.caption("로그가 여기에 표시됩니다.")

    st.divider()
    st.markdown("### ℹ️ 사용법")
    st.markdown(
        "1. **영상 업로드**\n"
        "2. **연예인명·제품명** 입력\n"
        "3. **상단 문구·출처** 입력\n"
        "4. **자막 자동 추출** 클릭\n"
        "5. **대사 수정** (줄바꿈 자유)\n"
        "6. **썸네일 문구** 확인·수정\n"
        "7. **최종 영상 만들기** 클릭\n"
        "8. **다운로드**\n\n"
        "> 원본 음성 자동 유지\n"
        "> AI 음성 미사용"
    )

    st.divider()
    st.markdown("### 📂 최근 결과")
    if OUTPUT_DIR.exists():
        for _rd in sorted(OUTPUT_DIR.iterdir(), reverse=True)[:5]:
            if _rd.is_dir():
                st.caption(f"📁 {_rd.name}")
