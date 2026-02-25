"""
멀티턴 대화 메모리 (Memory)

슬랙 스레드의 이전 메시지를 수집하고,
대화 맥락을 반영하여 질문을 독립적으로 재작성(Query Rewriting)합니다.
"""

import re
import logging

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

logger = logging.getLogger(__name__)

MAX_TURNS = 10

# ── Query Rewriting 프롬프트 ──────────────────────────
REWRITE_PROMPT = ChatPromptTemplate.from_messages([
    ("system", (
        "You are a query rewriter. Given a conversation history and a follow-up question, "
        "rewrite the follow-up question as a standalone question in Korean.\n"
        "If the question is already standalone or there is no history, return it as-is.\n"
        "Do NOT answer the question. Only rewrite it.\n"
        "Output ONLY the rewritten question, nothing else."
    )),
    ("human",
     "## 대화 히스토리\n{history}\n\n"
     "## 후속 질문\n{question}\n\n"
     "## 독립적으로 재작성된 질문"),
])


def get_thread_history(client, channel: str, thread_ts: str, max_turns: int = MAX_TURNS) -> list[dict]:
    """
    Slack API로 스레드의 이전 메시지를 가져와
    [{"role": "user"|"assistant", "content": "..."}] 형태로 반환합니다.
    
    Args:
        client: Slack WebClient
        channel: 채널 ID
        thread_ts: 스레드 타임스탬프
        max_turns: 최대 턴 수 (기본 10)
    
    Returns:
        대화 히스토리 리스트 (최근 max_turns개 메시지)
    """
    try:
        result = client.conversations_replies(
            channel=channel,
            ts=thread_ts,
            limit=max_turns * 2 + 1,  # user+bot 쌍 + 여유
        )
        messages = result.get("messages", [])
    except Exception as e:
        logger.warning(f"[메모리] 스레드 히스토리 수집 실패: {e}")
        return []

    history = []
    for msg in messages:
        # 현재 메시지(가장 마지막)는 제외하고 이전 메시지만 수집
        text = msg.get("text", "").strip()
        if not text:
            continue

        # 봇 메시지인지 판별
        if msg.get("bot_id") or msg.get("subtype") == "bot_message":
            history.append({"role": "assistant", "content": text})
        else:
            # 멘션 태그 제거
            clean_text = re.sub(r"<@[A-Z0-9]+>", "", text).strip()
            if clean_text:
                history.append({"role": "user", "content": clean_text})

    # 마지막 메시지(현재 질문)는 제외
    if history:
        history = history[:-1]

    # 최근 max_turns개만 유지
    if len(history) > max_turns:
        history = history[-max_turns:]

    logger.info(f"[메모리] 스레드 히스토리 {len(history)}턴 수집")
    return history


def format_history(history: list[dict]) -> str:
    """대화 히스토리를 텍스트 형식으로 변환합니다."""
    if not history:
        return "(이전 대화 없음)"

    lines = []
    for msg in history:
        role = "사용자" if msg["role"] == "user" else "봇"
        lines.append(f"{role}: {msg['content']}")
    return "\n".join(lines)


def rewrite_query(question: str, history: list[dict], llm) -> str:
    """
    대화 히스토리를 참고하여 현재 질문을 독립적인 질문으로 재작성합니다.
    히스토리가 비어있으면 원본 질문을 그대로 반환합니다.
    """
    if not history:
        return question

    history_text = format_history(history)

    chain = REWRITE_PROMPT | llm | StrOutputParser()
    try:
        rewritten = chain.invoke({
            "history": history_text,
            "question": question,
        }).strip()

        if rewritten and rewritten != question:
            logger.info(f"[Query Rewriting] '{question}' → '{rewritten}'")
            return rewritten
        return question

    except Exception as e:
        logger.warning(f"[Query Rewriting] 재작성 실패: {e} → 원본 사용")
        return question
