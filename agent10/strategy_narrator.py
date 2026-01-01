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

        # 5) 350 초과면 공백 경계 기준으로 자르되, 4줄 구조는 유지
        if len(final_body) > 350:
            trimmed = final_body[:350]
            sp = trimmed.rfind(" ")
            if sp >= 280:
                trimmed = trimmed[:sp]
            trimmed = trimmed.rstrip()
            # 마지막 줄로만 줄이기 (앞 3줄 보존)
            first3 = lines[:3]
            last = trimmed.split("\n")[-1].strip()
            if not last:
                last = self._s(lines[3])
            lines = [self._s(x) for x in first3] + [self._hard_clean(last)]
            final_body = self._join_4lines(lines).rstrip()
            final_body = re.sub(r"[\s\)\]\}.,!?:;…~]+$", "", final_body)

            # 그래도 길면 마지막 줄을 추가로 컷
            if len(final_body) > 350:
                # 마지막 문단만 350에 맞춰 컷
                head = "\n".join([self._s(x) for x in lines[:3]]).strip()
                remain = 350 - (len(head) + 1)  # +1 for newline
                if remain < 10:
                    remain = 10
                last2 = self._s(lines[3])[:remain].rstrip()
                sp2 = last2.rfind(" ")
                if sp2 >= max(0, remain - 30):
                    last2 = last2[:sp2].rstrip()
                lines[3] = self._hard_clean(last2)
                final_body = self._join_4lines(lines).rstrip()
                final_body = re.sub(r"[\s\)\]\}.,!?:;…~]+$", "", final_body)

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
        시스템 프롬프트: 페르소나 정의 및 핵심 가이드라인
        """
        return f"""당신은 {brand_name}의 전문 마케팅 카피라이터입니다.
고객의 고민을 해결하고 제품 사용을 자연스럽게 유도하는 개인화 메시지를 작성하세요.

[핵심 가이드]
1. 말투: 친근하고 부드러운 '해요체'를 사용하세요. (~합니다, ~해요, ~있어요 등)
   - 절대 금지: '~있다', '~한다', '~함' 등의 딱딱한 문어체나 종결어미.
2. 구조: 반드시 4개의 단락으로 줄바꿈하여 구성하세요.
   - 단락1: 공감 (라이프스타일/환경)
   - 단락2: 제품 제안 (피부 고민 해결)
   - 단락3: 루틴/사용법 (구체적인 상황)
   - 단락4: 혜택/마무리 (지속 사용 유도)
3. 길이: 전체 공백 포함 300~350자를 엄격히 준수하세요.
4. 표현: '브랜드 톤을 유지하며', '기획된', '설계된' 등의 메타 설명어를 절대 쓰지 마세요.

[작성 예시 1]
TITLE: ✨환절기 건조함, 설화수로 다스리세요✨
BODY: 요즘처럼 일교차가 큰 날씨엔 피부 속당김이 더 심해지죠. 따뜻한 차 한 잔처럼 피부에도 깊은 보습이 필요해요.
설화수 자음생크림이 지친 피부에 깊은 영양을 채워줄 거예요.
세안 후 기초 마지막 단계에서 부드럽게 펴 바르면 밤사이 쫀쫀하게 차오르는 탄력을 느낄 수 있어요.
꾸준히 사용하시면 속부터 우러나오는 윤기를 경험하실 수 있습니다.

[작성 예시 2]
TITLE: 💧라네즈와 함께 수분 가득한 아침을!💧
BODY: 매일 아침 푸석한 피부 때문에 화장이 들뜨지는 않으신가요? 수분 부족은 피부 컨디션을 떨어뜨리는 주범이죠.
라네즈 워터뱅크 크림이 자는 동안 수분을 꽉 잠가줄 거예요.
저녁 세안 후 듬뿍 바르고 주무시면 다음 날 아침 몰라보게 촉촉해진 피부결을 만날 수 있어요.
{brand_name}와 함께라면 매일 아침 수분으로 꽉 찬 투명한 피부를 완성할 수 있습니다.

[작성 예시 3]
TITLE: 🌿출근 전 5분, 피부 걱정없이 시작하세요!💧
BODY: 출근 전 바쁜 아침, 사무실 에어컨과 마스크로 속건조와 피지, 모공이 고민이시죠
프리메라의 NEW 나이아시카 수딩 글로우 워터리 크림 30ml가 가볍게 수분을 채워줄 거예요
세안 후 토너로 정리하고 쓱 바르면 아침/저녁 3-4단계 루틴에 쉽게 녹아들어요.
{brand_name}와 함께라면 사용감, 루틴 내 위치, 지속 가능성 측면에서도 부담 없이 이어갈 수 있습니다!
""" + f"\n- 참고 톤 키워드: {list(self.tone_profile_map.keys())}\n"

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
반드시 예시와 같은 TITLE/BODY 형식을 따르세요.
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

    def _build_user_prompt_rewrite(
        self,
        free_text: str,
        plan: Dict[str, Any],
    ) -> str:
        outline = plan.get("message_outline", [])
        outline_text = "\n".join([f"- {o}" for o in outline])

        prompt = f"""
