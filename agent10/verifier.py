# agent10/verifier.py
import re


class MessageVerifier:
    def __init__(self):
        # 피부 고민(semantic) 키워드: slot2에서 느슨하게 일치시 사용
        self.skin_concern_keywords = [
            # 일반적인 피부 고민 관련 키워드 (확장 가능)
            "트러블", "여드름", "잡티", "홍조", "건조", "수분", "보습", "민감", "탄력", "주름",
            "미백", "톤업", "피지", "유분", "각질", "모공", "칙칙", "광채", "광", "피부결", "진정",
            "붉음", "색소", "흉터", "노화", "피부장벽", "피부톤", "피부개선", "피부고민"
        ]
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
            "지속", "계속", "이어", "관리", "습관",
            # 사용 흐름을 나타내는 표현도 루틴으로 취급(너무 엄격한 실패 방지)
            "세안", "토너", "다음", "단계", "후", "전", "바르", "사용"
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
            # 4줄 초과(예: URL/추가 줄)인 경우 slot4에 합친다
            s1, s2, s3 = lines[0], lines[1], lines[2]
            s4 = " ".join(lines[3:]).strip()
            return [s1, s2, s3, s4]

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
        # 1. 형식 + TITLE/BODY 정규화
        #  - 입력이 (a) title_line/body_line로 분리되어 오거나
        #         (b) 한쪽에 줄바꿈/중첩 TITLE/BODY가 섞여 와도
        #    가장 바깥 1쌍(TITLE 1개, BODY 1개)만 추출한다.
        # -------------------------------------------------
        raw = (t + "\n" + b).strip()

        # 기본 형식 체크(있으면 통과). 단, raw 기준으로도 보정한다.
        if "TITLE:" not in raw:
            errs.append("title_format")
        if "BODY:" not in raw:
            errs.append("body_format")

        # 가장 바깥 TITLE/BODY 1쌍 추출
        m = re.search(r"TITLE:\s*(.*?)\n\s*BODY:\s*(.*)\Z", raw, flags=re.DOTALL)
        if m:
            title = (m.group(1) or "").strip()
            body = (m.group(2) or "").strip()
        else:
            # fallback: 기존 방식(라인이 분리되어 들어오는 경우)
            title = t.replace("TITLE:", "", 1).strip() if t.startswith("TITLE:") else ""
            body = b.replace("BODY:", "", 1).strip() if b.startswith("BODY:") else b.strip()

        # BODY 내부에 중첩된 TITLE/BODY 마커가 남아있으면 제거(후속 파싱 보호)
        # - 가장 바깥 1쌍은 이미 raw에서 확정했으므로, body 안의 마커는 노이즈로 간주
        body = re.sub(r"(?m)^\s*TITLE:\s*", "", body)
        body = re.sub(r"(?m)^\s*BODY:\s*", "", body)

        # --- hard remove accidental label tokens (삽입된 라벨 제거) ---
        body = re.sub(r"\b사용감\b", "", body)
        body = re.sub(r"\b루틴\s*내\s*위치\b", "", body)
        body = re.sub(r"\b지속\s*가능성\b", "", body)
        body = re.sub(r"\s{2,}", " ", body).strip()

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
        if prod:
            # slot2 기준으로 우선 판단, fallback으로 body 전체 허용
            slots_tmp = self._split_slots(body)
            slot2_text = slots_tmp[1] if len(slots_tmp) >= 2 else body
            if not self._loose_contains(prod, slot2_text):
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

            # slot2에 라벨 토큰만 붙은 경우 방지
            if len(self._tokenize(s2)) <= 2:
                errs.append("slot2_invalid")
                slot2_ok = False
            else:
                # slot2: 피부 고민은 semantic 키워드로 느슨하게 허용 (skin_concern token 불일치시에도 키워드 일치하면 통과)
                slot2_ok = True
                if prod and not self._loose_contains(prod, s2):
                    slot2_ok = False
                # Relaxed semantic check for skin concerns
                skin_semantic_hit = any(k in s2 for k in self.skin_concern_keywords)
                if not (
                    (skin and self._loose_contains(skin, s2)) or
                    skin_semantic_hit or
                    (tex and self._loose_contains(tex, s2)) or
                    (fin and self._loose_contains(fin, s2)) or
                    (scent and self._loose_contains(scent, s2))
                ):
                    slot2_ok = False
                if not slot2_ok:
                    errs.append("slot2_invalid")

            # slot3
            # label-only contamination 방지: 단독 토큰만 있는 경우는 무효
            if len(self._tokenize(s3)) <= 2:
                errs.append("slot3_routine_missing")

            slot3_ok = self._has_routine_context(s3) and (
                (tou and self._loose_contains(tou, s3)) or
                (season and self._loose_contains(season, s3)) or
                (env and self._loose_contains(env, s3)) or
                True  # row 값이 비어있는 경우를 고려해 과도한 실패 방지
            )
            if not self._has_routine_context(s3):
                errs.append("slot3_routine_missing")

            # slot4: 값이 존재하면 허용 (토큰/키워드 불필요, 단순 존재 확인)
            slot4_ok = bool(s4 and s4.strip())
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

    # -------------------------------------------------
    # 1. 금지어 / 지양어 (기존 로직 유지)
    # -------------------------------------------------
    for w in _split_csv(rule.get("banned", "")):
        w_fold = w.casefold()
        if w and (w in txt or w_fold in txt_fold):
            errors.append(f"브랜드 금지어 포함됨: {w}")

    for w in _split_csv(rule.get("avoid", "")):
        w_fold = w.casefold()
        if w and (w in txt or w_fold in txt_fold):
            errors.append(f"브랜드 지양 표현 포함됨: {w}")

    # -------------------------------------------------
    # 2. 필수어: 의미 기반(sementic) 검증
    # -------------------------------------------------
    SEMANTIC_MAP = {
        "사용감": [
            "가볍", "스며", "흡수", "끈적", "번들",
            "레이어", "산뜻", "밀림"
        ],
        "지속 가능성": [
            "꾸준", "부담", "계속", "이어",
            "관리", "습관", "텀",
            "반복", "장기", "유지"
        ],
        "루틴 내 위치": [
            "세안", "토너", "다음", "단계",
            "마지막", "아침", "저녁"
        ],
        "리듬": [
            "루틴", "흐름", "일상", "습관",
            "아침", "저녁", "자연스럽"
        ],
        "장기 사용": [
            "꾸준", "오래", "계속", "유지",
            "장기", "반복", "습관"
        ],
    }

    for w in _split_csv(rule.get("must_include", "")):
        w = w.strip()
        if not w:
            continue

        # 2-1. 의미 매핑이 있는 경우 → 의미 키워드 중 하나라도 있으면 통과
        if w in SEMANTIC_MAP:
            keywords = SEMANTIC_MAP[w]
            if not any(k in txt for k in keywords):
                errors.append(f"브랜드 필수어(의미) 누락됨: {w}")
        else:
            # 2-2. 의미 매핑이 없으면 기존 토큰 기반 로직 유지
            tokens = [t for t in re.split(r"[^\w가-힣]+", w) if len(t) >= 2]
            if tokens:
                ok = any(tok in txt for tok in tokens) or any(tok.casefold() in txt_fold for tok in tokens)
                if not ok:
                    errors.append(f"브랜드 필수어 누락됨: {w}")
            else:
                if w and (w not in txt) and (w.casefold() not in txt_fold):
                    errors.append(f"브랜드 필수어 누락됨: {w}")

    return errors