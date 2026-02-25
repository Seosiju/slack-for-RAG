import os
from openai import OpenAI
from dotenv import load_dotenv

# .env 파일에서 토큰 로딩 (상위 경로)
env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
load_dotenv(env_path)

def test_openai_api():
    print("🤖 OpenAI API 연결 테스트 시작!")
    
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("❌ 오류: .env 파일에서 OPENAI_API_KEY를 찾을 수 없습니다.")
        return
        
    print(f"🔑 사용 중인 API 키: {api_key[:10]}...{api_key[-4:]}")
    
    client = OpenAI()
    
    try:
        # 1. 채팅 API 통신 테스트 (비용이 저렴하고 가장 기본)
        print("\n⏳ 1. ChatGPT 모델(gpt-4o-mini) 연결 응답 대기 중...")
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "Hello, are you there? 짧게 대답해줘."}],
            max_tokens=20
        )
        print("✅ 시스템 응답:", response.choices[0].message.content)
        
        # 2. 임베딩 API 테스트 (방금 전 에러가 났던 지점)
        print("\n⏳ 2. 임베딩 모델(text-embedding-3-small) 연결 대기 중 (방금 에러 났던 부분)...")
        emb_response = client.embeddings.create(
            model="text-embedding-3-small",
            input="테스트 문장입니다. 이 문장을 숫자로 바꿔주세요."
        )
        vector_length = len(emb_response.data[0].embedding)
        print(f"✅ 임베딩 성공! 변환된 벡터의 길이: {vector_length} 차원")
        
        print("\n🎉 모든 API 테스트를 성공적으로 통과했습니다!")
        print("   이제 결제가 완전히 API 키에 반영되었습니다. app.py를 다시 실행하셔도 좋습니다.")
        
    except Exception as e:
        print("\n❌ API 호출 실패!")
        print("결제 직후라면 서버(OpenAI)에 카드 정보가 동기화되기까지 5~10분 정도 걸릴 수 있습니다.")
        print("-" * 50)
        print(f"에러 상세 내용:\n{e}")

if __name__ == "__main__":
    test_openai_api()