[재작성 지시]
아래의 원문을 참고하여 마케팅 메시지를 다시 작성하세요.

요구 사항:
1. 반드시 TITLE/BODY 형식
2. BODY는 정확히 4개의 단락 (줄바꿈)
3. 단락 구조:
{outline_text}
4. 전체 길이: 공백 포함 300~350자
5. 원문의 핵심 의미를 유지하되 표현은 새로 작성 (요약/재진술)
6. 설명문, 자기언급, 메타 표현 금지

[원문]
{free_text}
"""
        return prompt

    def generate(
        self,
        row: Dict[str, Any],
        plan: Dict[str, Any],
        brand_rule: Dict[str, Any],
        repair_errors: Optional[List[str]] = None,
    ) -> str:
        brand_name = self._s(row.get("brand", "아모레퍼시픽"))

        # --- brand_rule control ---
        brand_rule = brand_rule or {}
        banned_words = [w.strip() for w in str(brand_rule.get("banned", "")).split(",") if w.strip()]
        avoid_words = [w.strip() for w in str(brand_rule.get("avoid", "")).split(",") if w.strip()]

        # --- fields ---
        product_name = self._s(row.get("상품명", ""))
        skin_concern = self._s(row.get("skin_concern", ""))
        lifestyle = self._s(row.get("lifestyle", ""))

        tone_rules = self._s(plan.get("tone_rules", ""))
        outline = plan.get("message_outline", [])
        outline_text = "\n".join([f"- {self._s(o)}" for o in outline if self._s(o)])

        # must include
        brand_must_include = plan.get("brand_must_include", [])
        if isinstance(brand_rule, dict):
            bri = brand_rule.get("must_include")
            if isinstance(bri, list) and bri:
                brand_must_include = bri

        must_str = ", ".join([self._s(x) for x in brand_must_include if self._s(x)]) if brand_must_include else ""

        system_p = self._build_system_prompt(brand_name)

        # --------------------------
        # Step 1) Free generation 600~1000
        # --------------------------
        free_user_p = self._build_user_prompt_free(row, plan, brand_rule)
        free_messages = [
            {"role": "system", "content": system_p},
            {"role": "user", "content": free_user_p},
        ]
        free_text = self.llm.generate(messages=free_messages)
        free_text = self._s(free_text)

        # --------------------------
        # Step 2) Rewrite to 4 slots / 300~350 with up to 8 retries
        # --------------------------
        last_errs: List[str] = []
        last_title = ""
        last_body = ""

        for attempt in range(8):
            # Build rewrite prompt using the free_text as source
            constraints = [
                "반드시 TITLE/BODY 형식을 사용한다.",
                "BODY는 줄바꿈 4문단(1:1:1:1)으로 작성한다.",
                "문단 순서: 1) 라이프스타일 2) 제품/피부고민 연결 3) 루틴/시간대 4) 마무리 메시지.",
                "BODY 길이는 공백 포함 300~350자이다.",
                "반말 금지, 설명용 하다체/문어체(~이다/~한다/~있다, ~합니다/~입니다) 금지, 해요체로 작성한다.",
                "브랜드명과 상품명을 BODY에 반드시 포함한다.",
                f"브랜드 필수 키워드({must_str})는 BODY에 자연스럽게 포함한다." if must_str else "브랜드 필수 키워드가 있으면 BODY에 자연스럽게 포함한다.",
                "중복 문장 금지, 메타/기획/전략 설명 문구 금지.",
                "TITLE은 25~40자, 제목 앞뒤에 각각 이모지 최소 1개 포함한다.",
                "페르소나 톤과 브랜드 톤이 느껴지는 어휘/리듬으로 작성한다(메타 표현으로 설명하지 말고 문장 자체로 반영).",
            ]
            if outline_text:
                constraints.append("아래 4슬롯 가이드 문장을 문장 속에 녹이되, 라벨을 그대로 출력하지 않는다:\n" + outline_text)

            repair_line = ""
            if last_errs:
                repair_line = "\n\n[수정 필요]\n- " + "\n- ".join(last_errs)

            rewrite_prompt = (
                "너는 한국어 CRM 마케팅 카피라이터다.\n\n"
                "[제약]\n- " + "\n- ".join(constraints) +
                repair_line +
                "\n\n[필수 포함]\n"
                f"- 브랜드: {brand_name}\n"
                f"- 상품명: {product_name}\n"
                + (f"- 브랜드 필수 키워드: {must_str}\n" if must_str else "")
                + (f"- 톤 규칙: {tone_rules}\n" if tone_rules else "")
                + "\n[브랜드 톤 힌트]\n"
                + f"- 도입 방향: {brand_rule.get('opening','')}\n"
                + f"- 루틴 설명: {brand_rule.get('routine','')}\n"
                + f"- 마무리 방향: {brand_rule.get('closing','')}\n"
                + "\n[원문(참고)]\n"
                + free_text
                + "\n"
            )

            rewrite_messages = [
                {"role": "system", "content": system_p},
                {"role": "user", "content": rewrite_prompt},
            ]
            out = self.llm.generate(messages=rewrite_messages)

            out_text = out.get("text", "") if isinstance(out, dict) else str(out)
            out_text = self._s(out_text)

            # Guard: If LLM returned empty, skip to next attempt
            if not out_text:
                last_errs = ["llm_empty_output"]
                continue

            title = "혜택 안내"
            body = out_text

            if "TITLE:" in out_text and "BODY:" in out_text:
                t_part, b_part = out_text.split("BODY:", 1)
                title = t_part.replace("TITLE:", "").strip()
                body = b_part.strip()

            # Normalize body to 4 paragraphs (hard)
            lines = self._split_4_paragraphs(body)
            # remove banned/avoid at line level
            for i in range(4):
                for bw in banned_words:
                    if bw and bw in lines[i]:
                        lines[i] = lines[i].replace(bw, "")
                for aw in avoid_words:
                    if aw and aw in lines[i]:
                        lines[i] = lines[i].replace(aw, "")
                if self._contains_banned(lines[i]):
                    for p in self.meta_ban_phrases:
                        if p:
                            lines[i] = lines[i].replace(p, "")
                    for rx in self.meta_ban_regex:
                        import re
                        lines[i] = re.sub(rx, "", lines[i])
                lines[i] = " ".join(lines[i].split()).strip()

            body = "\n".join(lines).strip()

            # Ensure must-includes (brand/product/must keywords) without breaking style
            joined = " ".join(lines)
            if brand_name and brand_name not in joined:
                lines[1] = f"{brand_name} {lines[1]}".strip()
            if product_name and product_name not in joined:
                lines[1] = f"{product_name} {lines[1]}".strip()
            if brand_must_include:
                missing = [w for w in brand_must_include if self._s(w) and self._s(w) not in " ".join(lines)]
                if missing:
                    addon = " ".join([self._s(w) for w in missing if self._s(w)])
                    lines[3] = (lines[3].rstrip() + " " + addon).strip()

            body = "\n".join([self._s(x) for x in lines]).strip()

            # Enforce final length 300~350 deterministically
            body = self._ensure_len_300_350(body)

            # Title enforcement (25~40, emoji both sides)
            title = self._ensure_title_25_40_with_emojis(title, brand_name, product_name, skin_concern, lifestyle)

            # Final hard ban check (whole body)
            if self._contains_banned(body):
                last_errs = ["banned_phrase_detected"]
                last_title, last_body = title, body
                continue

            errs = self._validate_generated(title, body, brand_name, product_name)
            if not errs:
                return f"TITLE:\n{title}\nBODY:\n{body}"

            last_errs = errs
            last_title, last_body = title, body

        # fallback (still enforce lengths)
        fb_title = self._ensure_title_25_40_with_emojis(last_title or "피부 루틴 안내", brand_name, product_name, skin_concern, lifestyle)
        fb_body = self._ensure_len_300_350(last_body or f"{lifestyle}\n{brand_name} {product_name}\n부담 없이 얇게 펴 발라 마무리해요\n필요한 타이밍에 가볍게 챙겨두면 좋아요")
        fb_lines = self._split_4_paragraphs(fb_body)
        fb_body = "\n".join(fb_lines).strip()
        fb_body = self._ensure_len_300_350(fb_body)

        return f"TITLE:\n{fb_title}\nBODY:\n{fb_body}"
    def _has_emoji(self, s: str) -> bool:
        import re
        if not s:
            return False
        return re.search(r"[\U0001F300-\U0001FAFF]", s) is not None

    def _ensure_title_25_40_with_emojis(self, title: str, brand: str, product: str, skin_concern: str, lifestyle: str) -> str:
        title = self._s(title)
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