"""
RAG (Retrieval-Augmented Generation) 엔진 — LangChain 기반

질문 라우팅 → 하이브리드 검색 → LLM 답변 생성 파이프라인을 통합 관리합니다.
"""

import json
import shutil
import time
import logging
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import PyMuPDFLoader, Docx2txtLoader
from langchain_community.vectorstores import FAISS
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough

from core.models import get_llm, get_embeddings, DEFAULT_MODEL
from core.router import classify, get_meta_response
from core.memory import rewrite_query, format_history

load_dotenv()

logger = logging.getLogger(__name__)

# ── 설정 ──────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
INDEX_DIR = BASE_DIR / "index"
LOG_DIR = BASE_DIR / "logs"
CHUNK_SIZE = 500
CHUNK_OVERLAP = 100
TOP_K = 10

# ── 시스템 프롬프트 (범용 어시스턴트) ─────────────────
SYSTEM_PROMPT_RAG = (
    "당신은 AI 어시스턴트입니다.\n"
    "아래 참고 문서가 제공된 경우, 문서 내용을 근거로 정확하게 답변하세요.\n"
    "문서에 근거한 답변의 경우 출처(문서명)를 함께 언급해주세요.\n"
    "문서에 없는 내용을 질문받으면 '제공된 문서에서 확인할 수 없습니다'라고 답하세요."
)

SYSTEM_PROMPT_GENERAL = (
    "당신은 도움이 되는 AI 어시스턴트입니다.\n"
    "사용자의 질문에 친절하고 정확하게 답변하세요."
)

PROMPT_TEMPLATE_RAG = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT_RAG),
    ("human", "{history_block}## 참고 문서\n\n{context}\n\n## 질문\n\n{question}"),
])

PROMPT_TEMPLATE_GENERAL = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT_GENERAL),
    ("human", "{history_block}{question}"),
])


