# agent10/verifier.py
import re


class MessageVerifier:
    def __init__(self):
        # 메타/기획/CTA 금지어 (강제 차단)
        self.meta_ban = [
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
        ]

        # 루틴/지속 맥락 키워드 (느슨)
        self.routine_keywords = [
            "아침", "저녁", "루틴", "매일", "일상", "반복",
            "지속", "계속", "이어", "관리"
        ]

    # -------------------------------------------------
    # helpers
    # -------------------------------------------------
    def _s(self, v):
        return "" if v is None else str(v).strip()

    def _tokenize(self, text):
        return [t for t in re.split(r"[^\w가-힣]+", text) if len(t) >= 2]

    def _loose_contains(self, source, target):
        """
        source 토큰 중 하나라도 target에 있으면 통과
        """
        if not source:
            return True
        tokens = self._tokenize(source)
        if not tokens:
            return True
        return any(tok in target for tok in tokens)

    def _has_routine_context(self, body):
        return any(k in body for k in self.routine_keywords)

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
        # 3. 본문 길이 (완화)
        # -------------------------------------------------
        if len(body) < 200:
            errs.append("body_len<200")
        if len(body) > 450:
            errs.append("body_len>450")

        # -------------------------------------------------
        # 4. 브랜드 포함 여부 (느슨)
        # -------------------------------------------------
        brand = self._s(row.get("brand_name_slot")) or self._s(row.get("brand"))
        if brand and brand not in body:
            errs.append("brand_missing")

        # -------------------------------------------------
        # 5. 제품명 포함 여부 (토큰 기준)
        # -------------------------------------------------
        prod = self._s(row.get("상품명"))
        if prod and not self._loose_contains(prod, body):
            errs.append("product_missing")

        # -------------------------------------------------
        # 6. 라이프스타일 / 피부 고민 (존재 여부만)
        # -------------------------------------------------
        lifestyle = self._s(row.get("lifestyle"))
        if lifestyle and not self._loose_contains(lifestyle, body):
            errs.append("lifestyle_missing")

        skin = self._s(row.get("skin_concern"))
        if skin and not self._loose_contains(skin, body):
            errs.append("skin_concern_missing")

        # -------------------------------------------------
        # 7. 루틴/지속 맥락 (의미 유사 허용)
        # -------------------------------------------------
        if not self._has_routine_context(body):
            errs.append("routine_context_missing")

        # -------------------------------------------------
        # 8. 메타/금지 표현 (강제 차단)
        # -------------------------------------------------
        for p in self.meta_ban:
            if p and p in body:
                errs.append(f"meta_phrase:{p}")

        # -------------------------------------------------
        # 9. 마크다운 링크 금지
        # -------------------------------------------------
        if re.search(r"\[.*?\]\(https?://", body):
            errs.append("markdown_link_banned")

        return errs


# -------------------------------------------------
# 브랜드 규칙 검증 (완화 버전)
# -------------------------------------------------
def verify_brand_rules(text, rule):
    errors = []
    if not rule:
        return errors

    # 금지어: 그대로 엄격
    banned = str(rule.get("banned", ""))
    if banned and banned.lower() != "nan":
        for w in banned.split(","):
            w = w.strip()
            if w and w in text:
                errors.append(f"브랜드 금지어 포함됨: {w}")

    # 필수어: 토큰 하나라도 있으면 통과
    must = str(rule.get("must_include", ""))
    if must and must.lower() != "nan":
        for w in must.split(","):
            w = w.strip()
            if not w:
                continue
            tokens = [t for t in re.split(r"[^\w가-힣]+", w) if len(t) >= 2]
            if tokens and not any(tok in text for tok in tokens):
                errors.append(f"브랜드 필수어 누락됨: {w}")

    # 지양어: 그대로 차단
    avoid = str(rule.get("avoid", ""))
    if avoid and avoid.lower() != "nan":
        for w in avoid.split(","):
            w = w.strip()
            if w and w in text:
                errors.append(f"브랜드 지양 표현 포함됨: {w}")

    return errors