# agent10/openai_client.py
import os
import time

try:
    from openai import OpenAI
except Exception:
    OpenAI = None


class OpenAIChatCompletionClient:
    """
    OpenAI ChatCompletion Client (Ollama 완전 차단 + 라우팅 디버그)

    - 모델: gpt-4o-mini
    - base_url: https://api.openai.com/v1 (강제)
    - OPENAI_OFFLINE=1 이면 더미 응답
    - Ollama / localhost / 로컬 LLM 경로 완전 차단
    - 항상 str 반환
    """

    def __init__(self, model="gpt-4o-mini"):
        # -------------------------------------------------
        # 🔥 Ollama 관련 환경변수 완전 제거
        # -------------------------------------------------
        for k in [
            "OLLAMA_BASE_URL",
            "OLLAMA_HOST",
            "DISABLE_OLLAMA",
            "LOCAL_LLM",
            "LLM_PROVIDER",
        ]:
            os.environ.pop(k, None)

        self.model = model
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.offline = os.getenv("OPENAI_OFFLINE", "0") == "1"

        self.base_url = "https://api.openai.com/v1"
        self.provider = "openai"

        self.client = None

        if self.offline:
            print("[OpenAIClient] OPENAI_OFFLINE=1 -> OFFLINE mode")
            return

        if not self.api_key:
            print("[OpenAIClient] OPENAI_API_KEY not found -> OFFLINE mode")
            self.offline = True
            return

        if OpenAI is None:
            print("[OpenAIClient] openai package not available -> OFFLINE mode")
            self.offline = True
            return

        try:
            # ✅ base_url 강제 지정
            self.client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
            )
        except Exception as e:
            print(f"[OpenAIClient] OpenAI init failed: {e}")
            self.offline = True
            self.client = None

    # -------------------------------------------------
    # utils
    # -------------------------------------------------
    def _dummy_response(self):
        return (
            "TITLE: [오프라인 모드]\n"
            "BODY: OPENAI_API_KEY가 없거나 OpenAI 호출이 비활성화되어 있습니다."
        )

    # -------------------------------------------------
    # main
    # -------------------------------------------------
    def chat(self, messages, temperature=0.7):
        """
        messages: [{"role": "system"|"user"|"assistant", "content": "..."}]
        return: str
        """

        # -------------------------------------------------
        # Strict type guard: messages must be list of dicts with keys 'role' and 'content'
        # -------------------------------------------------
        if not isinstance(messages, list):
            raise TypeError(
                "OpenAIChatCompletionClient.chat expects messages as list[{'role','content'}]; "
                f"got {type(messages)}"
            )

        for m in messages:
            if not isinstance(m, dict) or "role" not in m or "content" not in m:
                raise ValueError(
                    "Each message must be dict with keys {'role','content'}; "
                    f"got {m}"
                )

        # 🔥 실제 호출 직전 라우팅 디버그 (판별용 핵심 로그)
        print(
            "[LLM ROUTE DEBUG]",
            "provider=", self.provider,
            "model=", self.model,
            "base_url=", self.base_url,
            "OPENAI_OFFLINE=", os.getenv("OPENAI_OFFLINE"),
            "OLLAMA_BASE_URL=", os.getenv("OLLAMA_BASE_URL"),
        )

        if self.offline or not self.client:
            return self._dummy_response()

        if not messages:
            return self._dummy_response()

        max_attempts = 3
        backoff = 1.5

        for attempt in range(1, max_attempts + 1):
            try:
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=float(temperature),
                )
                content = resp.choices[0].message.content
                return (content or "").strip() or "TITLE:\nBODY:"
            except Exception as e:
                print(f"[OpenAIClient] API Request Error (attempt {attempt}): {e}")
                if attempt < max_attempts:
                    time.sleep(backoff ** attempt)
                    continue
                break

        return (
            "TITLE: 오류 발생\n"
            "BODY: OpenAI API 호출 중 오류가 발생했습니다."
        )

    # -------------------------------------------------
    # compatibility wrapper (for StrategyNarrator)
    # -------------------------------------------------
    def generate(self, messages=None, system=None, user=None, temperature=0.7):
        # StrategyNarrator may call generate(messages=...)
        if messages is not None:
            if not isinstance(messages, list):
                raise TypeError(
                    "OpenAIChatCompletionClient.generate(messages=...) requires messages as list; "
                    f"got {type(messages)}"
                )
            return self.chat(messages=messages, temperature=temperature)

        # Or generate(system, user) style
        if system is not None and user is not None:
            return self.chat(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=temperature,
            )

        return self._dummy_response()

if __name__ == "__main__":
    # 단독 테스트
    client = OpenAIChatCompletionClient()
    res = client.chat([
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello!"}
    ])
    print(res)