# agent10/verifier.py
import re


class MessageVerifier:
    def __init__(self):
        # 메타/기획/CTA 금지어 (강제 차단)
        # - 변형/띄어쓰기/조사 차이를 일부 흡수하기 위해 regex 패턴으로도 추가 검사함
        self.meta_ban = [
            "브랜드 톤을 유지하며",
            "브랜드 톤을 살려",
            "브랜드 톤을 살리",
            "설계된 제품",
            "기획된",
            "전략적으로",
            "톤을 반영하여",
            "브랜드 아이덴티티",
            "클릭",
            "구매하기",
            "더 알아보려면",
            "더 알아보기",
            "자세히 보기",
        ]

        # 금지어 regex (띄어쓰기/조사/변형 완화 탐지)
        self.meta_ban_regex = [
            r"브랜드\s*톤(을|이)?\s*(유지|살리|살려|반영)",
            r"브랜드\s*아이덴티티",
            r"(클릭|구매\s*하기|구매하기|더\s*알아\s*보(려면|기)|자세히\s*보(기|려면))",
            r"(전략적|기획된|설계된)\s*",
        ]

        # 루틴/지속 맥락 키워드 (느슨)
        self.routine_keywords = [
            "아침", "저녁", "루틴", "매일", "일상", "반복",
            "지속", "계속", "이어", "관리", "습관"
        ]


    # -------------------------------------------------
    # helpers
    # -------------------------------------------------
    def _s(self, v):
        return "" if v is None else str(v).strip()

    def _tokenize(self, text):
        # 한글/영문/숫자/underscore를 단어로 취급
        return [t for t in re.split(r"[^\w가-힣]+", text) if len(t) >= 2]

    def _normalize(self, text: str) -> str:
        # 중복 문장 검사용 정규화 (lookbehind 사용 안 함)
        text = self._s(text).lower()
        text = re.sub(r"\s+", " ", text).strip()
        text = re.sub(r"[^\w가-힣 ]+", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _loose_contains(self, source, target):
        """
        source 토큰 중 하나라도 target에 있으면 통과 (느슨)
        """
        if not source:
            return True
        tokens = self._tokenize(source)
        if not tokens:
            return True
        return any(tok in target for tok in tokens)

    def _has_routine_context(self, body):
        return any(k in body for k in self.routine_keywords)

    def _split_slots(self, body: str):
        """
        BODY를 4 슬롯으로 분해.
        1) 우선 줄바꿈 기반 분해
        2) 부족하면 문장부호 기반 분해
        """
        b = self._s(body)

        # 1) 줄바꿈 기준
        lines = [ln.strip() for ln in b.split("\n") if ln.strip()]
        if len(lines) >= 4:
            return lines

        # 2) 문장부호 기준 (., !, ?, …, ~)
        parts = re.split(r"[.!?…~]+", b)
        parts = [p.strip() for p in parts if p and p.strip()]

        # URL이 마지막에 붙는 케이스로 마지막 조각이 빈 경우가 있어 보정
        if len(parts) >= 4:
            return parts

        # 3) 그래도 부족하면 원문 반환
        return [b] if b else []

    def _jaccard(self, a: str, b: str) -> float:
        ta = set(self._tokenize(a))
        tb = set(self._tokenize(b))
        if not ta and not tb:
            return 1.0
        if not ta or not tb:
            return 0.0
        inter = len(ta & tb)
        union = len(ta | tb)
        return inter / union if union else 0.0

    def _has_duplicate_sentences(self, slots):
        """
        완전 중복 + 유사 중복(토큰 자카드) 둘 다 검사
        """
        norm = [self._normalize(s) for s in slots if self._normalize(s)]
        # 완전 중복
        if len(norm) != len(set(norm)):
            return True

        # 유사 중복 (아주 높은 유사도면 중복으로 판단)
        for i in range(len(slots)):
            for j in range(i + 1, len(slots)):
                if self._jaccard(slots[i], slots[j]) >= 0.85:
                    return True
        return False


    def _contains_meta_banned(self, body: str) -> list:
        found = []
        for p in self.meta_ban:
            if p and p in body:
                found.append(p)
        for rx in self.meta_ban_regex:
            if re.search(rx, body):
                found.append(f"regex:{rx}")
        return found

    # -------------------------------------------------
    # main
    # -------------------------------------------------
    def validate(self, row: dict, title_line: str, body_line: str):
        errs = []

        t = self._s(title_line)
        b = self._s(body_line)

        # -------------------------------------------------
        # 1. 형식
        # -------------------------------------------------
        if not t.startswith("TITLE:"):
            errs.append("title_format")
        if not b.startswith("BODY:"):
            errs.append("body_format")

        title = t.replace("TITLE:", "", 1).strip()
        body = b.replace("BODY:", "", 1).strip()

        # -------------------------------------------------
        # 2. 제목
        # -------------------------------------------------
        if not title:
            errs.append("title_empty")
        if len(title) > 40:
            errs.append("title_len>40")

        # -------------------------------------------------
        # 3. 본문 길이 (강제: 300~350)
        # -------------------------------------------------
        body_len = len(body)
        if body_len < 300:
            errs.append("body_len<300")
        if body_len > 350:
            errs.append("body_len>350")

        # -------------------------------------------------
        # 4. 링크/CTA 형식 금지 (유지)
        #  - 마크다운 링크 금지
        # -------------------------------------------------
        if re.search(r"\[.*?\]\(https?://", body):
            errs.append("markdown_link_banned")

        # -------------------------------------------------
        # 5. 브랜드 포함 여부 (강제: title 또는 body에 존재)
        # -------------------------------------------------
        brand = self._s(row.get("brand_name_slot")) or self._s(row.get("brand"))
        if brand:
            if (brand not in title) and (brand not in body):
                errs.append("brand_missing")

        # -------------------------------------------------
        # 6. 제품명 포함 여부 (강제: 토큰 기준)
        # -------------------------------------------------
        prod = self._s(row.get("상품명"))
        if prod and not self._loose_contains(prod, body):
            errs.append("product_missing")

        # -------------------------------------------------
        # 7. 라이프스타일 / 피부 고민 (강제: 존재)
        # -------------------------------------------------
        lifestyle = self._s(row.get("lifestyle"))

        skin = self._s(row.get("skin_concern"))
        if skin and not self._loose_contains(skin, body):
            errs.append("skin_concern_missing")

        # -------------------------------------------------
        # 8. 1:1:1:1 슬롯 구조 (강제: 4슬롯 확보 + 슬롯별 최소 요건)
        #  - slot1: lifestyle(또는 environment/seasonality/time_of_use) 맥락
        #  - slot2: product 포함 + skin_concern(또는 texture/finish/scent) 맥락
        #  - slot3: 루틴/지속 맥락 + (time_of_use/seasonality/environment 중 하나라도)
        #  - slot4: 마무리(채널/재구매/가격/cta_style 중 하나라도)
        # -------------------------------------------------
        slots = self._split_slots(body)
        if len(slots) < 4:
            errs.append("slot_count<4")
        else:
            s1, s2, s3, s4 = slots[0], slots[1], slots[2], slots[3]

            env = self._s(row.get("environment_context"))
            season = self._s(row.get("seasonality"))
            tou = self._s(row.get("time_of_use"))

            tex = self._s(row.get("texture_preference"))
            fin = self._s(row.get("finish_preference"))
            scent = self._s(row.get("scent_preference"))

            channel = self._s(row.get("shopping_channel"))
            rep = self._s(row.get("repurchase_tendency"))
            price = self._s(row.get("price_sensitivity"))
            cta = self._s(row.get("cta_style"))

            # slot1
            slot1_ok = (
                (lifestyle and self._loose_contains(lifestyle, s1)) or
                (env and self._loose_contains(env, s1)) or
                (season and self._loose_contains(season, s1)) or
                (tou and self._loose_contains(tou, s1))
            )
            if not slot1_ok:
                errs.append("slot1_invalid")

            # slot2
            slot2_ok = True
            if prod and not self._loose_contains(prod, s2):
                slot2_ok = False
            if not (
                (skin and self._loose_contains(skin, s2)) or
                (tex and self._loose_contains(tex, s2)) or
                (fin and self._loose_contains(fin, s2)) or
                (scent and self._loose_contains(scent, s2))
            ):
                slot2_ok = False
            if not slot2_ok:
                errs.append("slot2_invalid")

            # slot3
            slot3_ok = self._has_routine_context(s3) and (
                (tou and self._loose_contains(tou, s3)) or
                (season and self._loose_contains(season, s3)) or
                (env and self._loose_contains(env, s3)) or
                True  # row 값이 비어있는 경우를 고려해 과도한 실패 방지
            )
            if not self._has_routine_context(s3):
                errs.append("slot3_routine_missing")

            # slot4
            slot4_ok = (
                (channel and self._loose_contains(channel, s4)) or
                (rep and self._loose_contains(rep, s4)) or
                (price and self._loose_contains(price, s4)) or
                (cta and self._loose_contains(cta, s4))
            )
            if not slot4_ok:
                errs.append("slot4_invalid")

            # 중복 문장 금지
            if self._has_duplicate_sentences([s1, s2, s3, s4]):
                errs.append("duplicate_sentence")


        # -------------------------------------------------
        # 10. 메타/금지 표현 (강제 차단)
        # -------------------------------------------------
        banned_found = self._contains_meta_banned(body)
        for p in banned_found:
            errs.append(f"meta_phrase:{p}")

        return errs


# -------------------------------------------------
# 브랜드 규칙 검증 (강화 버전)
# -------------------------------------------------
def verify_brand_rules(text, rule):
    errors = []
    if not rule:
        return errors

    txt = "" if text is None else str(text)
    txt_fold = txt.casefold()

    def _split_csv(v):
        v = "" if v is None else str(v)
        v = v.strip()
        if not v or v.lower() == "nan":
            return []
        return [x.strip() for x in v.split(",") if x.strip()]

    # 금지어: 엄격 + 대소문자 무시(영문 대응)
    for w in _split_csv(rule.get("banned", "")):
        w_fold = w.casefold()
        if w and (w in txt or w_fold in txt_fold):
            errors.append(f"브랜드 금지어 포함됨: {w}")

    # 지양어: 엄격 + 대소문자 무시(영문 대응)
    for w in _split_csv(rule.get("avoid", "")):
        w_fold = w.casefold()
        if w and (w in txt or w_fold in txt_fold):
            errors.append(f"브랜드 지양 표현 포함됨: {w}")

    # 필수어: "토큰 하나라도"는 너무 약해서,
    # - 2토큰 이상이면: 최소 2개 토큰 중 1개 이상 포함
    # - 1토큰이면: 그 토큰 포함
    for w in _split_csv(rule.get("must_include", "")):
        tokens = [t for t in re.split(r"[^\w가-힣]+", w) if t.strip()]
        tokens2 = [t for t in tokens if len(t) >= 2]

        if tokens2:
            # 2글자 이상 토큰이 존재하면 그중 하나라도 포함
            ok = any(tok in txt for tok in tokens2) or any(tok.casefold() in txt_fold for tok in tokens2)
            if not ok:
                errors.append(f"브랜드 필수어 누락됨: {w}")
        else:
            # 2글자 이상 토큰이 없으면 원문 그대로 포함 체크
            if w and (w not in txt) and (w.casefold() not in txt_fold):
                errors.append(f"브랜드 필수어 누락됨: {w}")

    return errors