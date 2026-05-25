#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
deploy_ready_check.py
배포 전 자동 체크 스크립트.
실행: python deploy_ready_check.py
"""
import os, sys, subprocess, importlib
from pathlib import Path

ROOT = Path(__file__).parent
PASS = "✅"; FAIL = "❌"; WARN = "⚠️ "

results = []

def check(label, ok, detail=""):
    mark = PASS if ok else FAIL
    msg = f"  {mark} {label}"
    if detail:
        msg += f"  ({detail})"
    results.append((ok, msg))
    print(msg)

print()
print("=" * 52)
print("  배포 준비 체크리스트")
print("=" * 52)

# 1. 필수 파일
for fn in ["app.py", "requirements.txt", "packages.txt", ".gitignore"]:
    check(fn, (ROOT / fn).exists())

# 2. .gitignore 내용 검사
gi = ROOT / ".gitignore"
if gi.exists():
    gi_text = gi.read_text(encoding="utf-8")
    check(".gitignore: output/ 제외", "output/" in gi_text)
    check(".gitignore: __pycache__/ 제외", "__pycache__/" in gi_text)
    check(".gitignore: config.json 제외", "config.json" in gi_text)

# 3. packages.txt 내용
pk = ROOT / "packages.txt"
if pk.exists():
    pk_text = pk.read_text(encoding="utf-8")
    check("packages.txt: ffmpeg 포함", "ffmpeg" in pk_text)
    check("packages.txt: fonts-nanum 포함", "fonts-nanum" in pk_text)

# 4. requirements.txt 위험 패키지 검사
rq = ROOT / "requirements.txt"
if rq.exists():
    rq_text = rq.read_text(encoding="utf-8")
    danger = ["torch==", "torchvision", "torchaudio", "edge-tts", "gtts", "pandas"]
    for d in danger:
        if d in rq_text.lower():
            check(f"requirements.txt: {d} 없음", False, "클라우드 충돌 위험")
        # else: silent pass

# 5. streamlit 실행 가능
try:
    r = subprocess.run(
        [sys.executable, "-m", "streamlit", "--version"],
        capture_output=True, text=True, timeout=10,
    )
    ok = r.returncode == 0
    check("streamlit 실행 가능", ok, r.stdout.strip()[:40] if ok else r.stderr[:40])
except Exception as e:
    check("streamlit 실행 가능", False, str(e)[:40])

# 6. ffmpeg
ffmpeg_ok = subprocess.run(
    ["ffmpeg", "-version"], capture_output=True
).returncode == 0
check("ffmpeg 실행 가능 (로컬)", ffmpeg_ok,
      "클라우드에서는 packages.txt 로 설치됨")

# 7. Whisper
try:
    import whisper  # noqa
    check("openai-whisper import", True)
except ImportError:
    check("openai-whisper import", False, "pip install openai-whisper")

# 8. Pillow
try:
    from PIL import Image  # noqa
    check("Pillow import", True)
except ImportError:
    check("Pillow import", False, "pip install Pillow")

# 9. app.py 문법
try:
    import ast
    ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
    check("app.py 문법 OK", True)
except SyntaxError as e:
    check("app.py 문법 OK", False, f"line {e.lineno}: {e.msg}")

# 10. 로컬 .git 확인
git_ok = (ROOT / ".git").exists()
print(f"  {'✅' if git_ok else '⚠️ '} .git 저장소 {'초기화됨' if git_ok else '없음 — git_push.bat 실행 필요'}")

# ── 최종 결과
print()
print("=" * 52)
fails = [r for r in results if not r[0]]
if not fails:
    print("  🎉 모든 체크 통과! 배포 준비 완료.")
else:
    print(f"  ⚠️  {len(fails)}개 항목 수정 필요:")
    for _, msg in fails:
        print(f"     {msg.strip()}")
print("=" * 52)
print()
