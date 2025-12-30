import re

class MessageVerifier:
    def __init__(self):
        # AI스러운 표현이나 마케팅적으로 어색한 표현들을 걸러내는 리스트
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
        """안전한 문자열 변환"""
        return "" if v is None else str(v).strip()

    def _check_loose_match(self, target_str, body_text):
        """
        [유연한 검사] 
        문자열이 완벽하게 일치하지 않아도, 쉼표(,)로 구분된 키워드 중 하나라도 있으면 통과시킵니다.
        예: "출근 전 5분 루틴, 사무실 에어컨" -> 본문에 "사무실 에어컨"만 있어도 OK
        """
        if not target_str:
            return True # 검사할 게 없으면 통과
            
        # 1. 전체가 통으로 들어있으면 통과
        if target_str in body_text:
            return True
            
        # 2. 쉼표로 나눠서 하나라도 들어있으면 통과 (부분 점수 인정)
        keywords = [k.strip() for k in target_str.split(',') if k.strip()]
        for k in keywords:
            if k in body_text:
                return True
                
        return False

    def validate(self, row: dict, title_line: str, body_line: str):
        errs = []

        t = self._s(title_line)
        b = self._s(body_line)

        # 1. 형식 체크
        if not t.startswith("TITLE:"):
            errs.append("title_format")
        if not b.startswith("BODY:"):
            errs.append("body_format")

        title = t.replace("TITLE:", "", 1).strip()
        body = b.replace("BODY:", "", 1).strip()

        # 2. 제목 길이 체크
        if not title:
            errs.append("title_empty")
        if len(title) > 40:
            errs.append("title_len>40")

        # 3. 본문 길이 체크 (범위 완화: 200~450자)
        # 너무 엄격하면(300~350) 내용이 좋은데도 에러가 나서 재시도를 많이 하게 됩니다.
        if len(body) < 200:
            errs.append("body_len<200")
        if len(body) > 450:
            errs.append("body_len>450")

        # 4. URL 위치 및 개수 체크
        url = self._s(row.get("URL"))
        if url:
            # URL이 http로 시작하는지 확인해서 잘라내기 (파라미터 등 변형 대비)
            simple_url = url.split('?')[0] if '?' in url else url
            
            if simple_url not in body and url not in body:
                errs.append("url_missing")
            
            # URL 개수 체크 (1개 초과면 에러)
            if body.count("http") > 1:
                errs.append("url_multiple")

            # URL이 맨 뒤에 있는지 체크 (약간의 오차 허용)
            # 본문 뒤에서 100자 이내에 URL이 있으면 인정 (마지막에 점(.)이 찍히거나 공백이 있어도 OK)
            last_idx = body.rfind("http")
            if last_idx != -1:
                if len(body) - last_idx > len(url) + 50: 
                    errs.append("url_not_last")

        # 5. 필수 키워드 포함 여부 (유연한 검사 적용)
        prod = self._s(row.get("상품명"))
        # [수정] 상품명에서 "30ml", "1+1" 같은 불필요한 스펙 제거 후 검사
        # 예: "나이아시카 크림 30ml" -> "나이아시카 크림"만 본문에 있어도 인정
        prod_clean = re.sub(r'\d+(ml|g|ea|매).*', '', prod).strip()
        
        if prod_clean and prod_clean not in body:
             # 그래도 없으면 원본으로 한 번 더 체크
             if prod not in body:
                 errs.append("product_missing")

        # [수정] 라이프스타일, 피부고민은 하나만 맞아도 인정
        lifestyle = self._s(row.get("lifestyle"))
        if not self._check_loose_match(lifestyle, body):
            errs.append("lifestyle_missing")

        skin = self._s(row.get("skin_concern"))
        if not self._check_loose_match(skin, body):
            errs.append("skin_concern_missing")

        # 6. 금지어(Meta Ban) 체크
        for p in self.meta_ban:
            if p and p in body:
                errs.append(f"meta_phrase:{p}")

        # 7. 마크다운 링크 금지 ([...](http...))
        if re.search(r"\[.*?\]\(https?://", body):
            errs.append("markdown_link_banned")

        return errs


# Controller에서 호출하는 독립 함수
def verify_brand_rules(text, rule):
    """
    브랜드별 규칙 검증 (유연한 매칭 적용)
    """
    errors = []
    if not rule:
        return errors

    # 1. 금지어(Banned) 체크 - 이건 엄격하게 유지
    banned_str = str(rule.get("banned", ""))
    if banned_str and banned_str.lower() != "nan":
        for word in banned_str.split(","):
            w = word.strip()
            if w and w in text:
                errors.append(f"브랜드 금지어 포함됨: {w}")

    # 2. 필수어(Must Include) 체크 - 유연하게 (단어가 포함만 되면 OK)
    must_str = str(rule.get("must_include", ""))
    if must_str and must_str.lower() != "nan":
        for word in must_str.split(","):
            w = word.strip()
            if not w: continue
            
            # [수정] 한국어 어미 변화 고려 (앞 2글자만 맞으면 통과)
            # 예: 룰이 "지속 가능성"이어도 본문에 "지속 가능한"이 있으면 통과
            if len(w) >= 2:
                check_w = w[:2]
            else:
                check_w = w
                
            if check_w not in text:
                errors.append(f"브랜드 필수어 누락됨: {w}")

    # 3. 지양할 표현(Avoid) 체크
    avoid_str = str(rule.get("avoid", ""))
    if avoid_str and avoid_str.lower() != "nan":
        for word in avoid_str.split(","):
            w = word.strip()
            if w and w in text:
                errors.append(f"브랜드 지양 표현 포함됨: {w}")

    return errors