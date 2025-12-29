class ReActReasoningAgent:
    def __init__(self, llm, tone_map):
        self.llm = llm
        self.tone_map = tone_map

    def plan(self, row):
        outline = [
            "라이프스타일과 환경 맥락 제시",
            "피부 고민과 제품 연결",
            "루틴/시간대/사용 흐름",
            "구매 텀 완곡 + CTA"
        ]

        return {
            "message_outline": outline,
            "tone_rules": self.tone_map.get(str(row.get("brand_tone_cluster")), ""),
            "persona_fields": {k: row.get(k) for k in row},
        }