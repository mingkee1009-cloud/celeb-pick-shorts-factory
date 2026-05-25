#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
streamlit_app_check.py
app.py 의 import, 문법, 의존성을 체크한다.
실행: python streamlit_app_check.py
"""
import ast, sys, subprocess, importlib.util
from pathlib import Path

ROOT = Path(__file__).parent
OK = "✅"; NG = "❌"; WN = "⚠️ "
passed = failed = 0

def show(label, ok, note=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  {OK} {label}" + (f"  ({note})" if note else ""))
    else:
        failed += 1
        print(f"  {NG} {label}" + (f"  --> {note}" if note else ""))

print()
print("=" * 56)
print("  app.py 배포 가능성 점검")
print("=" * 56)

# 1. app.py 존재
app_path = ROOT / "app.py"
show("app.py 존재", app_path.exists())

# 2. 문법 검사
if app_path.exists():
    try:
        src = app_path.read_text(encoding="utf-8")
        ast.parse(src)
        show("app.py 문법 정상", True)
    except SyntaxError as e:
        show("app.py 문법 정상", False, f"line {e.lineno}: {e.msg}")

# 3. 로컬 모듈 존재
for mod in ["subtitle_extractor", "make_final_shorts"]:
    show(f"{mod}.py 존재", (ROOT / f"{mod}.py").exists())

# 4. 로컬 모듈 문법
for mod in ["subtitle_extractor", "make_final_shorts",
            "find_original_video", "search_related_videos"]:
    fp = ROOT / f"{mod}.py"
    if fp.exists():
        try:
            ast.parse(fp.read_text(encoding="utf-8"))
            show(f"{mod}.py 문법 정상", True)
        except SyntaxError as e:
            show(f"{mod}.py 문법 정상", False, f"line {e.lineno}: {e.msg}")

# 5. 패키지 import 체크
for pkg, inst in [
    ("streamlit",  "pip install streamlit"),
    ("PIL",        "pip install Pillow"),
    ("whisper",    "pip install openai-whisper"),
    ("yt_dlp",     "pip install yt-dlp"),
    ("numpy",      "pip install numpy"),
]:
    try:
        __import__(pkg)
        show(f"import {pkg}", True)
    except ImportError:
        show(f"import {pkg}", False, inst)

# 6. ffmpeg
r = subprocess.run(["ffmpeg", "-version"], capture_output=True)
show("ffmpeg 실행 (로컬)", r.returncode == 0,
     "클라우드: packages.txt 로 자동 설치됨")

r2 = subprocess.run(["ffprobe", "-version"], capture_output=True)
show("ffprobe 실행 (로컬)", r2.returncode == 0,
     "클라우드: ffmpeg 패키지에 포함")

# 7. Whisper 모델 기본값 확인
se = ROOT / "subtitle_extractor.py"
if se.exists():
    import re
    m = re.search(r'model_size.*?=.*?"(\w+)"', se.read_text(encoding="utf-8"))
    model = m.group(1) if m else "unknown"
    ok_model = model in ("tiny", "base")
    show(f"Whisper 기본 모델: {model}",
         ok_model,
         "" if ok_model else "클라우드 메모리 초과 위험 — tiny 권장")

# ── 최종 판정
print()
print("=" * 56)
if failed == 0:
    print(f"  🚀 {passed}개 전부 통과 — 즉시 배포 가능!")
elif failed <= 2:
    print(f"  ⚠️  {failed}개 경고 (클라우드에서는 자동 해결될 수 있음)")
    print(f"     통과 {passed}개 / 실패 {failed}개")
else:
    print(f"  ❌ {failed}개 수정 필요 (위 목록 확인)")
print("=" * 56)
print()
