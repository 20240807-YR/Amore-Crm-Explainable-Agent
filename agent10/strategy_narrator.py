import traceback
from brand_rules import build_brand_rule_block


class StrategyNarrator:
    """
    3-PASS (HARD LIMITED)
    - TOTAL LLM CALLS <= 4 (per row)

    FINAL RULES:
    - BODY: 300~350자
    - TITLE: 25~40자
    - TITLE: 이모지 앞/뒤 필수 (강제 래핑)
    """

    def __init__(self, llm, tone_profile_map=None):
        self.llm = llm
        self.tone_profile_map = tone_profile_map or {}

        self.MIN_BODY_LEN = 300
        self.MAX_BODY_LEN = 350
        self.MIN_TITLE_LEN = 25
        self.MAX_TITLE_LEN = 40

        self.HOOK_POINTS = [
            "5분", "오늘", "바로", "딱", "핵심", "루틴", "출근", "사무실",
            "수분", "모공", "속건조", "피지", "가볍게", "간단히"
        ]
        self.EMOJIS = ["✨", "🔥", "💧", "⏱️", "🌿"]

        self.MAX_LLM_CALLS = 4
        self._llm_calls = 0

    # -------------------------------------------------
    # utils
    # -------------------------------------------------
    def _call_llm(self, messages):
        if self._llm_calls >= self.MAX_LLM_CALLS:
            raise RuntimeError("LLM call limit exceeded (max=4)")
        self._llm_calls += 1
        return self.llm.chat(messages) or ""

    def _s(self, v):
        return "" if v is None else str(v).strip()

    def _len_ok(self, s, mn, mx):
        n = len((s or "").strip())
        return mn <= n <= mx

    def _has_hook(self, title):
        t = (title or "").strip()
        return any(h in t for h in self.HOOK_POINTS)

    # ✅ 이모지 강제 래핑 (검사 ❌, 무조건 보정)
    def _wrap_emoji(self, title):
        t = (title or "").strip()
        emoji = self.EMOJIS[0]

        # 앞 제거
        for e in self.EMOJIS:
            if t.startswith(e):
                t = t[len(e):].strip()
            if t.endswith(e):
                t = t[:-len(e)].strip()

        return f"{emoji} {t} {emoji}"

    def _extract(self, text):
        title, body = "", ""
        for line in (text or "").splitlines():
            line = line.strip()
            if line.startswith("TITLE:"):
                title = line.replace("TITLE:", "").strip()
            elif line.startswith("BODY:"):
                body = line.replace("BODY:", "").strip()
        return title, body

    # -------------------------------------------------
    # BODY 길이 보정
    # -------------------------------------------------
    def _normalize_body_len(self, body: str) -> str:
        body = (body or "").strip()

        filler = (
            "아침과 저녁 어느 순간에도 부담 없이 손이 가는 루틴으로 "
            "일상의 흐름을 자연스럽게 이어줍니다. "
        )

        while len(body) < self.MIN_BODY_LEN:
            body += " " + filler

        if len(body) > self.MAX_BODY_LEN:
            body = body[: self.MAX_BODY_LEN].rstrip()

        return body

    # -------------------------------------------------
    # TITLE 길이 보정 (이모지 제외 상태에서 처리)
    # -------------------------------------------------
    def _normalize_title_len(self, title: str) -> str:
        title = (title or "").strip()

        if not self._has_hook(title):
            title = f"{title} 출근 5분 루틴".strip()

        pad = " 오늘 루틴 포인트"
        while len(title) < self.MIN_TITLE_LEN:
            title += pad

        if len(title) > self.MAX_TITLE_LEN:
            title = title[: self.MAX_TITLE_LEN].rstrip()

        return title

    # -------------------------------------------------
    # PASS 1: EXPAND
    # -------------------------------------------------
    def _expand(self, brand, lifestyle, skin_concern, product_name, tone, rule_block):
        system = (
            "마케팅용 문장을 작성하세요.\n"
            "설명형 금지, 광고 문체 유지.\n"
            "과장/구매유도/CTA 금지.\n\n"
            f"말투: {tone}\n"
            f"브랜드: {brand}\n"
            f"라이프스타일: {lifestyle}\n"
            f"피부고민: {skin_concern}\n"
            f"제품명: {product_name}\n\n"
            f"{rule_block}\n"
            "- BODY는 600~900자\n"
            "- 출력은 TITLE/BODY\n"
        )
        return self._call_llm([
            {"role": "system", "content": system},
            {"role": "user", "content": "작성하세요."}
        ])

    # -------------------------------------------------
    # PASS 2: COMPRESS
    # -------------------------------------------------
    def _compress(self, expanded):
        system = (
            "문장을 재서술로 압축하세요.\n"
            "문장 삭제 금지.\n\n"
            f"- BODY: {self.MIN_BODY_LEN}~{self.MAX_BODY_LEN}자\n"
            f"- TITLE: {self.MIN_TITLE_LEN}~{self.MAX_TITLE_LEN}자\n"
            "- TITLE에 이모지 포함\n"
            "- 후킹 키워드 1개 이상\n"
            "출력: TITLE/BODY\n"
        )
        return self._call_llm([
            {"role": "system", "content": system},
            {"role": "user", "content": expanded}
        ])

    # -------------------------------------------------
    # main
    # -------------------------------------------------
    def generate(self, row, plan, brand_rule):
        try:
            self._llm_calls = 0

            brand = self._s(row.get("brand"))
            lifestyle = self._s(row.get("lifestyle"))
            skin = self._s(row.get("skin_concern"))
            product = self._s(row.get("상품명"))

            tone = self.tone_profile_map.get(
                row.get("persona_id"), "자연스러운 마케팅 문체"
            )

            rule_block = build_brand_rule_block(brand_rule)

            expanded = self._expand(brand, lifestyle, skin, product, tone, rule_block)
            compressed = self._compress(expanded)

            title, body = self._extract(compressed)

            # 🔥 순서 중요
            title = self._normalize_title_len(title)
            title = self._wrap_emoji(title)
            body = self._normalize_body_len(body)

            # hook만 최소 체크
            if not self._has_hook(title):
                raise ValueError("TITLE hook missing")

            return f"TITLE: {title}\nBODY: {body}"

        except Exception:
            traceback.print_exc()
            raise