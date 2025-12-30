import os
from openai import OpenAI

class OpenAIChatCompletionClient:
    def __init__(self, model="gpt-4o"):
        """
        OpenAI API 클라이언트 초기화
        :param model: 사용할 모델명 (gpt-4o, gpt-4-turbo, gpt-3.5-turbo 등)
        """
        # 환경변수에서 API 키를 가져옵니다.
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.offline = False

        if not self.api_key:
            print("[Warning] OPENAI_API_KEY not found. Running in OFFLINE mode (Mock response).")
            self.offline = True
            self.client = None
        else:
            try:
                self.client = OpenAI(api_key=self.api_key)
            except Exception as e:
                print(f"[Error] OpenAI Client init failed: {e}")
                self.offline = True

        self.model = model

    def chat(self, messages, temperature=0.7):
        """
        Chat Completion API를 호출합니다.
        :param messages: [{"role": "system", "content": "..."}, ...] 형태의 리스트
        :return: 모델이 생성한 텍스트 (str)
        """
        # 1. 오프라인 모드(API 키 없음)이거나 에러 발생 시 더미 응답 반환
        if self.offline or not self.client:
            return (
                "TITLE: [오프라인 모드] 제목 예시\n"
                "BODY: 현재 OpenAI API 키가 없거나 오프라인 상태입니다. "
                "이것은 테스트용 더미 응답입니다. API 키를 설정해주세요."
            )

        # 2. 실제 API 호출
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
            )
            return response.choices[0].message.content

        except Exception as e:
            print(f"[OpenAIClient] API Request Error: {e}")
            return "TITLE: 에러 발생\nBODY: API 호출 중 오류가 발생했습니다."

if __name__ == "__main__":
    # 테스트 코드
    client = OpenAIChatCompletionClient()
    res = client.chat([
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello!"}
    ])
    print("Response:", res)