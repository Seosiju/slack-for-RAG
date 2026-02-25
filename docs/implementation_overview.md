# Slack RAG 챗봇 — 구현 분석 문서

> 작성일: 2025-02-25 (v2 반영)  
> 대상 디렉토리: `/Users/snu.sim/git/job/slack`

---

## 1. 프로젝트 개요

PDF 운영보고서를 벡터 인덱스로 변환하고, Slack에서 `@gpt`를 멘션하면 **질문 유형을 자동 분류(라우팅)**한 뒤, RAG 또는 일반 LLM으로 답변하는 챗봇입니다.

| 핵심 기술 | 역할 |
|---|---|
| **LangChain (LCEL)** | RAG 파이프라인 오케스트레이션 |
| **slack-bolt + Socket Mode** | 서버 없이 로컬에서 Slack 이벤트 수신 |
| **PyMuPDF** | PDF → 텍스트 추출 |
| **FAISS** | 로컬 벡터 유사도 검색 |
| **OpenAI API** | 임베딩(`text-embedding-3-small`) + LLM(`gpt-4o-mini`, `gpt-4o`) |

---

## 2. 디렉토리 구조

```
slack/
├── .env                  # 환경변수 (Slack 토큰, OpenAI API 키)
├── .gitignore            # .env, index/, logs/ 등 추적 제외
├── requirements.txt      # Python 의존성 10개
├── app.py                # [진입점] Slack 봇 + 명령어 처리
├── rag.py                # [호환용] core.rag 를 re-export
├── core/                 # 핵심 모듈 패키지
│   ├── __init__.py
│   ├── rag.py            # RAG 엔진 (라우팅 + 검색 + 답변)
│   ├── router.py         # 질문 분류 (document/meta/general)
│   ├── models.py         # LLM 모델 레지스트리
│   └── memory.py         # 멀티턴 대화 히스토리 + Query Rewriting
├── data/                 # PDF 원본 4건
│   ├── 코칭스터디 16기 운영보고서(랩업).pdf
│   ├── 코칭스터디 17기 운영보고서.pdf
│   ├── 연세대 DX코딩캠프 2024 여름방학 운영보고서.pdf
│   └── 연세대 DX코딩캠프 2025 겨울방학 운영보고서.pdf
├── index/                # [자동생성] FAISS 벡터 인덱스 캐시
├── logs/                 # [자동생성] 로그 + traces.jsonl
├── test/                 # 테스트 도구
│   ├── api_test.py       # OpenAI API 연결 확인
│   └── qa_test.py        # RAG 대화형 테스트 (터미널)
└── docs/                 # 문서
    ├── implementation_overview.md  ← 이 문서
    ├── changelog.md               ← 변경 이력
    └── railway_deploy_guide.md    ← 배포 가이드
```

---

## 3. 핵심 모듈 분석

### 3.1 `app.py` — Slack 봇 메인 (213줄)

**역할:** Slack 이벤트를 수신하고, 명령어 처리 또는 RAG 엔진을 호출합니다.

| 구간 | 내용 |
|---|---|
| 환경 설정 | `dotenv` 로드, 로깅 (터미널 + 파일 RotatingFileHandler) |
| 초기화 | `App(token=SLACK_BOT_TOKEN)` → `RAG()` 인스턴스 |
| `handle_command()` | `/model`, `/help` 슬래시 명령어 처리 |
| `handle_mention()` | `@app.event("app_mention")`. 멘션 질문 추출 → 명령어 확인 → 스레드 히스토리 수집 → `rag.ask_with_trace()` → "검색 중" 메시지를 답변으로 교체 |
| `handle_dm()` | `@app.event("message")`. DM 채널 필터링 → RAG 답변 |
| 실행 | `SocketModeHandler.start()` |

---

### 3.2 `core/rag.py` — RAG 엔진 (336줄)

**역할:** 질문 라우팅 → 경로별 처리 → 답변 생성의 전체 파이프라인 통합.

#### 설정값

| 상수 | 값 | 설명 |
|---|---|---|
| `CHUNK_SIZE` | 500 | 텍스트 청크 크기 (자) |
| `CHUNK_OVERLAP` | 100 | 청크 간 겹침 |
| `TOP_K` | 5 | 유사도 검색 결과 수 |

#### `ask_with_trace()` 파이프라인

