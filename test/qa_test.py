"""
RAG 파이프라인 로컬 테스트 도구

Slack 없이 터미널에서 질문→라우팅→검색→답변 전 과정을 상세하게 추적합니다.

실행:
    python test/qa_test.py                          # 대화형 모드
    python test/qa_test.py "코칭스터디 17기 수료율은?"  # 단발 질문 모드
"""

import os
import sys
import json
import logging

# 상위 폴더의 모듈을 import 하기 위한 경로 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.rag import RAG

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


def print_separator(title: str = "", char: str = "─", width: int = 70):
    if title:
        padding = (width - len(title) - 2) // 2
        print(f"\n{char * padding} {title} {char * padding}")
    else:
        print(char * width)


def print_trace(trace: dict, show_prompt: bool = False):
    """RAG trace 결과를 사람이 읽기 좋게 출력합니다."""

    # ── 질문 + 라우팅 결과 ──
    print_separator("입력 질문")
    route_label = {"document": "📄 문서 검색", "meta": "ℹ️ 시스템 정보", "general": "💬 일반 대화"}
    print(f"  {trace['question']}")
    print(f"  → 라우팅: {route_label.get(trace.get('route', ''), trace.get('route', '?'))}")

    # ── 검색 결과 (document 경로만) ──
    if trace.get("retrieved_chunks"):
        print_separator(f"검색된 청크 (Top-{len(trace['retrieved_chunks'])})")
        for i, chunk in enumerate(trace["retrieved_chunks"], 1):
            print(f"\n  [{i}] 출처: {chunk['source']} (p.{chunk['page']})  |  유사도: {chunk['score']}")
            preview = chunk["text"][:150].replace("\n", " ")
            if len(chunk["text"]) > 150:
                preview += "..."
            print(f"      {preview}")

    # ── 프롬프트 (선택) ──
    if show_prompt and trace.get("prompt"):
        print_separator("LLM에 전달된 프롬프트 전문")
        print(trace["prompt"])

    # ── 답변 ──
    print_separator("LLM 생성 답변")
    print(f"  {trace['answer']}")

    # ── 성능 지표 ──
    print_separator("성능 지표")
    timing = trace["timing"]
    print(f"  라우팅 분류:      {timing.get('0_routing', '-')}초")
    print(f"  벡터 검색 소요:   {timing.get('1_retrieval', '-')}초")
    print(f"  LLM 답변 생성:    {timing.get('2_llm_generation', '-')}초")
    print(f"  전체 소요 시간:   {timing.get('total', '?')}초")
    print(f"  사용 모델:        LLM={trace.get('model', '?')} / Embedding={trace.get('embedding_model', '?')}")
    print(f"  라우팅 경로:      {trace.get('route', '?')}")

    if "token_usage" in trace:
        usage = trace["token_usage"]
        print(f"  토큰 사용량:      프롬프트={usage['prompt_tokens']} + 답변={usage['completion_tokens']} = 총 {usage['total_tokens']}토큰")

    print_separator()


def interactive_mode(rag: RAG):
    """대화형 테스트 모드"""
    print("\n" + "=" * 70)
    print("  🧪 RAG 파이프라인 로컬 테스트 (대화형 모드)")
    print("  명령어:")
    print("    /prompt  — 프롬프트 전문 출력 ON/OFF")
    print("    /search  — 검색만 수행 (LLM 호출 없이)")
    print("    /model   — 모델 변경 (/model gpt-4o)")
    print("    /save    — 마지막 trace를 JSON 저장")
    print("    /quit    — 종료")
    print("=" * 70)

    show_prompt = False
    last_trace = None

    while True:
        try:
            question = input("\n💬 질문: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n\n👋 테스트를 종료합니다.")
            break

        if not question:
            continue

        if question == "/quit":
            print("👋 테스트를 종료합니다.")
            break

        if question == "/prompt":
            show_prompt = not show_prompt
            status = "ON 🟢" if show_prompt else "OFF 🔴"
            print(f"  프롬프트 전문 출력: {status}")
            continue

        if question == "/save":
            if last_trace:
                filepath = os.path.join(os.path.dirname(os.path.dirname(__file__)), "test/last_trace.json")
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(last_trace, f, ensure_ascii=False, indent=2)
                print(f"  💾 저장 완료: {filepath}")
            else:
                print("  아직 질문한 적이 없습니다.")
            continue

        if question.startswith("/model"):
            parts = question.split()
            if len(parts) > 1:
                try:
                    rag.set_model(parts[1])
                    print(f"  ✅ 모델이 {parts[1]}로 변경되었습니다.")
                except ValueError as e:
                    print(f"  ❌ {e}")
            else:
                from core.models import list_models
                print(f"  사용 가능: {', '.join(list_models())}")
            continue

        if question.startswith("/search "):
            query = question[8:].strip()
            if not query:
                print("  사용법: /search 검색할 질문")
                continue
            print_separator(f"검색만 수행: '{query}'")
            results = rag.search(query)
            for i, (doc, score) in enumerate(results, 1):
                source = doc.metadata.get("source", "?")
                source_name = os.path.basename(source) if source else "?"
                page = doc.metadata.get("page", "?")
                preview = doc.page_content[:200].replace("\n", " ")
                print(f"\n  [{i}] 유사도: {score:.4f} | 출처: {source_name} (p.{page})")
                print(f"      {preview}")
            print_separator()
            continue

        # ── 일반 질문 → 전체 파이프라인 실행 ──
        try:
            last_trace = rag.ask_with_trace(question, source="test")
            print_trace(last_trace, show_prompt=show_prompt)
        except Exception as e:
            print(f"\n  ❌ 오류 발생: {e}")
            import traceback
            traceback.print_exc()


def main():
    print("🔧 RAG 엔진 초기화 중...")
    rag = RAG()
    print("✅ RAG 엔진 준비 완료!\n")

    if len(sys.argv) > 1:
        question = " ".join(sys.argv[1:])
        trace = rag.ask_with_trace(question, source="test")
        print_trace(trace, show_prompt=True)
    else:
        interactive_mode(rag)


if __name__ == "__main__":
    main()
