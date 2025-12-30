import re
import random
from agent10.rules_prompt import build_brand_rule_block


class StrategyNarrator:
    def __init__(self, llm_client, tone_profile_map=None, pad_pool=None):
        self.llm = llm_client
        self.tone_profile_map = tone_profile_map or {}

        self.banned_phrases = [
            "브랜드 톤을 유지하며",
            "브랜드 톤을 살려",
            "설계된 제품",
            "기획된",
            "전략적으로",
            "톤을 반영하여",
            "브랜드 아이덴티티",
            "클릭",
            "구매하기",
            "더 알아보려면",
            "(을)를",
            "중심으로",
            "안내드립니다",
            "정리했습니다",
            "고려해",
            "있다면",
            "간접적으로",
        ]

        self.pad_pool = pad_pool or [
            "최근 관리 텀이 길어졌던 흐름을 감안해, 다시 이어가기 부담 없는 구성입니다.",
            "피부 컨디션이 일정하지 않은 날에도 무리 없이 유지할 수 있는 흐름입니다.",
            "과한 약속보다는 일상 속에서 자연스럽게 이어지는 사용감을 기준으로 했습니다.",
            "자극 요소를 최소화해 편안한 사용감을 우선으로 고려했습니다.",
            "리뷰를 꼼꼼히 확인하는 성향에 맞춰 사용감과 루틴 적합성을 중심으로 잡았습니다.",
            "가격 부담 없이 지속 가능한 루틴을 유지할 수 있는 방향입니다.",
        ]

    def _s(self, v):
        return "" if v is None else str(v).strip()

    def _norm(self, s):
        s = "" if s is None else str(s)
        s = re.sub(r"\s+", " ", s).strip()
        s = re.sub(r"\s*,\s*", ", ", s)
        s = re.sub(r"\s*/\s*", "/", s)
        s = re.sub(r"\s*\.\s*\.", ".", s)
        return s.strip()

    def _remove_banned(self, text):
        t = self._s(text)
        for p in self.banned_phrases:
            t = t.replace(p, "")
        return self._norm(t)

    def _safe_title(self, row):
        brand = self._s(row.get("brand"))
        skin = self._s(row.get("skin_concern"))
        title = f"{brand} {skin} 피부를 위한 가벼운 케어"
        return self._norm(title)[:40]

    def _finalize_body_length(self, body):
        b = self._norm(body)

        target_min, target_max = 300, 350
        pool = self.pad_pool[:]
        random.shuffle(pool)

        while True:
            L = len(b)

            if target_min <= L <= target_max:
                return b

            if L < target_min:
                if pool:
                    b = self._norm(b + " " + pool.pop())
                else:
                    b = self._norm(b + " 최근 루틴을 편하게 이어가기 좋은 흐름입니다.")
                continue

            if L > target_max:
                b = self._norm(b[:target_max].rstrip(",. "))
                return b

    def _slot_template(self, row):
        g = lambda k: self._s(row.get(k))

        lifestyle = g("lifestyle")
        env = g("environment_context")
        season = g("seasonality")

        skin = g("skin_concern")
        product = g("상품명")
        texture = g("texture_preference")
        finish = g("finish_preference")

        time_of_use = g("time_of_use")
        routine = g("routine_step_count")

        s1 = (
            f"{lifestyle} 환경에서는 {env} 영향이 반복되면서 "
            f"{season} 변화에 따라 피부 컨디션이 쉽게 흔들릴 수 있습니다."
        )

        s2 = (
            f"이런 상황에서는 {product}처럼 "
            f"{texture} 사용감과 {finish} 마무리를 가진 제품이 "
            f"{skin} 고민을 부담 없이 케어하는 데 잘 어울립니다."
        )

        s3 = (
            f"덕분에 {time_of_use} 기준 {routine}단계 루틴에도 "
            f"무리 없이 녹아들어 일상 속에서 활용하기 편합니다."
        )

        s4 = (
            "과하지 않은 흐름으로 구성되어 "
            "관리 텀이 길어졌을 때도 다시 시작하기 어렵지 않습니다."
        )

        body = " ".join([s1, s2, s3, s4])
        body = self._remove_banned(body)

        return self._finalize_body_length(body)

    def generate(self, row: dict, plan: dict, brand_rule: dict, repair_errors=None):
        if not plan or not plan.get("message_outline"):
            raise RuntimeError("plan missing message_outline")

        rule_block = build_brand_rule_block(brand_rule)

        title = self._safe_title(row)
        body = self._slot_template(row)

        url = self._s(row.get("URL"))
        if url:
            body = f"{body} {url}"

        prompt = (
            rule_block
            + "\n"
            + f"TITLE: {title}\n"
            + f"BODY: {body}"
        )

        return prompt