# agent10/strategy_narrator.py
import traceback
from brand_rules import build_brand_rule_block


class StrategyNarrator:
    def __init__(self, llm, tone_profile_map=None):
        self.llm = llm
        self.tone_profile_map = tone_profile_map or {}

    def _s(self, v):
        return "" if v is None else str(v).strip()

    def _as_list(self, v):
        if v is None:
            return []
        if isinstance(v, (list, tuple)):
            return [self._s(x) for x in v if self._s(x)]
        s = self._s(v)
        if not s:
            return []
        return [t.strip() for t in s.split(",") if t.strip()]

    # -------------------------------------------------
    # ✅ 최소 가드만 유지
    # - product_name이 비었을 때만 에러
    # - 품질/의미/옵션/길이 판단은 하지 않음
    # -------------------------------------------------
    def _validate_product_name(self, product_name: str):
        s = (product_name or "").strip()
        if not s or s.lower() == "nan":
            raise ValueError("[Narrator] 제품명 없음(nan/empty) → 생성 중단")

    def generate(self, row: dict, plan: dict, brand_rule: dict, repair_errors: list = None):

        # -------------------------------------------------
        # 1. 핵심 식별 정보
        # -------------------------------------------------
        persona_id = self._s(row.get("persona_id", "Unknown"))
        brand = self._s(row.get("brand_name_slot")) or self._s(row.get("brand", ""))

        tone_keyword = self.tone_profile_map.get(
            persona_id,
            "차분하고 과장되지 않은 설명형 말투"
        )

        rule_block = build_brand_rule_block(brand_rule)

        # -------------------------------------------------
        # 2. 의미 재료
        # -------------------------------------------------
        lifestyle = self._s(row.get("lifestyle", ""))
        skin_concern = self._s(row.get("skin_concern", ""))
        product_name = self._s(row.get("상품명", ""))

        # ✅ 제품명 비었을 때만 중단
        self._validate_product_name(product_name)

        outline = plan.get("message_outline", []) if isinstance(plan, dict) else []

        brand_must_include = self._as_list(plan.get("brand_must_include")) if isinstance(plan, dict) else []
        if not brand_must_include:
            brand_must_include = self._as_list(brand_rule.get("must_include"))

        must_include_block = ""
        if brand_must_include:
            must_include_block = (
                "[브랜드 필수어(반드시 본문에 자연스럽게 포함)]\n"
                + "\n".join([f"- {w}" for w in brand_must_include])
                + "\n\n"
            )

        # -------------------------------------------------
        # 3. system_prompt
        # -------------------------------------------------
        system_prompt = (
            "당신은 추천을 판단하는 AI가 아닙니다.\n"
            "이미 결정된 전략 정보를 문장으로 편집하는 편집기입니다.\n\n"
            f"말투 가이드: {tone_keyword}\n\n"
            "[필수 반영 정보]\n"
            f"- 브랜드: {brand}\n"
            f"- 라이프스타일: {lifestyle}\n"
            f"- 피부 고민: {skin_concern}\n"
            f"- 제품명: {product_name}\n\n"
            f"{must_include_block}"
            "[문장 슬롯 강제 규칙]\n"
            "BODY는 반드시 아래 4개 슬롯을 순서대로 모두 포함해야 합니다.\n"
            "각 슬롯은 의미적으로 분리되어야 하며, 하나라도 누락되면 실패입니다.\n\n"
            "슬롯 1) 라이프스타일 맥락\n"
            "슬롯 2) 피부 고민 명시\n"
            "슬롯 3) 브랜드 + 제품 연결\n"
            "슬롯 4) 루틴/지속 맥락\n\n"
            "[브랜드 필수어 규칙]\n"
            "제공된 브랜드 필수어가 있다면 BODY에 전부 포함해야 합니다.\n"
            "단, 나열 목록처럼 쓰지 말고 문맥 안에 자연스럽게 녹여야 합니다.\n\n"
            "[금지 사항]\n"
            "- 메타 표현(전략/톤/설계/기획 등) 금지\n"
            "- 구매 유도/확인 요청 문구 금지\n\n"
            "[형식 규칙]\n"
            "0) 출력은 정확히 2줄\n"
            "   - TITLE: 로 시작하는 1줄\n"
            "   - BODY: 로 시작하는 1줄\n"
            "1) TITLE ≤ 40자\n"
            "2) BODY 200~450자\n\n"
            f"{rule_block}\n"
        )

        # -------------------------------------------------
        # 4. user_prompt
        # -------------------------------------------------
        user_prompt = (
            "[문장 구조 참고]\n"
            f"- 순서: {' → '.join(outline)}\n\n"
            "위 정보를 사용해 CRM 메시지를 작성하세요.\n"
        )

        if repair_errors:
            err_str = (
                ", ".join(map(str, repair_errors))
                if isinstance(repair_errors, (list, tuple))
                else self._s(repair_errors)
            )
            user_prompt += (
                "\n[REPAIR MODE]\n"
                "4슬롯 구조를 유지하며 아래 오류만 최소 수정으로 해결하세요.\n"
                f"- 오류 목록: {err_str}\n"
            )

        user_prompt += (
            "\n[출력 형식]\n"
            "TITLE: (40자 이내)\n"
            "BODY: (200~450자)\n"
        )

        # -------------------------------------------------
        # 5. LLM 호출
        # -------------------------------------------------
        try:
            response = self.llm.chat([
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ])
            return (response or "").strip()

        except Exception as e:
            print(f"[StrategyNarrator] Error: {e}")
            traceback.print_exc()
            raise