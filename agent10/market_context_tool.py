# market_context_tool.py
class MarketContextTool:
    def __init__(self, enabled=False):
        self.enabled = enabled

    def fetch(self, brand: str):
        if not self.enabled:
            return {}
        return {}