# ── JSONL 트레이스 로거 ───────────────────────────────
def _save_trace_to_jsonl(trace: dict):
    """trace dict를 logs/traces.jsonl에 한 줄씩 추가 저장합니다."""
    LOG_DIR.mkdir(exist_ok=True)
    filepath = LOG_DIR / "traces.jsonl"

    record = {
        "timestamp": datetime.now().isoformat(),
        "question": trace.get("question", ""),
        "rewritten_query": trace.get("rewritten_query", ""),
        "route": trace.get("route", ""),
        "answer": trace.get("answer", ""),
        "source": trace.get("source", "unknown"),
        "chat_history_turns": len(trace.get("chat_history", [])),
        "retrieved_chunks": [
            {
                "source": c["source"],
                "page": c["page"],
                "score": c["score"],
                "text_preview": c["text"][:200],
            }
            for c in trace.get("retrieved_chunks", [])
        ],
        "timing": trace.get("timing", {}),
        "token_usage": trace.get("token_usage", {}),
        "model": trace.get("model", ""),
        "embedding_model": trace.get("embedding_model", ""),
    }

    with open(filepath, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


class RAG:
    """PDF 기반 RAG 시스템 (라우팅 + 하이브리드 검색)"""

    def __init__(self, model_name: str | None = None):
        self.llm = get_llm(model_name)
        self.embeddings = get_embeddings()
        self.vectorstore: FAISS | None = None

        # 캐시가 유효한지 확인 → 유효하면 로드, 아니면 빌드
        if self._cache_is_valid():
            self._load_cache()
        else:
            self._build()

    # ── 인덱스 빌드 ───────────────────────────────────
    def _build(self):
        """PDF 로드 → 청크 분할 → 임베딩 → FAISS 인덱스 생성"""
        print("🔨 인덱스를 새로 빌드합니다...")

        documents = []
        
        # 1. PDF 파일 로드
        for pdf_path in sorted(DATA_DIR.glob("*.pdf")):
            loader = PyMuPDFLoader(str(pdf_path))
            docs = loader.load()
            documents.extend(docs)
            total_chars = sum(len(d.page_content) for d in docs)
            print(f"  📄 [PDF] 로드 완료: {pdf_path.name} ({total_chars:,}자, {len(docs)}페이지)")

        # 2. Word (.docx) 파일 로드
        for docx_path in sorted(DATA_DIR.glob("*.docx")):
            loader = Docx2txtLoader(str(docx_path))
            docs = loader.load()
            documents.extend(docs)
            total_chars = sum(len(d.page_content) for d in docs)
            print(f"  📝 [Word] 로드 완료: {docx_path.name} ({total_chars:,}자)")

        if not documents:
            raise FileNotFoundError(f"data/ 폴더에 PDF 또는 Word 파일이 없습니다: {DATA_DIR}")

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
            separators=["\n\n", "\n", ". ", " ", ""],
        )
        chunks = splitter.split_documents(documents)
        print(f"  🔪 총 {len(chunks)}개 청크 생성")

        # 각 청크의 텍스트 앞에 출처 문서명을 삽입 (검색 품질 향상)
        for chunk in chunks:
            source = chunk.metadata.get("source", "")
            source_name = Path(source).name if source else "알 수 없음"
            chunk.page_content = f"[출처: {source_name}]\n{chunk.page_content}"

        self.vectorstore = FAISS.from_documents(chunks, self.embeddings)
        print(f"  ✅ FAISS 인덱스 생성 완료 (벡터 {self.vectorstore.index.ntotal}개)")
        self._save_cache()

    # ── 캐시 관리 ─────────────────────────────────────
    MANIFEST_FILE = INDEX_DIR / "manifest.json"

    def _get_current_file_manifest(self) -> dict:
        """data/ 폴더의 현재 파일 목록과 크기를 딕셔너리로 반환합니다."""
        data_files = sorted(DATA_DIR.glob("*.pdf")) + sorted(DATA_DIR.glob("*.docx"))
        return {
            f.name: {"size": f.stat().st_size, "mtime": f.stat().st_mtime}
            for f in data_files
        }

    def _cache_is_valid(self) -> bool:
        index_faiss = INDEX_DIR / "index.faiss"
        index_pkl = INDEX_DIR / "index.pkl"
        if not index_faiss.exists() or not index_pkl.exists():
            return False

        current_manifest = self._get_current_file_manifest()

        # 문서가 하나도 없으면 캐시 무효
        if not current_manifest:
            return False

        # 매니페스트 파일이 없으면 (구버전 캐시) 재빌드
        if not self.MANIFEST_FILE.exists():
            print("📢 매니페스트가 없습니다. 인덱스를 재빌드합니다.")
            return False

        # 저장된 매니페스트와 현재 파일 목록 비교
        with open(self.MANIFEST_FILE, "r", encoding="utf-8") as f:
            saved_manifest = json.load(f)

        saved_names = set(saved_manifest.keys())
        current_names = set(current_manifest.keys())

        # 파일 추가 감지
        added = current_names - saved_names
        if added:
            print(f"📢 새 문서 추가됨: {', '.join(added)} → 인덱스를 재빌드합니다.")
            return False

        # 파일 삭제 감지
        removed = saved_names - current_names
        if removed:
            print(f"📢 문서 삭제됨: {', '.join(removed)} → 인덱스를 재빌드합니다.")
            return False

        # 파일 수정 감지 (크기 또는 수정시간 변경)
        for name in current_names:
            if current_manifest[name]["size"] != saved_manifest[name]["size"]:
                print(f"📢 문서 변경됨: {name} → 인덱스를 재빌드합니다.")
                return False
            if current_manifest[name]["mtime"] > saved_manifest[name]["mtime"]:
                print(f"📢 문서 수정됨: {name} → 인덱스를 재빌드합니다.")
                return False

        return True

    def _save_cache(self):
        INDEX_DIR.mkdir(exist_ok=True)
        self.vectorstore.save_local(str(INDEX_DIR))

        # 매니페스트 저장 (현재 파일 목록 기록)
        manifest = self._get_current_file_manifest()
        with open(self.MANIFEST_FILE, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)

        print(f"  💾 캐시 저장 완료: {INDEX_DIR} (문서 {len(manifest)}개 기록)")

    def _load_cache(self):
        print("📂 캐시된 인덱스를 로드합니다...")
        self.vectorstore = FAISS.load_local(
            str(INDEX_DIR), self.embeddings, allow_dangerous_deserialization=True
        )
        print(f"  ✅ 로드 완료 (벡터 {self.vectorstore.index.ntotal}개)")

    def rebuild(self):
        if INDEX_DIR.exists():
            shutil.rmtree(INDEX_DIR)
        self._build()

    # ── 검색 (디버깅용) ───────────────────────────────
    def search(self, question: str, top_k: int = TOP_K) -> list[tuple]:
        return self.vectorstore.similarity_search_with_score(question, k=top_k)

    # ── 모델 교체 ─────────────────────────────────────
    def set_model(self, model_name: str):
        """런타임에 LLM 모델을 교체합니다."""
        self.llm = get_llm(model_name)
        logger.info(f"[모델 교체] → {model_name}")

    # ── 핵심: 라우팅 + 답변 생성 ──────────────────────
    def ask_with_trace(self, question: str, source: str = "unknown", chat_history: list[dict] | None = None) -> dict:
        """
        질문을 라우팅 → 경로별 처리 → trace 반환

        Args:
            question: 사용자 질문
            source: 요청 출처 ("slack", "dm", "test")
            chat_history: 이전 대화 히스토리 [{"role": "user"|"assistant", "content": "..."}]
        """
        chat_history = chat_history or []

        trace = {
            "question": question,
            "rewritten_query": "",
            "source": source,
            "route": "",
            "chat_history": chat_history,
            "retrieved_chunks": [],
            "context": "",
            "prompt": "",
            "answer": "",
            "timing": {},
            "model": getattr(self.llm, "model_name", str(self.llm)),
            "embedding_model": getattr(self.embeddings, "model", ""),
        }

        if not question.strip():
            trace["answer"] = "질문을 입력해 주세요."
            return trace

        t_start = time.time()

        # ── STEP 0-1: Query Rewriting (대화 맥락 반영) ──
        search_query = question  # 벡터 검색에 사용할 질문
        if chat_history:
            t_rw0 = time.time()
            search_query = rewrite_query(question, chat_history, self.llm)
            t_rw1 = time.time()
            trace["rewritten_query"] = search_query
            trace["timing"]["0_rewriting"] = round(t_rw1 - t_rw0, 3)

        # ── STEP 0-2: 라우팅 (재작성된 질문으로 분류) ──
        t0 = time.time()
        route = classify(search_query, self.llm)
        t1 = time.time()
        trace["route"] = route
        trace["timing"]["0_routing"] = round(t1 - t0, 3)

        # ── 히스토리 블록 (프롬프트 삽입용) ──
        history_block = ""
        if chat_history:
            history_block = f"## 이전 대화\n\n{format_history(chat_history)}\n\n"

        # ── 경로별 처리 ──
        if route == "meta":
            trace["answer"] = get_meta_response(search_query, self.vectorstore)
            trace["timing"]["total"] = round(time.time() - t_start, 3)
            _save_trace_to_jsonl(trace)
            return trace

        if route == "general":
            t2 = time.time()
            prompt_messages = PROMPT_TEMPLATE_GENERAL.format_messages(
                question=question, history_block=history_block
            )
            response = self.llm.invoke(prompt_messages)
            t3 = time.time()
            trace["answer"] = response.content
            trace["timing"]["2_llm_generation"] = round(t3 - t2, 3)
            trace["timing"]["total"] = round(t3 - t_start, 3)
            trace["prompt"] = "\n".join([f"[{m.type}]\n{m.content}" for m in prompt_messages])
            if hasattr(response, "response_metadata"):
                usage = response.response_metadata.get("token_usage", {})
                if usage:
                    trace["token_usage"] = {
                        "prompt_tokens": usage.get("prompt_tokens", 0),
                        "completion_tokens": usage.get("completion_tokens", 0),
                        "total_tokens": usage.get("total_tokens", 0),
                    }
            logger.info(f"[GENERAL] Q: {question[:50]}... | LLM: {trace['timing']['2_llm_generation']}s")
            _save_trace_to_jsonl(trace)
            return trace

        # ── route == "document": RAG 파이프라인 ──
        # STEP 1: 벡터 검색 (재작성된 질문으로 검색)
        t2 = time.time()
        results = self.vectorstore.similarity_search_with_score(search_query, k=TOP_K)
        t3 = time.time()
        trace["timing"]["1_retrieval"] = round(t3 - t2, 3)

        for doc, score in results:
            source_file = doc.metadata.get("source", "알 수 없음")
            source_name = Path(source_file).name if source_file else "알 수 없음"
            trace["retrieved_chunks"].append({
                "source": source_name,
                "page": doc.metadata.get("page", "?"),
                "score": round(float(score), 4),
                "text": doc.page_content,
            })

        # STEP 2: 컨텍스트 조합
        context_parts = []
        for i, chunk in enumerate(trace["retrieved_chunks"], 1):
            context_parts.append(
                f"[문서 {i}] (출처: {chunk['source']}, p.{chunk['page']})\n{chunk['text']}"
            )
        context = "\n\n---\n\n".join(context_parts)
        trace["context"] = context

        # STEP 3: 프롬프트 생성 (히스토리 포함)
        prompt_messages = PROMPT_TEMPLATE_RAG.format_messages(
            context=context, question=question, history_block=history_block
        )
        trace["prompt"] = "\n".join([f"[{m.type}]\n{m.content}" for m in prompt_messages])

        # STEP 4: LLM 호출
        t4 = time.time()
        response = self.llm.invoke(prompt_messages)
        t5 = time.time()
        trace["timing"]["2_llm_generation"] = round(t5 - t4, 3)
        trace["timing"]["total"] = round(t5 - t_start, 3)
        trace["answer"] = response.content

        if hasattr(response, "response_metadata"):
            usage = response.response_metadata.get("token_usage", {})
            if usage:
                trace["token_usage"] = {
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0),
                }

        logger.info(
            f"[RAG] Q: {question[:50]}... | "
            f"검색: {trace['timing'].get('1_retrieval', '?')}s | "
            f"LLM: {trace['timing']['2_llm_generation']}s | "
            f"총: {trace['timing']['total']}s"
        )
        _save_trace_to_jsonl(trace)
        return trace

    # ── 간단 답변 ─────────────────────────────────────
    def ask(self, question: str, source: str = "unknown") -> str:
        trace = self.ask_with_trace(question, source=source)
        return trace["answer"]


# ── 단독 실행 시 간단 테스트 ───────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    rag = RAG()
    print("\n" + "=" * 60)
    test_q = "코칭스터디 17기 수료율은?"
    print(f"Q: {test_q}")
    print(f"A: {rag.ask(test_q, source='cli')}")