```
STEP 0-1: Query Rewriting (대화 히스토리가 있을 때만)
  → 후속 질문을 독립적 질문으로 재작성

STEP 0-2: 라우팅
  → LLM 분류기를 통해 document / meta / general 분기

[meta 경로]     → 시스템 정보 직접 응답 (LLM 비사용, 즉시 반환)
[general 경로]  → LLM에 직접 질문 (벡터 검색 생략)
[document 경로] → 아래 RAG 파이프라인 실행

STEP 1: FAISS 벡터 검색 (재작성된 질문으로 Top-5)
STEP 2: 컨텍스트 조합
STEP 3: 프롬프트 생성 (시스템 + 히스토리 + 컨텍스트 + 질문)
STEP 4: LLM 호출 → 답변 반환
```

---

### 3.3 `core/router.py` — 질문 분류기 (72줄)

- LLM에 질문을 보내 `document`, `meta`, `general` 중 하나로 분류
- 분류 실패 시 안전하게 `document`로 폴백
- `get_meta_response()`: PDF 목록, 벡터 수 등 시스템 정보를 직접 응답

---

### 3.4 `core/models.py` — 모델 레지스트리 (73줄)

- `.env`의 API Key 존재 여부에 따라 사용 가능 모델을 동적으로 등록
- `get_llm(model_name)`: 이름으로 LLM 인스턴스 반환
- `list_models()`: 사용 가능 모델 목록
- `get_embeddings()`: 임베딩 모델 인스턴스
- Google Gemini, Anthropic Claude 확장 주석 포함

---

### 3.5 `core/memory.py` — 멀티턴 메모리 (124줄)

- `get_thread_history()`: Slack API로 스레드 이전 메시지 수집 (최대 10턴)
- `rewrite_query()`: 대화 맥락을 반영하여 후속 질문을 독립적 질문으로 재작성
- `format_history()`: 히스토리를 "사용자: ... / 봇: ..." 텍스트로 변환

---

## 4. 데이터 흐름

```
사용자 (@gpt 질문)
    │
    ▼
app.py — 이벤트 수신 + 명령어 확인
    │
    ├─ 명령어이면 → 즉시 응답
    │
    ├─ 질문이면 →
    │   ├─ 스레드 히스토리 수집 (memory.py)
    │   └─ rag.ask_with_trace() 호출
    │       │
    │       ├─ Query Rewriting (memory.py)
    │       ├─ 라우팅 분류 (router.py)
    │       │
    │       ├─ [meta]     → 시스템 정보 응답
    │       ├─ [general]  → LLM 직접 답변
    │       └─ [document] → FAISS 검색 → LLM 답변
    │
    └─ Slack 메시지 교체 (답변 전송)
```

---

## 5. 인덱스 캐시 전략

1. **최초 실행**: PDF → 텍스트 추출 → 500자 청크 → OpenAI 임베딩 → FAISS 인덱스 → `index/` 저장
2. **재실행**: `index/index.faiss` 수정시간 vs PDF 최신 수정시간 비교
3. **수동 재빌드**: `rm -rf index/` 후 재실행

---

## 6. 의존성

| 패키지 | 최소 버전 | 용도 |
|---|---|---|
| `slack-bolt` | 1.18.0 | Slack 이벤트 프레임워크 |
| `slack-sdk` | 3.27.0 | Slack API 클라이언트 |
| `langchain` | 0.3.0 | RAG 코어 |
| `langchain-openai` | 0.3.0 | OpenAI LLM/Embedding |
| `langchain-community` | 0.3.0 | FAISS, PyMuPDF 로더 |
| `langchain-text-splitters` | 0.3.0 | 청크 분할 |
| `faiss-cpu` | 1.8.0 | 벡터 검색 |
| `pymupdf` | 1.24.0 | PDF 추출 |
| `python-dotenv` | 1.0.0 | `.env` 로드 |
| `numpy` | 1.26.0 | FAISS 의존 |

---

## 7. 환경변수

| 변수명 | 용도 |
|---|---|
| `KMP_DUPLICATE_LIB_OK` | FAISS + Anaconda OpenMP 충돌 방지 |
| `SLACK_BOT_TOKEN` | `xoxb-` Bot User OAuth Token |
| `SLACK_APP_TOKEN` | `xapp-` App Level Token (Socket Mode) |
| `OPENAI_API_KEY` | OpenAI API 인증 |
