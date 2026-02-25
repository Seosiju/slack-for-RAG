# 📚 Slack RAG 챗봇

PDF 운영보고서를 기반으로, Slack에서 `@gpt`를 멘션하면 문서 내용을 검색하여 답변하는 AI 챗봇입니다.

**LangChain** 기반으로 구축되어 AI 제공자(OpenAI, Google, Anthropic 등)를 쉽게 교체할 수 있습니다.

## 아키텍처

```
사용자 (@gpt 질문)
    │
    ▼
Slack Bot (Socket Mode)
    │
    ├─ 초기화 시 ────────────────────────────────────────┐
    │   PDF 파일 → PyMuPDFLoader → 텍스트 추출           │
    │   → RecursiveCharacterTextSplitter (500자 청크)     │
    │   → Embeddings 모델 → FAISS 벡터 인덱스 저장       │
    │                                                     │
    ├─ 질문 수신 시 (LCEL 체인) ─────────────────────────┐
    │   질문 → Retriever (FAISS 유사도 검색 Top-5)       │
    │   → Prompt Template (시스템 프롬프트 + 컨텍스트)   │
    │   → LLM (ChatModel) → 답변 → Slack 스레드 전송    │
    └─────────────────────────────────────────────────────┘
```

## 프로젝트 구조

```
slack/
├── .env                # 환경변수 (토큰, API 키) ← 직접 입력 필요
├── requirements.txt    # Python 패키지 목록
├── app.py              # Slack 봇 메인 (진입점)
├── rag.py              # RAG 엔진 (LangChain LCEL 체인)
├── data/               # PDF 원본 파일
│   ├── 코칭스터디 16기 운영보고서(랩업).pdf
│   ├── 코칭스터디 17기 운영보고서.pdf
│   ├── 연세대 DX코딩캠프 2024 여름방학 운영보고서.pdf
│   └── 연세대 DX코딩캠프 2025 겨울방학 운영보고서.pdf
└── index/              # [자동생성] FAISS 벡터 인덱스 캐시
```

## 사전 준비

### 1. Slack 앱 생성 및 설정

