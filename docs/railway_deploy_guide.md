# Railway 배포 가이드

> Slack RAG 챗봇을 Railway에 올려 24시간 운영하기

---

## 사전 준비

- [GitHub](https://github.com) 계정
- [Railway](https://railway.app) 계정 (GitHub 연동 가입 추천)
- 프로젝트 코드가 GitHub 저장소에 push 되어 있어야 함

> ⚠️ `.env` 파일은 `.gitignore`에 포함되어 GitHub에 올라가지 않습니다.  
> 환경변수는 Railway 대시보드에서 별도로 설정합니다.

---

## STEP 1. 배포에 필요한 파일 추가

### 1-1. `Procfile` 생성

프로젝트 루트(`slack/`)에 `Procfile`이라는 파일을 만들고 아래 한 줄만 작성합니다:

```
worker: python app.py
```

> `web`이 아닌 `worker`를 사용합니다. Socket Mode는 HTTP 요청을 받는 게 아니라  
> Slack 서버에 WebSocket 연결을 유지하는 방식이므로, 웹 서버가 필요 없습니다.

### 1-2. `runtime.txt` 생성 (선택)

Railway가 사용할 Python 버전을 지정합니다:

```
python-3.11.11
```

> 생략해도 Railway가 기본 버전을 사용하므로 필수는 아닙니다.

### 1-3. `.gitignore` 확인

아래 항목이 포함되어 있어야 합니다 (현재 이미 설정됨):

```
.env
index/
logs/
__pycache__/
*.pyc
```

### 1-4. data/ 폴더의 PDF를 Git에 포함

PDF 파일이 `.gitignore`에 의해 제외되지 않았는지 확인합니다.  
Railway 서버에서 PDF가 있어야 인덱스를 빌드할 수 있습니다.

```bash
git add data/
git commit -m "data: PDF 파일 추가"
git push
```

> PDF 용량이 너무 크다면 Git LFS를 사용하거나,  
> S3 같은 외부 스토리지에서 다운로드하는 방식도 가능합니다.

---

## STEP 2. Railway 프로젝트 생성

1. [railway.app](https://railway.app) 에 로그인
2. **New Project** 클릭
3. **Deploy from GitHub repo** 선택
4. GitHub 저장소 연결 → 이 프로젝트의 저장소 선택
5. Railway가 자동으로 빌드를 시작하지만, 환경변수가 없으므로 **실패할 것입니다** (정상)

---

## STEP 3. 환경변수 설정

Railway 대시보드에서:

1. 배포된 서비스 클릭
2. **Variables** 탭으로 이동
3. 아래 4개 환경변수를 추가:

| 변수명 | 값 | 설명 |
|---|---|---|
| `KMP_DUPLICATE_LIB_OK` | `TRUE` | FAISS OpenMP 충돌 방지 |
| `SLACK_BOT_TOKEN` | `xoxb-...` | Slack Bot OAuth Token |
| `SLACK_APP_TOKEN` | `xapp-...` | Slack App Level Token |
| `OPENAI_API_KEY` | `sk-proj-...` | OpenAI API 키 |

> **Raw Editor** 버튼을 누르면 `.env` 파일 내용을 통째로 붙여넣을 수 있어 편합니다.

환경변수를 저장하면 Railway가 자동으로 재배포합니다.

---

## STEP 4. 배포 확인

1. Railway 대시보드에서 **Deployments** 탭 클릭
2. 최신 배포의 **View Logs** 클릭
3. 아래와 같은 로그가 나오면 성공:

```
🔨 인덱스를 새로 빌드합니다...
  📄 로드 완료: 코칭스터디 16기 운영보고서(랩업).pdf (...)
  📄 로드 완료: 코칭스터디 17기 운영보고서.pdf (...)
  ...
  ✅ FAISS 인덱스 생성 완료 (벡터 XXX개)
==================================================
  Slack RAG 챗봇이 시작됩니다!
==================================================
```

4. Slack에서 `@gpt 테스트!` 멘션 → 답변이 오면 배포 완료 🎉

---

## STEP 5. 주의사항

### 인덱스 캐시는 매 배포 시 초기화됨

Railway는 배포할 때마다 새로운 컨테이너를 생성합니다.  
따라서 `index/` 폴더에 저장된 FAISS 캐시가 매번 사라지고, **배포 시마다 인덱스를 새로 빌드**합니다.

- PDF 4개 분량이면 빌드에 **10~30초** 정도 걸리므로 큰 문제는 아닙니다.
- 만약 PDF가 수십 개로 늘어나 빌드 시간이 길어진다면, 인덱스를 Git에 포함하거나 볼륨(Volume)을 사용하는 방식을 고려할 수 있습니다.

### 로그 확인

- `logs/` 폴더도 배포 시 초기화됩니다.
- 실시간 로그는 Railway 대시보드의 **Logs** 탭에서 확인 가능합니다.
- 영구적인 로그 저장이 필요하면 Railway Volume을 연결하거나, 외부 로깅 서비스를 사용합니다.

---

## 이후 업데이트 방법

코드를 수정하거나 PDF를 추가한 경우:

```bash
git add .
git commit -m "변경사항 설명"
git push
```

→ Railway가 자동으로 감지하여 **재빌드 + 재배포**합니다.  
→ 배포 중에도 이전 버전이 계속 동작하므로 **서비스 중단 없이** 교체됩니다.

---

## 요금 참고

| 항목 | 내용 |
|---|---|
| 플랜 | Hobby ($5/월 기본료, 사용량 포함) |
| 예상 실사용 비용 | 이 봇 규모에서 **월 $1~3 수준** |
| 과금 기준 | vCPU 사용시간 + 메모리 점유량 |
| Socket Mode 특성 | 대기 중에는 CPU를 거의 안 쓰므로 매우 저렴 |

---

## 트러블슈팅

### 배포 후 Slack에서 응답 없음
1. Railway Logs에서 에러 확인
2. 환경변수 4개가 모두 정확히 입력되었는지 확인
3. Slack 앱의 **Socket Mode**가 Enable 상태인지 확인

### `ModuleNotFoundError` 발생
- `requirements.txt`가 프로젝트 루트에 있는지 확인
- Railway는 이 파일을 자동으로 감지하여 `pip install`을 실행합니다

### 메모리 부족 (OOMKilled)
- PDF가 너무 많아 FAISS 인덱스가 메모리를 초과한 경우
- Railway 대시보드에서 메모리 한도를 늘리거나, PDF를 분리 운영

---

## 전체 파일 구조 (배포 후)

```
slack/
├── .gitignore
├── Procfile              ← [신규] Railway 실행 명령
├── runtime.txt           ← [신규, 선택] Python 버전 지정
├── requirements.txt
├── app.py
├── rag.py
├── data/
│   ├── 코칭스터디 16기 운영보고서(랩업).pdf
│   ├── 코칭스터디 17기 운영보고서.pdf
│   ├── 연세대 DX코딩캠프 2024 여름방학 운영보고서.pdf
│   └── 연세대 DX코딩캠프 2025 겨울방학 운영보고서.pdf
└── docs/
    ├── implementation_overview.md
    └── railway_deploy_guide.md   ← 이 문서
```
