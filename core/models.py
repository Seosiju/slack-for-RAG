"""
다중 모델 레지스트리 (Model Registry)

LangChain의 BaseChatModel 인터페이스를 활용하여,
여러 AI 제공자의 모델을 통일된 인터페이스로 관리합니다.

사용 가능한 모델은 .env에 해당 API Key가 존재하는 경우에만 등록됩니다.
"""

import os
import logging

from langchain_openai import ChatOpenAI, OpenAIEmbeddings

logger = logging.getLogger(__name__)

# ── 기본 설정 ─────────────────────────────────────────
DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_TEMPERATURE = 0.2


def get_available_models() -> dict:
    """
    사용 가능한 LLM 모델 딕셔너리를 반환합니다.
    .env에 API Key가 존재하는 제공자의 모델만 등록합니다.
    """
    models = {}

    # ── OpenAI ──
    if os.getenv("OPENAI_API_KEY"):
        models["gpt-4o-mini"] = ChatOpenAI(model="gpt-4o-mini", temperature=DEFAULT_TEMPERATURE)
        models["gpt-4o"] = ChatOpenAI(model="gpt-4o", temperature=DEFAULT_TEMPERATURE)

    # ── Google Gemini (확장 시 주석 해제) ──
    # pip install langchain-google-genai
    # if os.getenv("GOOGLE_API_KEY"):
    #     from langchain_google_genai import ChatGoogleGenerativeAI
    #     models["gemini-2.0-flash"] = ChatGoogleGenerativeAI(
    #         model="gemini-2.0-flash", temperature=DEFAULT_TEMPERATURE
    #     )

    # ── Anthropic Claude (확장 시 주석 해제) ──
    # pip install langchain-anthropic
    # if os.getenv("ANTHROPIC_API_KEY"):
    #     from langchain_anthropic import ChatAnthropic
    #     models["claude-sonnet"] = ChatAnthropic(
    #         model="claude-sonnet-4-20250514", temperature=DEFAULT_TEMPERATURE
    #     )

    return models


def get_llm(model_name: str | None = None):
    """모델 이름으로 LLM 인스턴스를 반환합니다."""
    models = get_available_models()
    name = model_name or DEFAULT_MODEL

    if name not in models:
        available = ", ".join(models.keys())
        raise ValueError(f"'{name}' 모델을 찾을 수 없습니다. 사용 가능: {available}")

    return models[name]


def list_models() -> list[str]:
    """사용 가능한 모델 이름 목록을 반환합니다."""
    return list(get_available_models().keys())


def get_embeddings():
    """임베딩 모델 인스턴스를 반환합니다."""
    return OpenAIEmbeddings(model="text-embedding-3-small")
