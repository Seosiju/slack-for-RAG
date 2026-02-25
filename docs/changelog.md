# 변경 이력 (Changelog)

> Slack RAG 챗봇 개발 과정에서의 주요 수정 내역을 정리합니다.

---

## v2 — 아키텍처 리팩토링 + 기능 확장

### 구조 변경: `core/` 패키지 도입

기존에 `app.py` + `rag.py` 2개 파일에 모든 로직이 들어있던 구조를 **역할별 모듈로 분리**하였습니다.

| 변경 전 | 변경 후 | 역할 |
|---|---|---|
| `rag.py` (342줄, 모든 로직 포함) | `core/rag.py` (336줄, 오케스트레이션) | RAG 파이프라인 통합 관리 |
| _(없음)_ | `core/router.py` (72줄) | 질문 유형 분류 (document/meta/general) |
| _(없음)_ | `core/models.py` (73줄) | LLM 모델 레지스트리 & 동적 교체 |
| _(없음)_ | `core/memory.py` (124줄) | 멀티턴 대화 히스토리 & Query Rewriting |
| `app.py` (160줄) | `app.py` (213줄) | Slack 이벤트 핸들러 + 명령어 처리 |
| `rag.py` _(원본)_ | `rag.py` (6줄, re-export만) | 하위 호환성 유지 |

---

### 추가된 기능

#### 1. 질문 라우팅 (Router)

질문을 LLM으로 분류하여 3가지 경로로 분기합니다:

| 경로 | 처리 방식 | 예시 |
|---|---|---|
| `document` | 벡터 검색 → RAG 파이프라인 | "코칭스터디 17기 수료율은?" |
| `meta` | 시스템 정보 직접 응답 (LLM 미사용) | "어떤 문서가 로드되어 있어?" |
| `general` | LLM 직접 답변 (검색 없이) | "1+1은?", "안녕하세요" |

**효과:** 일반 대화에 불필요한 문서 검색을 생략하여 응답 속도 향상 & 토큰 절약

#### 2. 다중 모델 지원 (Model Registry)

- `core/models.py`에서 사용 가능한 LLM 모델을 레지스트리로 관리
- `.env`에 해당 API Key가 있는 경우에만 모델 등록 (안전한 확장)
- **런타임 모델 교체:** `rag.set_model("gpt-4o")` 호출로 즉시 전환 가능
- 현재 등록된 모델: `gpt-4o-mini` (기본), `gpt-4o`
- Google Gemini, Anthropic Claude는 주석으로 확장 가이드 포함

#### 3. 슬래시 명령어

`app.py`에 명령어 시스템이 추가됨:

| 명령어 | 기능 |
|---|---|
| `@gpt /model` | 사용 가능한 모델 목록과 현재 모델 표시 |
| `@gpt /model gpt-4o` | 모델을 gpt-4o로 변경 |
| `@gpt /help` | 사용법 안내 |

#### 4. 멀티턴 대화 메모리 (Memory)

- **스레드 히스토리 수집:** Slack API(`conversations.replies`)로 스레드 내 이전 대화를 수집
- **Query Rewriting:** 대화 맥락을 반영하여 후속 질문을 독립적인 질문으로 재작성
  - 예: (이전: "수료율은?") → "멀티턴 구현된거 아니었어?" → "이 시스템에 멀티턴 대화 기능이 구현되어 있는가?"
- 최대 10턴까지의 이전 대화를 프롬프트에 포함
- 히스토리가 없으면 재작성 단계를 스킵하여 불필요한 LLM 호출 방지

> ⚠️ 현재 Slack Bot의 OAuth scope에 `channels:history`가 누락되어 스레드 히스토리 수집이 실패하고 있음 (로그에 `missing_scope` 경고 확인). Slack 앱 설정에서 해당 scope를 추가해야 멀티턴이 정상 작동합니다.

---

### 변경된 동작

#### 프롬프트 분리

| 경로 | 시스템 프롬프트 |
|---|---|
| `document` (RAG) | "AI 어시스턴트. 참고 문서를 근거로 답변. 출처 언급. 없으면 확인 불가라고 답변" |
| `general` | "도움이 되는 AI 어시스턴트. 친절하고 정확하게 답변" |

- 초기 버전에서는 모든 질문에 "교육 프로그램 운영보고서 기반 어시스턴트"라는 단일 프롬프트를 사용했으나, 라우팅 도입으로 경로별 최적화된 프롬프트 사용

#### 파이프라인 타이밍 확장

```
초기: 1_retrieval → 2_llm_generation → total
현재: 0_rewriting → 0_routing → 1_retrieval → 2_llm_generation → total
```

#### 트레이스 로그 확장

`logs/traces.jsonl`에 기록되는 항목이 확장됨:
- `rewritten_query` (재작성된 질문)
- `route` (라우팅 결과)
- `chat_history_turns` (대화 턴 수)

---

## v1 — 초기 구현

### 기본 구조

- `app.py`: Slack 이벤트 수신 (멘션 + DM), 로깅(터미널 + 파일)
- `rag.py`: RAG 전체 파이프라인 (PDF 로드 → 청킹 → 임베딩 → FAISS 인덱스 → LLM 답변)
- Socket Mode 사용 (서버 없이 로컬 실행)
- LangChain LCEL 체인 기반

### 핵심 기능

- PyMuPDF로 PDF 텍스트 추출
- RecursiveCharacterTextSplitter (500자, 100자 겹침)
- FAISS 벡터 유사도 검색 (Top-5)
- 자동 캐시: `index/`에 FAISS 인덱스 저장, PDF 수정 시 자동 재빌드
- RotatingFileHandler (5MB × 3개 로그 파일)
- JSONL 트레이스 기록 (`logs/traces.jsonl`)
- "검색 중" 로딩 메시지 → 답변 교체 패턴

### 데이터

- 코칭스터디 16기 운영보고서 (랩업)
- 코칭스터디 17기 운영보고서
- 연세대 DX코딩캠프 2024 여름방학 운영보고서
- 연세대 DX코딩캠프 2025 겨울방학 운영보고서

### 테스트 도구

- `test/api_test.py`: OpenAI API 연결 테스트 (ChatGPT + 임베딩)
- `test/qa_test.py`: RAG 파이프라인 대화형 테스트 (Slack 없이 터미널 디버깅)

---

## 알려진 이슈

| 이슈 | 상태 | 설명 |
|---|---|---|
| `channels:history` scope 누락 | 🔴 미해결 | 멀티턴 대화 시 스레드 히스토리 수집 실패. Slack 앱 설정에서 scope 추가 필요 |
| 사용자별 모델 설정 휘발성 | ⚠️ 제한사항 | `user_models` dict가 메모리에만 저장되어 앱 재시작 시 초기화됨 |
