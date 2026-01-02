# agent10/market_context_tool.py
# ✅ 자기 자신을 import 하는 순환/자기참조 때문에 ImportError 난 상태라
# ✅ 이 파일은 "절대" from market_context_tool import MarketContextTool 같은 라인을 가지면 안 됨.

import os
print("[MarketContextTool] module loaded")


class MarketContextTool:
    def __init__(self, enabled: bool = False, serpapi_api_key: str | None = None):
        self.enabled = bool(enabled)
        self.api_key = serpapi_api_key or os.getenv("SERPAPI_API_KEY") or ""

    def fetch(self, brand: str):
        """
        controller에서 호출:
            market.fetch(brand) if use_market_context else {}

        지금은 use_market_context=False가 기본이니까,
        enabled=False면 무조건 {} 리턴해서 안전하게 우회.
        """
        print(f"[MarketContextTool] fetch called | enabled={self.enabled}")

        if not self.enabled:
            return {}

        # enabled=True인데도 키가 없으면 안전하게 빈 컨텍스트
        if not self.api_key:
            return {}

        # ✅ 여기서 SerpAPIWrapper 실제 호출을 붙이면 됨.
        # 현재는 파이프라인 깨지지 않게 placeholder로만 둠.
        brand = (brand or "").strip()
        if not brand:
            return {}

        return {
            "brand": brand,
            "note": "market_context_tool placeholder (SerpAPI not wired in this build)",
        }