class ReActReasoningAgent:
    def __init__(self, llm, tone_map):
        self.llm = llm
        self.tone_map = tone_map

        # LLM이 사고(확장)해도 되는 페르소나 컬럼 화이트리스트
        self.expandable_fields = [
            "preference",
            "shopping_pattern",
            "lifestyle",
            "skin_type",
            "skin_concern",
            "allergy_sensitivity",
            "texture_preference",
            "finish_preference",
            "scent_preference",
            "routine_step_count",
            "time_of_use",
            "seasonality",
            "environment_context",
            "price_sensitivity",
            "brand_loyalty",
            "repurchase_tendency",
            "shopping_channel",
            "review_dependency",
            "bundle_preference",
            "ingredient_avoid_list",
            "ethical_preference",
            "treatment_status",
            "message_tone_preference",
            "message_length_preference",
            "cta_style",
        ]

    def plan(self, row):
        outline = [
            "라이프스타일과 환경 맥락 제시",
            "피부 고민과 제품 연결",
            "루틴/시간대/사용 흐름",
            "구매 텀 완곡 + CTA"
        ]

        # -------------------------------------------------
        # 1. 원문 lifestyle (Verifier용, 절대 변경 금지)
        # -------------------------------------------------
        lifestyle_raw = row.get("lifestyle", "") or ""

        # -------------------------------------------------
        # 2. LLM 사고용 입력 구성 (화이트리스트만)
        # -------------------------------------------------
        expandable_context = {}
        for k in self.expandable_fields:
            v = row.get(k)
            if v:
                expandable_context[k] = v

        # -------------------------------------------------
        # 3. lifestyle / persona 맥락 확장 (문장 생성 금지)
        # -------------------------------------------------
        lifestyle_expanded = ""
        if expandable_context:
            try:
                lifestyle_expanded = self.llm.generate(
                    f"""
                    다음 페르소나 정보를 바탕으로,
                    문장에서 활용할 수 있는 '상황·맥락 확장 힌트'만 정리하라.

                    [절대 규칙]
                    - 마케팅 문구 작성 금지
                    - 문장 생성 금지
                    - 추천/평가/비교/판단 표현 금지
                    - 감정 과장 금지
                    - 짧은 구문(phrase) 형태로만 작성
                    - 원문 문자열을 바꾸거나 대체하지 말 것

                    [입력 페르소나 맥락]
                    {expandable_context}

                    [출력 예시]
                    - 아침 출근 전 짧은 준비 시간
                    - 실내 냉난방이 반복되는 환경
                    - 업무 중 잦은 마스크 착용
                    - 간단하고 빠른 사용을 선호하는 루틴
                    """
                ).strip()
            except Exception:
                lifestyle_expanded = ""

        # -------------------------------------------------
        # 4. 기존 구조 유지 + 확장 힌트만 추가
        # -------------------------------------------------
        return {
            "message_outline": outline,
            "tone_rules": self.tone_map.get(str(row.get("brand_tone_cluster")), ""),
            "persona_fields": {k: row.get(k) for k in row},  # 🔒 기존 그대로
            "lifestyle_expanded": lifestyle_expanded,        # ➕ 사고 결과
        }