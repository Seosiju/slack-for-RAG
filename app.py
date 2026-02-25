"""
Slack RAG 챗봇 — 메인 앱
Slack에서 @gpt 를 멘션하면 질문 유형에 따라 라우팅하여 답변합니다.
"""

import os
import re
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from dotenv import load_dotenv

from core.rag import RAG
from core.models import list_models
from core.memory import get_thread_history

# ── 환경 설정 ─────────────────────────────────────────
load_dotenv()

# ── 로깅 설정 (Layer 1: 터미널 + 파일 동시 기록) ──────
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

log_format = "%(asctime)s [%(levelname)s] %(message)s"
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(logging.Formatter(log_format))

file_handler = RotatingFileHandler(
    LOG_DIR / "app.log",
    maxBytes=5 * 1024 * 1024,
    backupCount=3,
    encoding="utf-8",
)
file_handler.setFormatter(logging.Formatter(log_format))

logging.basicConfig(level=logging.INFO, handlers=[stream_handler, file_handler])
logger = logging.getLogger(__name__)

# Slack 앱 초기화
app = App(token=os.environ["SLACK_BOT_TOKEN"])

# RAG 엔진 초기화
logger.info("RAG 엔진 초기화 중...")
rag = RAG()
logger.info("RAG 엔진 준비 완료!")

# 사용자별 모델 설정 저장 (user_id → model_name)
user_models: dict[str, str] = {}


# ── 명령어 처리 ───────────────────────────────────────
def handle_command(question: str, user: str) -> str | None:
    """
    /model 등 슬래시 명령어를 처리합니다.
    명령어가 아니면 None을 반환합니다.
    """
    if not question.startswith("/"):
        return None

    parts = question.split()
    cmd = parts[0].lower()

    if cmd == "/model":
        if len(parts) == 1 or parts[1].lower() == "list":
            # 모델 목록 표시
            available = list_models()
            current = user_models.get(user, "gpt-4o-mini")
            lines = [f"📋 사용 가능한 모델 (현재: *{current}*)"]
            for name in available:
                marker = " ✅" if name == current else ""
                lines.append(f"  • `{name}`{marker}")
            lines.append("\n사용법: `@gpt /model gpt-4o`")
            return "\n".join(lines)

        # 모델 변경
        model_name = parts[1].lower()
        available = list_models()
        if model_name not in available:
            return f"❌ '{model_name}' 모델을 찾을 수 없습니다.\n사용 가능: {', '.join(available)}"

        user_models[user] = model_name
        rag.set_model(model_name)
        return f"✅ 모델이 *{model_name}* 으로 변경되었습니다."

    if cmd == "/help":
        return (
            "📖 *사용법*\n"
            "  • `@gpt 질문` — 문서 기반 / 일반 질문 답변\n"
            "  • `@gpt /model` — 사용 가능한 모델 목록\n"
            "  • `@gpt /model gpt-4o` — 모델 변경\n"
            "  • `@gpt /help` — 도움말"
        )

    return None


# ── 이벤트 핸들러 ─────────────────────────────────────
@app.event("app_mention")
def handle_mention(event, say, client):
    """@gpt 멘션을 받으면 라우팅하여 답변합니다."""
    raw_text = event.get("text", "")
    user = event.get("user", "")
    channel = event.get("channel", "")
    thread_ts = event.get("thread_ts") or event.get("ts")

    # 멘션 태그 제거
    question = re.sub(r"<@[A-Z0-9]+>", "", raw_text).strip()

    if not question:
        say(
            text="안녕하세요! 궁금한 점을 질문해 주세요.\n"
                 "`@gpt /help` 로 사용법을 확인하세요.",
            thread_ts=thread_ts,
        )
        return

    logger.info(f"[질문 수신] user={user} | question={question}")

    # 명령어 처리
    cmd_response = handle_command(question, user)
    if cmd_response is not None:
        say(text=cmd_response, thread_ts=thread_ts)
        logger.info(f"[명령어 처리] cmd={question} | 응답 길이: {len(cmd_response)}자")
        return

    # "검색 중" 메시지
    loading_msg = client.chat_postMessage(
        channel=channel,
        text="문서를 검색 중입니다...",
        thread_ts=thread_ts,
    )

    try:
        # 스레드 히스토리 수집 (멀티턴)
        history = get_thread_history(client, channel, thread_ts)
        trace = rag.ask_with_trace(question, source="slack", chat_history=history)

        # 상세 로그
        if trace.get("rewritten_query"):
            logger.info(f"[Query Rewriting] '{question}' → '{trace['rewritten_query']}'")
        logger.info(f"[라우팅] route={trace['route']}")
        if trace["retrieved_chunks"]:
            logger.info(f"[검색 완료] 유사 청크 {len(trace['retrieved_chunks'])}개")
            for i, chunk in enumerate(trace["retrieved_chunks"], 1):
                logger.info(f"  [{i}] {chunk['source']} (p.{chunk['page']}) | 유사도: {chunk['score']}")
        logger.info(
            f"[답변 생성] "
            f"라우팅={trace['timing'].get('0_routing', '?')}s | "
            f"검색={trace['timing'].get('1_retrieval', '-')}s | "
            f"LLM={trace['timing'].get('2_llm_generation', '?')}s | "
            f"총={trace['timing'].get('total', '?')}s"
        )
        if "token_usage" in trace:
            usage = trace["token_usage"]
            logger.info(f"[토큰] 프롬프트={usage['prompt_tokens']} + 답변={usage['completion_tokens']} = 총 {usage['total_tokens']}")

        # "검색 중" → 실제 답변으로 교체
        client.chat_update(
            channel=channel,
            ts=loading_msg["ts"],
            text=trace["answer"],
        )
        logger.info(f"[슬랙 전송 완료] 답변 길이: {len(trace['answer'])}자")

    except Exception as e:
        logger.error(f"[답변 생성 실패] {e}", exc_info=True)
        client.chat_update(
            channel=channel,
            ts=loading_msg["ts"],
            text=f"답변 생성 중 오류가 발생했습니다.\n```{str(e)}```",
        )


@app.event("message")
def handle_dm(event, say):
    """DM으로 질문이 오면 답변합니다."""
    if event.get("bot_id") or event.get("subtype"):
        return
    if event.get("channel_type", "") != "im":
        return

    question = event.get("text", "").strip()
    if not question:
        return

    logger.info(f"[DM 질문 수신] question={question}")

    try:
        # DM은 스레드 없으므로 히스토리 없음
        trace = rag.ask_with_trace(question, source="dm")
        logger.info(f"[DM] route={trace['route']} | 총={trace['timing'].get('total', '?')}s")
        say(text=trace["answer"])
    except Exception as e:
        logger.error(f"[DM 답변 생성 실패] {e}", exc_info=True)
        say(text=f"답변 생성 중 오류가 발생했습니다.\n```{str(e)}```")


# ── 실행 ──────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 50)
    print("  Slack RAG 챗봇이 시작됩니다!")
    print("  Slack에서 @gpt 를 멘션하여 질문하세요.")
    print("  명령어: /model, /help")
    print("  종료: Ctrl+C")
    print(f"  로그 저장: {LOG_DIR}")
    print("=" * 50)

    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    handler.start()
