# 🎬 연예인 픽템 쇼츠 자막 공장

편집 완료 영상을 업로드하면 자막 자동 추출 → 대사 수정 → 상단/하단 바 합성 → `final_short.mp4` 완성까지 한 번에 처리하는 웹앱입니다.

---

## 🚀 웹 배포 방법 (초보자 기준 — 버튼 순서 그대로 따라하기)

### STEP 1 — GitHub 계정 만들기 (이미 있으면 건너뜀)

1. 브라우저에서 **https://github.com** 접속
2. 오른쪽 위 **Sign up** 클릭
3. 이메일 / 비밀번호 입력 후 계정 생성

---

### STEP 2 — GitHub 저장소 만들기

1. GitHub 로그인 상태에서 오른쪽 위 **+** 버튼 클릭
2. **New repository** 클릭
3. Repository name 에 **celeb-shorts-factory** 입력
4. **Private** 선택 (공개 안 해도 Streamlit Cloud 연동 가능)
5. 아래쪽 **Create repository** 초록 버튼 클릭
6. 만들어진 저장소 주소를 복사해 둠  
   예: `https://github.com/mingkee1009/celeb-shorts-factory`

---

### STEP 3 — 파일 GitHub에 올리기 (git_push.bat 더블클릭 한 번)

> Git 이 없으면 먼저 설치: https://git-scm.com/download/win  
> 설치 시 모든 옵션 기본값으로 Next → Install

1. 탐색기에서 프로젝트 폴더 열기  
   `C:\Users\이지연\OneDrive\Desktop\sunja_project\연예인픽템쇼츠공장`
2. **`git_push.bat`** 파일 더블클릭
3. 까만 창(CMD)이 열리면:
   - `Enter GitHub repo URL` 물어보면 → STEP 2에서 복사한 주소 붙여넣기 (Ctrl+V)  
     예: `https://github.com/mingkee1009/celeb-shorts-factory`
   - 이메일/이름 물어보면 → 아무 이메일/이름 입력
4. 브라우저 창이 뜨면 GitHub 로그인 → Allow 클릭
5. 창에 **DONE! Your code is now on GitHub.** 메시지가 나오면 완료

> 처음에 인증 팝업이 뜰 수 있습니다. GitHub 비밀번호 또는 **Sign in with your browser** 클릭해서 인증하세요.

---

### STEP 4 — Streamlit Cloud 배포

1. 브라우저에서 **https://share.streamlit.io** 접속
2. **Continue with GitHub** 클릭 → GitHub 계정으로 로그인
3. 오른쪽 위 **Create app** 클릭
4. **Deploy a public app from GitHub** 선택
5. 아래와 같이 입력:

   | 항목 | 입력값 |
   |------|--------|
   | Repository | `mingkee1009/celeb-shorts-factory` |
   | Branch | `main` |
   | Main file path | `app.py` |
   | App URL (선택) | 원하는 이름 (영어) |

6. 오른쪽 아래 **Deploy!** 파란 버튼 클릭
7. 빌드 로그가 흘러나옴 — **약 5~15분** 기다림  
   (torch + ffmpeg 설치 때문에 처음에만 오래 걸림)
8. 화면이 앱으로 바뀌면 배포 완료!

---

### STEP 5 — 즐겨찾기 등록

배포 완료 후 주소창에 이런 URL이 표시됩니다:
```
https://mingkee1009-celeb-shorts-factory-app-XXXXXX.streamlit.app
```

- **PC**: Ctrl+D 눌러 즐겨찾기 저장
- **스마트폰**: Safari / Chrome 공유 버튼 → "홈 화면에 추가"

---

## ⚠️ 오류가 났을 때

| 상황 | 해결 방법 |
|------|----------|
| 빌드 중 `torch` 오류 | requirements.txt 에서 `torch` 줄 삭제 후 재push |
| `ffmpeg not found` | packages.txt 에 `ffmpeg` 있는지 확인 |
| 자막이 □□□ 로 깨짐 | packages.txt 에 `fonts-nanum` 있는지 확인 |
| 앱이 느리거나 멈춤 | 영상을 20초 이하로 줄여서 업로드 |
| 업로드한 파일이 사라짐 | 세션 만료 — 재업로드 후 다시 생성 |
| 배포 후 흰 화면 | Streamlit Cloud 로그 확인 (앱 오른쪽 위 ☰ → Manage app) |

---

## 🛠️ 배포 전 자동 체크 (선택)

프로젝트 폴더에서 아래 명령 실행:

```bash
python deploy_ready_check.py
python streamlit_app_check.py
```

모든 항목에 ✅ 가 표시되면 바로 배포 가능합니다.

---

## 📋 GitHub에 올리는 파일 목록

```
app.py                   ← 메인 앱
subtitle_extractor.py    ← Whisper 자막 추출
make_final_shorts.py     ← ffmpeg 영상 합성
find_original_video.py   ← 고급 기능 (원본 탐색)
search_related_videos.py ← 고급 기능 (후보 검색)
requirements.txt         ← Python 패키지
packages.txt             ← 시스템 패키지 (ffmpeg, 한글 폰트)
.gitignore               ← 제외 파일 목록
README.md                ← 이 파일
deploy_ready_check.py    ← 배포 전 체크 스크립트
streamlit_app_check.py   ← 앱 점검 스크립트
```

**올리지 않는 파일 (.gitignore 자동 처리)**
```
config.json              ← Windows 로컬 경로 포함
start.bat / stop.bat     ← Windows 전용
create_shortcut.ps1      ← Windows 전용
git_push.bat             ← 한 번만 쓰는 파일
output/ input/ uploads/  ← 런타임 생성 폴더
__pycache__/             ← Python 캐시
```

---

## 💡 앱 사용 흐름

```
① 편집 완료 영상 업로드 (mp4 / mov / webm / m4v)
② 연예인명 · 제품명 · 상단 후킹 문구 · 출처 입력
③ [자막 자동 추출] 클릭 → Whisper 변환 (30초~2분)
④ 대사 수정 (줄바꿈으로 자막 단위 구분)
⑤ 썸네일 문구 수정 → 실시간 미리보기 확인
⑥ [최종 영상 만들기] 클릭 → final_short.mp4 생성
⑦ 영상 + 썸네일 다운로드 버튼 클릭
```

> 원본 음성은 자동으로 유지됩니다. AI 음성은 사용하지 않습니다.
