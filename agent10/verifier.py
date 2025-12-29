import re

class MessageVerifier:
    def __init__(self):
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

    def _s(self, v):
        return "" if v is None else str(v).strip()

    def validate(self, row: dict, title_line: str, body_line: str):
        errs = []

        t = self._s(title_line)
        b = self._s(body_line)

        if not t.startswith("TITLE:"):
            errs.append("title_format")
        if not b.startswith("BODY:"):
            errs.append("body_format")

        title = t.replace("TITLE:", "", 1).strip()
        body = b.replace("BODY:", "", 1).strip()

        if not title:
            errs.append("title_empty")
        if len(title) > 40:
            errs.append("title_len>40")

        if len(body) < 300:
            errs.append("body_len<300")
        if len(body) > 350:
            errs.append("body_len>350")

        url = self._s(row.get("URL"))
        if url:
            c = body.count(url)
            if c == 0:
                errs.append("url_missing")
            if c > 1:
                errs.append("url_multiple")
            if c == 1 and not body.endswith(url):
                errs.append("url_not_last")

        prod = self._s(row.get("상품명"))
        if prod and prod not in body:
            errs.append("product_missing")

        lifestyle = self._s(row.get("lifestyle"))
        if lifestyle and lifestyle not in body:
            errs.append("lifestyle_missing")

        skin = self._s(row.get("skin_concern"))
        if skin and skin not in body:
            errs.append("skin_concern_missing")

        for p in self.meta_ban:
            if p and p in body:
                errs.append(f"meta_phrase:{p}")

        if re.search(r"\[.*?\]\(https?://", body):
            errs.append("markdown_link_banned")

        return errs