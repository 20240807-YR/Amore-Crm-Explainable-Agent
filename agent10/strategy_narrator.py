# agent10/strategy_narrator.py
import re
from typing import Any, Dict, List, Optional, Tuple


class StrategyNarrator:
    """
    - plan(message_outline) 없으면 generate 실행 금지
    - BODY는 1:1:1:1 슬롯(4줄) 강제: 라이프스타일 → 제품 → 라이프스타일(루틴) → 추가 메시지(구매 텀/채널/혜택)
    - BODY 300~350자, URL 정확히 1회(마지막), 마크다운 링크 금지
    - 메타/기획/전략 표현 금지
    """

    def __init__(
        self,
        llm_client,
        pad_pool: Optional[List[str]] = None,
        tone_profile_map: Optional[Dict[str, Any]] = None,
        **kwargs,
    ):
        self.llm = llm_client
        self.tone_profile_map = tone_profile_map or {}
        self.pad_pool = pad_pool or [
            "오늘 컨디션에 맞춰 가볍게 얹기 좋아요.",
            "부담 없이 매일 이어가기 편해요.",
            "끈적임이 덜해 손이 자주 가요.",
            "바쁠수록 짧게 정리되는 루틴이 편하죠.",
            "가볍게 마무리돼 다음 단계가 수월해요.",
        ]

        # meta/기획/CTA 금지(강제)
        self.meta_ban_phrases = [
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
            # 문제로 지적된 어색한 종결문(직접 차단)
            "지속 가능성 측면에서도 부담 없이 이어갈 수",
            "이 과정에서 루틴 내 위치, 지속 가능성 측면에서도",
            "있다",
        ]
        self.meta_ban_regex = [
            r"브랜드\s*톤(을|이)?\s*(유지|살리|살려|반영)",
            r"(클릭|구매\s*하기|구매하기|더\s*알아\s*보(려면|기)|자세히\s*보(기|려면))",
            r"(전략적|기획된|설계된)\s*",
            r"지속\s*가능성\s*측면",
            r"(이다|있다)$",
        ]

    # -------------------------
    # utils
    # -------------------------
    def _s(self, v: Any) -> str:
        return "" if v is None else str(v).strip()

    def _get_url(self, row: Dict[str, Any]) -> str:
        for k in ["url", "URL", "product_url", "productURL", "상품URL", "상품_url", "link", "링크"]:
            v = self._s(row.get(k))
            if v and v.lower() != "nan":
                return v
        return ""

    def _strip_markdown_link(self, text: str) -> str:
        return re.sub(r"\[([^\]]+)\]\(https?://[^\)]+\)", r"\1", text)

    def _contains_banned(self, text: str) -> bool:
        if not text:
            return False
        for p in self.meta_ban_phrases:
            if p and p in text:
                return True
        for rx in self.meta_ban_regex:
            if re.search(rx, text):
                return True
        return False

    def _hard_clean(self, text: str) -> str:
        t = self._s(text)
        t = self._strip_markdown_link(t)
        t = re.sub(r"https?://[^\s]+", "", t, flags=re.IGNORECASE)
        t = re.sub(r"\s+", " ", t).strip()
        return t

    def _ensure_title_len(self, title: str) -> str:
        title = self._s(title)
        if len(title) <= 40:
            return title
        return title[:40].rstrip()

    def _split_4lines(self, body: str) -> List[str]:
        lines = [ln.strip() for ln in self._s(body).split("\n") if ln.strip()]
        if len(lines) >= 4:
            return lines[:4]
        parts = re.split(r"[.!?…~]+", self._s(body))
        parts = [p.strip() for p in parts if p and p.strip()]
        if len(parts) >= 4:
            return parts[:4]
        while len(lines) < 4:
            lines.append("")
        if not lines[0]:
            lines[0] = self._s(body)
        return lines[:4]

    def _join_4lines(self, lines: List[str]) -> str:
        lines = [self._s(x) for x in lines[:4]]
        # 4문단(4줄) 구조를 깨지지 않게 유지 (빈 줄도 보존)
        while len(lines) < 4:
            lines.append("")
        return "\n".join(lines[:4])

    def _fit_len_300_350(self, lines: List[str]) -> Tuple[List[str], str]:
        # 1) 4줄 고정 + 클린
        lines = [self._hard_clean(x) for x in (lines[:4] if lines else [])]
        while len(lines) < 4:
            lines.append("")

        # 2) 빈 문단 채우기 (4문단 유지)
        pad_pool = [self._s(x) for x in (self.pad_pool or []) if self._s(x)]
        if not pad_pool:
            pad_pool = [
                "오늘 컨디션에 맞춰 가볍게 얹기 좋아요.",
                "부담 없이 매일 이어가기 편해요.",
                "가볍게 마무리돼 다음 단계가 수월해요.",
                "바쁠수록 짧게 정리되는 루틴이 편하죠.",
            ]
        pi = 0
        for i in range(4):
            if not self._s(lines[i]):
                lines[i] = pad_pool[pi % len(pad_pool)]
                pi += 1

        # 3) 기본 바디 생성 (줄바꿈 유지)
        final_body = self._join_4lines(lines).rstrip()
        final_body = re.sub(r"[\s\)\]\}.,!?:;…~]+$", "", final_body)

        # 4) 300 미만이면 4번째 문단에 padding 추가 (결정론적)
        safety = 0
        while len(final_body) < 300 and safety < 80:
            add = pad_pool[pi % len(pad_pool)]
            pi += 1
            if add and add not in lines[3]:
                lines[3] = (self._s(lines[3]) + " " + add).strip()
                lines[3] = self._hard_clean(lines[3])
                final_body = self._join_4lines(lines).rstrip()
                final_body = re.sub(r"[\s\)\]\}.,!?:;…~]+$", "", final_body)
            else:
                # 중복이면 짧은 고정 문장으로 채움
                lines[3] = (self._s(lines[3]) + " 오늘도 가볍게 수분을 챙겨요.").strip()
                lines[3] = self._hard_clean(lines[3])
                final_body = self._join_4lines(lines).rstrip()
                final_body = re.sub(r"[\s\)\]\}.,!?:;…~]+$", "", final_body)
            safety += 1

        # 5) 350 초과 정책: 문장 단위 컷
        if len(final_body) > 350:
            # slot4 전체 제거
            lines = [self._s(x) for x in lines[:3]] + [""]
            final_body = self._join_4lines(lines).rstrip()
            final_body = re.sub(r"[\s\)\]\}.,!?:;…~]+$", "", final_body)

        # 6) 그래도 초과면 전체 discard
        if len(final_body) > 350:
            return [], ""

        return lines, final_body

    def _ensure_len_300_350(self, body: str) -> str:
        """
        Compatibility wrapper.
        generate() expects _ensure_len_300_350, but legacy logic uses _fit_len_300_350.
        This method adapts the existing implementation without changing behavior.
        """
        lines = self._split_4lines(body)
        _, final_body = self._fit_len_300_350(lines)
        return final_body

    # -------------------------
    # prompt builders
    # -------------------------
    def _build_system_prompt(self, brand_name: str) -> str:
        """
        시스템 프롬프트: STRICT SLOT-ONLY, TITLE/BODY 예시·라벨·구조 금지
        """
        return f"""당신은 {brand_name}의 전문 마케팅 카피라이터입니다.

[중요]
- 당신의 출력은 **오직 4개의 슬롯 문장만** 허용됩니다.
- TITLE, BODY, 제목, 본문, 사용감, 루틴 내 위치, 지속 가능성 같은 라벨 단어를 절대 쓰지 마세요.

[출력 형식 — 반드시 이 형식만 사용]
slot1_text: 라이프스타일/환경 공감 문장 1~2개
slot2_text: 피부 고민 + 제품(상품명 포함) 설명 문장 1~2개
slot3_text: 사용 순서/시간대/단계가 드러나는 루틴 문장 1~2개
slot4_text: 꾸준함/관리 주기/부담 없는 마무리 문장 1~2개

[문체]
- 반드시 해요체만 사용
- '~이다/~한다/~있다/~합니다' 금지

[금지]
- TITLE/BODY/slot 라벨 외 다른 형식 금지
- 링크/URL/CTA 문구 금지

[의미 지시 — 단어 그대로 사용 금지]
- '사용감'이라는 단어를 쓰지 말고, 발림/흡수/가벼움/끈적임 없음의 의미로 표현하세요.
- '루틴 내 위치'라는 단어를 쓰지 말고, 세안 후/토너 다음/아침·저녁 루틴 등의 의미로 표현하세요.
- '지속 가능성'이라는 단어를 쓰지 말고, 매일 부담 없음/꾸준히 쓰기 쉬움/관리 주기의 의미로 표현하세요.
"""

    def _build_user_prompt(
        self,
        row: Dict[str, Any],
        plan: Dict[str, Any],
        brand_rule: Dict[str, Any],
        repair_errors: Optional[List[str]] = None,
    ) -> str:
        brand_name = self._s(row.get("brand", ""))
        product_name = self._s(row.get("상품명", "제품"))
        
        must_include = plan.get("brand_must_include", [])
        must_str = ", ".join(must_include) if must_include else "없음"

        # 브랜드 규칙 병합
        rule_text = ""
        banned = self._s(brand_rule.get("banned", ""))
        avoid = self._s(brand_rule.get("avoid", ""))
        if banned:
            rule_text += f"- 절대 금지어: {banned}\n"
        if avoid:
            rule_text += f"- 지양할 표현: {avoid}\n"

        prompt = f"""
[고객 정보]
- 상황(Lifestyle): {plan.get('lifestyle_expanded', row.get('lifestyle', ''))}
- 피부 고민: {self._s(row.get('skin_concern', ''))}
- 추천 제품: {product_name}
- 필수 포함 키워드: {must_str} (문장 속에 자연스럽게 녹여내세요)
{rule_text}
[요청 사항]
위 정보를 바탕으로 {brand_name}의 톤앤매너에 맞는 매력적인 메시지를 작성해 주세요.
반드시 시스템 지시의 slot1_text~slot4_text 형식만 따르세요. TITLE/BODY 같은 라벨은 절대 쓰지 마세요.
"""
        if repair_errors:
            prompt += f"\n[수정 요청] 이전 생성 결과에 다음 문제가 있었습니다. 이를 반영하여 수정하세요: {', '.join(repair_errors)}"

        return prompt

    def _build_user_prompt_free(
        self,
        row: Dict[str, Any],
        plan: Dict[str, Any],
        brand_rule: Dict[str, Any],
    ) -> str:
        brand_name = self._s(row.get("brand", ""))
        product_name = self._s(row.get("상품명", "제품"))

        prompt = f"""
[작성 지시]
아래 정보를 참고하여 {brand_name}의 마케팅 메시지를 자유롭게 작성하세요.

- 길이: 공백 포함 600~1000자
- 구조 제한 없음
- 설명/분석/자기소개 금지
- 고객에게 직접 말 거는 어조 유지
- 브랜드/제품/피부 고민/상황을 자연스럽게 포함

[고객 정보]
- 라이프스타일: {row.get('lifestyle', '')}
- 피부 고민: {row.get('skin_concern', '')}
- 추천 제품: {product_name}
"""
        return prompt


    # -------------------------
    # New slot helper prompt builders
    # -------------------------
    def _build_user_prompt_slot_expand(self, free_text: str) -> str:
        """
        Asks LLM to output exactly 4 slots from the given text, no rewriting.
        """
        return (
            "아래 텍스트의 정보를 활용하여 4개의 슬롯을 아래 형식으로 분리해 주세요:\n"
            "SLOT1:\n...\nSLOT2:\n...\nSLOT3:\n...\nSLOT4:\n...\n"
            "\n[규칙]\n"
            "- 반드시 주어진 텍스트의 정보만 사용하세요. 어떤 새로운 표현, 어투, 재구성, 추가 정보도 금지합니다.\n"
            "- 각 슬롯은 1~2문장으로, 원문에서 필요한 부분만 발췌하세요.\n"
            "- 어떠한 경우에도 TITLE/BODY라는 단어, 라벨, 설명은 넣지 마세요.\n"
            "- SLOT1~4 레이블은 반드시 정확히 지키세요.\n"
            "\n[입력 텍스트]\n"
            f"{free_text}\n"
        )

    def _build_user_prompt_slot_summarize(self, slot_text: str, slot_id: int) -> str:
        """
        Summarizes slot text to strict char count, per slot.
        """
        char_rules = {
            1: "60~80자 (환경/상황)",
            2: "80~100자 (피부 고민+제품)",
            3: "70~90자 (루틴/시간대 필수)",
            4: "60~80자 (지속/구매 텀)"
        }
        rule = char_rules.get(slot_id, "70~90자")
        return (
            f"아래 SLOT{slot_id} 내용을 {rule}로 요약해 주세요.\n"
            "- 반드시 원문의 의미만 요약, 재구성/재해석/새로운 정보 추가 금지\n"
            "- SLOT{slot_id}의 핵심 정보만 남기고, 문장/어투/톤을 바꾸지 마세요.\n"
            "- 반드시 한글로, 지정된 글자 수 내에서만 작성하세요.\n"
            "- TITLE/BODY라는 단어 절대 금지\n"
            "\n[SLOT{slot_id}]\n"
            f"{slot_text}\n"
        )

    def _build_user_prompt_title_from_slots(self, slots_text: str) -> str:
        """
        Generate a title using only info NOT directly used in BODY, 25-40 chars, 1-2 emojis, no 설명체/하다체.
        """
        return (
            "아래 4개의 슬롯 정보를 참고하여 제목을 한글 25~40자, 이모지 1~2개(앞/뒤 모두)에 맞춰 작성하세요.\n"
            "- 반드시 BODY에 직접적으로 사용되지 않은 정보/포인트만 활용\n"
            "- 설명체, 하다체, '~이다', '~합니다' 등 금지\n"
            "- 제목에 TITLE/BODY라는 단어는 절대 금지\n"
            "- 반드시 한글로, 자연스럽고 눈길을 끄는 표현만\n"
            "- 이모지는 제목 앞뒤에 1~2개씩 포함\n"
            "\n[슬롯 정보]\n"
            f"{slots_text}\n"
        )

    def generate(
        self,
        row: Dict[str, Any],
        plan: Dict[str, Any],
        brand_rule: Dict[str, Any],
        repair_errors: Optional[List[str]] = None,
    ) -> str:
        brand_name = self._s(row.get("brand", "아모레퍼시픽"))
        product_name = self._s(row.get("상품명", ""))
        skin_concern = self._s(row.get("skin_concern", ""))
        lifestyle = self._s(row.get("lifestyle", ""))

        # -------------------------
        # must_include 의미화 (단어 자체 금지)
        # -------------------------
        must_include = plan.get("brand_must_include", []) or []
        must_include = [self._s(x) for x in must_include if self._s(x)]

        meaning_map = {
            "사용감": "발림/흡수/가벼움/끈적임 적음/레이어링 쉬움의 의미로만",
            "루틴 내 위치": "세안 후/토너 다음/아침·저녁/마지막 단계/3~4단계 중 위치의 의미로만",
            "지속 가능성": "매일 부담 없음/꾸준히/관리 주기/텀이 길어져도 이어가기 쉬움의 의미로만",
        }

        meaning_rules = []
        for k in must_include:
            if k in meaning_map:
                meaning_rules.append(f"- '{k}' 단어는 절대 쓰지 말고 {meaning_map[k]} 표현하세요.")
            else:
                meaning_rules.append(f"- '{k}'는 단어 그대로 쓰지 말고 의미로 자연스럽게 풀어 쓰세요.")
        meaning_rules_text = "\n".join(meaning_rules) if meaning_rules else "- 없음"

        forbidden_tokens = [
            "TITLE", "BODY", "제목", "본문",
            "사용감", "루틴 내 위치", "지속 가능성",
            "slot1_text", "slot2_text", "slot3_text", "slot4_text",
        ]

        routine_markers = ["세안", "토너", "아침", "저녁", "단계", "마지막", "3~4"]

        def _has_forbidden(text: str) -> Optional[str]:
            t = self._s(text)
            for tok in forbidden_tokens:
                if tok and tok in t:
                    return tok
            if self._contains_banned(t):
                return "banned_phrase"
            return None

        def _fallback_slots() -> List[str]:
            l1 = f"{lifestyle}처럼 바쁠 때도 피부 컨디션은 금방 티가 나요. 실내 건조와 마스크 환경이면 더 쉽게 뻑뻑해져요."
            l2 = f"{skin_concern} 고민이 있을 땐 {product_name}로 수분을 빠르게 채워줘요. 가볍게 스며들어 겉은 번들거리지 않게 정돈돼요."
            l3 = "세안 후 토너 다음 단계에서 얇게 펴 발라요. 아침에는 가볍게 한 겹, 저녁에는 필요한 부위만 한 번 더 레이어링해요."
            l4 = "최근 관리 텀이 길어졌더라도 오늘부터 부담 없이 다시 이어가요. 꾸준히 쓰기 쉬워서 루틴이 흔들릴 때도 정리하기 좋아요."
            return [self._hard_clean(l1), self._hard_clean(l2), self._hard_clean(l3), self._hard_clean(l4)]

        def _validate_slots(slots: List[str]) -> None:
            if len(slots) != 4:
                raise ValueError("slot_count<4")

            joined = " ".join(slots)
            leaked = _has_forbidden(joined)
            if leaked:
                raise ValueError(f"forbidden token leaked: {leaked}")

            if any(len(self._s(s)) < 35 for s in slots):
                raise ValueError("slot too short")

            if product_name and product_name not in slots[1]:
                raise ValueError("product missing in slot2")
            if skin_concern and skin_concern not in slots[1]:
                raise ValueError("skin_concern missing in slot2")

            if not any(mk in slots[2] for mk in routine_markers):
                raise ValueError("routine marker missing in slot3")

        last_err = None
        slots: List[str] = []

        for _ in range(3):
            try:
                system_p = (
                    f"당신은 {brand_name}의 전문 마케팅 카피라이터입니다.\n\n"
                    "[중요]\n"
                    "- 출력은 반드시 slot1_text~slot4_text 4줄만 허용합니다.\n"
                    "- 다른 라벨/설명/번호/불릿/빈 줄 금지\n"
                    "- 반드시 해요체만 사용\n"
                    "- '~이다/~한다/~있다/~합니다' 금지\n"
                    "- 링크/URL/클릭/구매하기/더 알아보기 등 CTA 문구 금지\n"
                    "- '사용감','루틴 내 위치','지속 가능성' 단어 자체 금지\n"
                )

                user_p = f"""
[입력]
- 라이프스타일: {lifestyle}
- 피부 고민: {skin_concern}
- 추천 제품(상품명 그대로 포함): {product_name}

[필수 규칙]
- 아래 4줄만 출력하세요
- 각 줄은 1~2문장, 해요체
- slot2_text에는 반드시 제품명 + 피부 고민 포함
- slot3_text에는 사용 순서/시간대/단계 표현 필수
- slot4_text에는 꾸준함/관리 주기/구매 텀 완곡 포함

[brand_must_include 처리]
{meaning_rules_text}

[출력 형식]
slot1_text: ...
slot2_text: ...
slot3_text: ...
slot4_text: ...
""".strip()

                messages = [{"role": "system", "content": system_p}, {"role": "user", "content": user_p}]
                slot_out = self.llm.generate(messages=messages)
                slot_out = self._s(slot_out.get("text", "") if isinstance(slot_out, dict) else slot_out)

                m = re.search(
                    r"slot1_text\s*:\s*(.*?)\n\s*slot2_text\s*:\s*(.*?)\n\s*slot3_text\s*:\s*(.*?)\n\s*slot4_text\s*:\s*(.*)",
                    slot_out,
                    re.DOTALL | re.IGNORECASE,
                )
                if not m:
                    raise ValueError("LLM slot format mismatch")

                raw_slots = [self._s(s) for s in m.groups()]
                slots = [self._hard_clean(s) for s in raw_slots]

                _validate_slots(slots)
                last_err = None
                break

            except Exception as e:
                last_err = e
                slots = []

        if not slots:
            slots = _fallback_slots()
            _validate_slots(slots)

        body = "\n".join(slots).strip()
        body = self._ensure_len_300_350(body)
        if not body:
            slots = _fallback_slots()
            body = self._ensure_len_300_350("\n".join(slots).strip())

        if _has_forbidden(body):
            slots = _fallback_slots()
            body = self._ensure_len_300_350("\n".join(slots).strip())

        lines = [ln for ln in body.split("\n") if ln.strip()]
        if len(lines) != 4:
            slots = _fallback_slots()
            body = self._ensure_len_300_350("\n".join(slots).strip())
            lines = [ln for ln in body.split("\n") if ln.strip()]
            if len(lines) != 4:
                raise ValueError("final body slot count != 4")

        if len(body) < 300 or len(body) > 350:
            slots = _fallback_slots()
            body = self._ensure_len_300_350("\n".join(slots).strip())
            if len(body) < 300 or len(body) > 350:
                raise ValueError("final body length not in 300~350")

        title_prompt = f"""
브랜드: {brand_name}
제품: {product_name}
피부 고민: {skin_concern}
라이프스타일: {lifestyle}

위 정보를 참고해 25~40자 제목을 작성하세요.
- 이모지 1~2개 포함
- BODY 문장 재사용 금지
- 설명체/하다체 금지
""".strip()

        title_messages = [
            {"role": "system", "content": "제목만 한 줄로 작성하세요."},
            {"role": "user", "content": title_prompt},
        ]

        title_out = self.llm.generate(messages=title_messages)
        title = self._ensure_title_25_40_with_emojis(
            self._s(title_out.get("text", "") if isinstance(title_out, dict) else title_out),
            brand_name,
            product_name,
            skin_concern,
            lifestyle,
        )

        return f"TITLE: {title}\nBODY: {body}"
    def _has_emoji(self, s: str) -> bool:
        import re
        if not s:
            return False
        return re.search(r"[\U0001F300-\U0001FAFF]", s) is not None

    def _ensure_title_25_40_with_emojis(self, title: str, brand: str, product: str, skin_concern: str, lifestyle: str) -> str:
        title = self._s(title)
        # Remove any accidental TITLE/BODY prefixes
        title = re.sub(r"^(TITLE\s*:?\s*)", "", title, flags=re.IGNORECASE).strip()
        title = re.sub(r"^(BODY\s*:?\s*)", "", title, flags=re.IGNORECASE).strip()
        # Fallback title if too short/empty
        if len(title) < 10:
            core = f"{brand} {product}".strip()
            topic = skin_concern or "피부 컨디션"
            ctx = lifestyle or "오늘 루틴"
            title = f"{ctx} {topic}, {core}로 정리해요"
        # Enforce length range by trimming first
        if len(title) > 40:
            title = title[:40].rstrip()
        # If still shorter than 25, pad with a natural phrase (no meta)
        if len(title) < 25:
            pad = " 촉촉하게 마무리해요"
            title = (title + pad)[:40].rstrip()
        # Ensure emoji at both ends
        if not self._has_emoji(title[:2]):
            title = "✨" + title
        if not self._has_emoji(title[-2:]):
            title = title + "✨"
        # Re-trim to 40 if emoji pushed it over
        if len(title) > 40:
            title = title[:40].rstrip()
            # keep ending emoji
            if not self._has_emoji(title[-2:]):
                title = title[:-1].rstrip() + "✨"
        # Ensure minimum 25 again (rare edge)
        if len(title) < 25:
            title = (title + " 촉촉 루틴이에요")[:40].rstrip()
            if not self._has_emoji(title[:2]):
                title = "✨" + title
            if not self._has_emoji(title[-2:]):
                title = title + "✨"
            if len(title) > 40:
                title = title[:40].rstrip()
        return title

    def _split_4_paragraphs(self, body: str) -> List[str]:
        lines = [ln.strip() for ln in self._s(body).split("\n") if ln.strip()]
        if len(lines) == 4:
            return lines
        # Try sentence split (simple) then group to 4
        import re
        parts = [p.strip() for p in re.split(r"[.!?…]+", self._s(body)) if p.strip()]
        if len(parts) >= 4:
            return parts[:4]
        # Pad empty
        while len(lines) < 4:
            lines.append("")
        return lines[:4]

    def _validate_generated(self, title: str, body: str, brand: str, product: str) -> List[str]:
        errs: List[str] = []

        t = self._s(title)
        b = self._s(body)

        if len(t) < 25 or len(t) > 40:
            errs.append("title_len_25_40")
        if not (self._has_emoji(t[:2]) and self._has_emoji(t[-2:])):
            errs.append("title_emoji_both_sides")

        # 4 paragraphs
        lines = [ln for ln in b.split("\n") if ln.strip()]
        if len(lines) != 4:
            errs.append("slot_count_4")

        # length 300~350 (spaces included)
        if len(b) < 300 or len(b) > 350:
            errs.append("body_len_300_350")

        # must include brand/product
        if brand and brand not in b:
            errs.append("brand_missing")
        if product and product not in b:
            errs.append("product_missing")

        # ban stiff endings / ban casual 반말 (very rough guard)
        import re
        if re.search(r"(이다|한다|있다)\.", b) or re.search(r"(입니다|합니다)\b", b):
            errs.append("speech_style_violation")
        # avoid meta banned phrases
        if self._contains_banned(b):
            errs.append("banned_phrase_detected")

        return errs