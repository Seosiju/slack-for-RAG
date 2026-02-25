"""
질문 분류 라우터 (Router)

질문을 분석하여 적절한 처리 경로로 분기합니다.
- "document": 문서 검색이 필요한 질문 → RAG 파이프라인
- "meta":     시스템/문서 메타 정보 질문 → 직접 응답
- "general":  일반 대화/범용 질문 → LLM 직접 답변
"""

import logging
from pathlib import Path

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"

# ── 분류용 프롬프트 (경량, max_tokens=10) ─────────────
CLASSIFIER_PROMPT = ChatPromptTemplate.from_messages([
    ("system", (
        "You are a question classifier. Classify the user's question into exactly one category.\n"
        "Respond with ONLY one word: document, meta, or general.\n\n"
        "Rules:\n"
        "- 'document': Questions about the CONTENT of uploaded documents "
        "(reports, data, statistics, analysis, programs, events described in documents)\n"
        "- 'meta': Questions ONLY about the technical system configuration "
        "(what documents are loaded, how many vector chunks exist, what AI model is being used). "
        "This is ONLY for system/infrastructure questions.\n"
        "- 'general': Everything else — greetings, general knowledge, coding questions, "
        "casual conversation, AND questions about the conversation itself "
        "(e.g. 'what did I just ask?', 'summarize our conversation', 'what was my previous question?'). "
        "Questions about the conversation or chat history are ALWAYS 'general', NEVER 'meta'."
    )),
    ("human", "{question}"),
])


def classify(question: str, llm) -> str:
    """질문을 분류하여 'document', 'meta', 'general' 중 하나를 반환합니다."""
    chain = CLASSIFIER_PROMPT | llm | StrOutputParser()
    try:
        result = chain.invoke({"question": question}).strip().lower()
        # 결과가 유효한 카테고리가 아니면 기본값으로 document 처리
        if result not in ("document", "meta", "general"):
            logger.warning(f"[라우터] 분류 결과가 유효하지 않음: '{result}' → 'document'로 폴백")
            result = "document"
        logger.info(f"[라우터] '{question[:40]}...' → {result}")
        return result
    except Exception as e:
        logger.error(f"[라우터] 분류 실패: {e} → 'document'로 폴백")
        return "document"


def get_meta_response(question: str, vectorstore=None) -> str:
    """시스템 메타 정보에 대한 질문에 직접 답변합니다."""
    # 문서 목록 수집 (PDF + Word)
    data_files = sorted(DATA_DIR.glob("*.pdf")) + sorted(DATA_DIR.glob("*.docx"))
    doc_list = "\n".join([f"  {i}. {f.name}" for i, f in enumerate(data_files, 1)])
    total_docs = len(data_files)

    # 벡터 수
    vector_count = vectorstore.index.ntotal if vectorstore else "알 수 없음"

    response = (
        f"현재 시스템 정보입니다.\n\n"
        f"📄 로드된 문서 ({total_docs}개):\n{doc_list}\n\n"
        f"🔢 벡터 인덱스: {vector_count}개 청크\n"
    )
    return response