1. [api.slack.com/apps](https://api.slack.com/apps) 에서 **Create New App** → **From scratch**
2. 앱 이름을 `gpt` (혹은 원하는 이름)로 설정
3. **Socket Mode** 활성화:
   - 좌측 메뉴 → Settings → **Socket Mode** → Enable
   - App-Level Token 생성 (Scope: `connections:write`) → `xapp-` 토큰 복사
4. **Bot Token Scopes** 추가:
   - 좌측 메뉴 → Features → **OAuth & Permissions** → Scopes에서 아래 추가:
     - `app_mentions:read`
     - `chat:write`
     - `im:history`
     - `im:read`
     - `im:write`
5. **Event Subscriptions** 활성화:
   - 좌측 메뉴 → Features → **Event Subscriptions** → Enable
   - Subscribe to bot events에서 아래 추가:
     - `app_mention`
     - `message.im`
6. 앱을 워크스페이스에 **Install** → `xoxb-` 토큰 복사

### 2. `.env` 파일 설정

```env
# Slack
SLACK_BOT_TOKEN=xoxb-your-token-here
SLACK_APP_TOKEN=xapp-your-token-here

# AI API (사용할 제공자에 맞게 설정)
OPENAI_API_KEY=sk-your-key-here
# GOOGLE_API_KEY=your-key-here        ← Google Gemini 사용 시
# ANTHROPIC_API_KEY=your-key-here     ← Anthropic Claude 사용 시
```

### 3. 패키지 설치

```bash
cd slack
pip install -r requirements.txt
```

## 실행 방법

```bash
python app.py
```

실행하면 다음과 같은 메시지가 나타납니다:

```
🔨 인덱스를 새로 빌드합니다...       ← 최초 1회만 (이후 캐시 사용)
  📄 로드 완료: 코칭스터디 16기 ...
  ...
  ✅ FAISS 인덱스 생성 완료
==================================================
🤖 Slack RAG 챗봇이 시작됩니다!
   Slack에서 @gpt 를 멘션하여 질문하세요.
   종료: Ctrl+C
==================================================
```

## 사용법

### 채널에서 멘션

```
@gpt 코칭스터디 17기 수료율은?
```

→ 봇이 **스레드**로 PDF 내용 기반의 답변을 생성합니다.

### DM으로 직접 질문

봇에게 DM을 보내면 멘션 없이도 바로 답변합니다.

## AI 제공자 교체 방법

`rag.py` 상단의 LLM/Embedding 설정 부분만 수정하면 됩니다.

### OpenAI → Google Gemini 로 교체

```bash
pip install langchain-google-genai
```

```python
# rag.py 상단 수정
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings

llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash")
embeddings = GoogleGenerativeAIEmbeddings(model="models/text-embedding-004")
```

`.env`에 `GOOGLE_API_KEY=your-key` 추가

### OpenAI → Anthropic Claude 로 교체

```bash
pip install langchain-anthropic
```

```python
# rag.py 상단 수정
from langchain_anthropic import ChatAnthropic

llm = ChatAnthropic(model="claude-sonnet-4-20250514")
# 임베딩은 OpenAI 또는 Google 것을 사용 (Anthropic은 임베딩 미제공)
```

`.env`에 `ANTHROPIC_API_KEY=your-key` 추가

> **주의:** AI 제공자를 교체한 뒤에는 임베딩 모델이 달라지므로 인덱스를 재빌드해야 합니다.
> ```bash
> rm -rf index/
> python app.py
> ```

## PDF 문서 업데이트

`data/` 폴더에 새 PDF를 추가하거나 기존 PDF를 교체한 경우:

```bash
rm -rf index/
python app.py
```

---

## ❗ 트러블슈팅 매뉴얼

### 문제 1: 토큰 오류 — `BoltError: token is not set`

**원인:** `.env` 파일의 토큰이 비어 있거나, 변수명이 틀렸습니다.

**해결:**
1. `.env` 파일에서 변수명이 정확히 `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`인지 확인
2. 토큰 값에 따옴표(`"`, `'`)를 넣지 않았는지 확인
3. `.env` 파일이 `app.py`와 같은 폴더(`slack/`)에 있는지 확인

---

### 문제 2: PDF 없음 — `FileNotFoundError`

**원인:** `data/` 폴더가 없거나 PDF 파일이 들어있지 않습니다.

**해결:**
1. `slack/data/` 폴더가 존재하는지 확인
2. 해당 폴더에 `.pdf` 파일이 있는지 확인

---

### 문제 3: Slack에서 봇이 아무 반응이 없음

**원인 후보:**
- `python app.py`가 실행 중이지 않음
- Event Subscriptions에서 `app_mention` 미등록
- Socket Mode 미활성화

**해결:**
1. 터미널에서 `python app.py`가 돌아가고 있는지 확인
2. [api.slack.com/apps](https://api.slack.com/apps) → Event Subscriptions → `app_mention` 등록 확인
3. Socket Mode **Enable** 상태 확인

---

### 문제 4: OpenAI API 오류 — `AuthenticationError` / `RateLimitError`

**해결:**
1. [platform.openai.com/api-keys](https://platform.openai.com/api-keys) 키 유효성 확인
2. [platform.openai.com/usage](https://platform.openai.com/usage) 잔액 확인
3. 잔액 부족 시 → 크레딧 충전 또는 **Google Gemini로 교체** (위 가이드 참고)

---

### 문제 5: 답변 품질 저조 — "문서에서 확인할 수 없습니다"가 자주 나옴

**해결:**
1. `rag.py`에서 `CHUNK_SIZE`를 `800`, `CHUNK_OVERLAP`을 `200`으로 늘려보세요
2. `TOP_K`를 `7`이나 `10`으로 올려보세요
3. 인덱스 재빌드: `rm -rf index/ && python app.py`

---

### 문제 6: 패키지 미설치 — `ModuleNotFoundError`

**해결:**
```bash
pip install -r requirements.txt
```

---

## 기술 스택

| 기술 | 용도 |
|---|---|
| Python 3.10+ | 런타임 |
| LangChain | RAG 파이프라인 프레임워크 (LCEL 체인) |
| slack-bolt | Slack 이벤트 수신 및 메시지 응답 |
| PyMuPDF | PDF → 텍스트 추출 |
| FAISS | 벡터 유사도 검색 (로컬 벡터DB) |
| OpenAI API | 임베딩 + LLM (교체 가능) |
| Socket Mode | 서버 없이 로컬에서 Slack 연결 |
