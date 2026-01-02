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

[LLM SLOT-ONLY 입력 예시]
slot1_text:
바쁜 아침 출근 준비로 시간이 부족해 피부가 쉽게 푸석해지는 상황이에요.

slot2_text:
가벼운 텍스처의 나이아시카 수딩 글로우 워터리 크림이 수분을 빠르게 채워줘요.

slot3_text:
세안 후 토너 다음 단계에서 매일 아침 5분 루틴으로 사용하기 좋아요.

slot4_text:
꾸준히 사용하면 아침마다 촉촉한 피부 컨디션을 유지할 수 있어요.

[규칙]
- 위 예시는 LLM이 생성해야 할 **출력 형식의 유일한 예시**입니다.
- TITLE, BODY, 사용감, 루틴 내 위치 등 구조 토큰은 절대 포함하지 않습니다.
- 각 슬롯은 순수 자연어 문장만 허용됩니다.


[최종 출력 예시 — narrator 조립 결과용]
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

[작성 예시 4]
TITLE: 🌼바쁜 아침, 프리메라와 함께 피부 걱정 끝내요!🌼
BODY: 아침 출근 준비로 바쁜 하루가 시작되면 피부 속건조가 더욱 신경 쓰이죠.
사무실 에어컨과 마스크로 피부가 푸석해질 때 프리메라 NEW 나이아시카 수딩 글로우 워터리 크림 30ml가 가볍게 수분을 채워줘요.
세안 후 토너 다음 단계에서 얇게 펴 바르면 아침 루틴에도 부담 없이 스며들어 사용감이 편안해요.
루틴 내 위치를 고민하지 않아도 매일 이어가기 쉬워 지속 가능성 측면에서도 자연스럽게 관리할 수 있어요.

[작성 예시 5]
TITLE: 🌙밤사이 촉촉함, 이니스프리와 함께해요🌙
BODY: 하루 종일 에어컨 바람에 피부가 많이 건조해진 느낌, 공감하시나요?
이럴 때 이니스프리 그린티 씨드 세럼이 피부 속까지 깊은 보습을 선사해 줄 거예요.
저녁 세안 후 첫 단계에서 가볍게 펴 바르면 밤새 속부터 차오르는 촉촉함을 느낄 수 있어요.
매일 밤 꾸준히 사용하면 아침마다 부드럽고 건강한 피부로 시작할 수 있습니다.

[작성 예시 6]
TITLE: ☀️햇살 아래에서도 산뜻하게, 헤라와 함께☀️
BODY: 야외 활동이 많은 계절, 자외선과 미세먼지로 피부가 쉽게 지치죠.
헤라 UV 미스트 쿠션이 가볍게 밀착되어 피부를 산뜻하게 보호해 줄 거예요.
외출 전 마지막 단계로 두드려 바르면 자연스러운 커버와 동시에 자외선 차단 효과를 볼 수 있어요.
하루 종일 들뜸 없이 촉촉한 피부로 자신감을 더해보세요.

[작성 예시 7]
TITLE: 🍃피부에 휴식을, 마몽드 카모마일 에센스와 함께🍃
BODY: 일상 속 스트레스와 미세먼지로 피부가 쉽게 예민해지는 요즘이에요.
마몽드 카모마일 퓨어 토너가 피부를 진정시키고 산뜻한 수분을 선사해 줄 거예요.
세안 후 화장솜에 적셔 부드럽게 닦아내면 매일 아침저녁 루틴에 부담 없이 사용할 수 있어요.
계속 사용하면 피부가 한층 더 편안해지고 건강한 컨디션을 유지할 수 있습니다.

[구조 및 생성 제한 원칙]
- LLM은 SLOT 텍스트만 생성 (TITLE/BODY/라벨 생성 금지)
- 최종 TITLE/BODY 조립은 narrator에서만 수행
- 길이 컷은 narrator 책임 (문장 단위 컷 → slot4 제거 → discard)
- verifier는 판정만 수행
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
            "- 각 슬롯은 3~5문장으로, 원문에서 필요한 부분만 발췌하세요.\n"
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
        brand_rule = brand_rule or {}
        product_name = self._s(row.get("상품명", ""))
        skin_concern = self._s(row.get("skin_concern", ""))
        lifestyle = self._s(row.get("lifestyle", ""))
        pad_pool = self.pad_pool or [
            "오늘 컨디션에 맞춰 가볍게 얹기 좋아요.",
            "부담 없이 매일 이어가기 편해요.",
            "끈적임이 덜해 손이 자주 가요.",
            "바쁠수록 짧게 정리되는 루틴이 편하죠.",
            "가볍게 마무리돼 다음 단계가 수월해요.",
        ]

        # must include
        brand_must_include = plan.get("brand_must_include", [])
        if isinstance(brand_rule, dict):
            bri = brand_rule.get("must_include")
            if isinstance(bri, list) and bri:
                brand_must_include = bri

        # Step 1) Free generation 600~1000
        system_p = self._build_system_prompt(brand_name)
        free_user_p = self._build_user_prompt_free(row, plan, brand_rule)
        free_messages = [
            {"role": "system", "content": system_p},
            {"role": "user", "content": free_user_p},
        ]
        free_text = self.llm.generate(messages=free_messages)
        free_text = self._s(free_text)

        # Step 2a) Slot expand
        expanded_slots_text = ""
        slot_parse_success = False
        for attempt in range(3):
            slot_expand_prompt = self._build_user_prompt_slot_expand(free_text)
            slot_expand_messages = [
                {"role": "system", "content": system_p},
                {"role": "user", "content": slot_expand_prompt},
            ]
            slot_expand_out = self.llm.generate(messages=slot_expand_messages)
            expanded_slots_text = self._s(slot_expand_out.get("text", "") if isinstance(slot_expand_out, dict) else slot_expand_out)
            # Relaxed regex for slot parsing
            slot_pattern = r"SLOT\s*1\s*:\s*(.+?)\s*SLOT\s*2\s*:\s*(.+?)\s*SLOT\s*3\s*:\s*(.+?)\s*SLOT\s*4\s*:\s*(.+)"
            m = re.search(slot_pattern, expanded_slots_text, re.DOTALL)
            if m:
                slot_parse_success = True
                slot1_raw, slot2_raw, slot3_raw, slot4_raw = [s.strip() for s in m.groups()]
                break
        if not slot_parse_success:
            slot1_raw = slot2_raw = slot3_raw = slot4_raw = ""

        # Step 2b) Summarize each slot
        slots = []
        for idx, slot_raw in enumerate([slot1_raw, slot2_raw, slot3_raw, slot4_raw], 1):
            slot_sum_prompt = self._build_user_prompt_slot_summarize(slot_raw, idx)
            slot_sum_messages = [
                {"role": "system", "content": system_p},
                {"role": "user", "content": slot_sum_prompt},
            ]
            slot_sum_out = self.llm.generate(messages=slot_sum_messages)
            slot_sum_text = self._s(slot_sum_out.get("text", "") if isinstance(slot_sum_out, dict) else slot_sum_out)
            slots.append(slot_sum_text)

        # ------------------------------
        # slot validation 완화 관련 주석
        # slot2는 의미군 키워드 기준으로 완화 검증
        # slot3는 루틴 의미 키워드 기준 완화
        # ------------------------------
        # Validate: If any summarized slot is empty or <20 chars, discard that slot
        for i in range(len(slots)):
            if not slots[i] or len(slots[i].strip()) < 20:
                slots[i] = ""

        # brand_must_include slot mapping
        slot2_map = [w for w in brand_must_include if "제품" in w or "사용감" in w or "감촉" in w]
        slot3_map = [w for w in brand_must_include if "루틴" in w or "위치" in w or "단계" in w]
        slot4_map = [w for w in brand_must_include if "지속" in w or "구매" in w or "텀" in w or "혜택" in w]
        # Enforce keywords in slots
        if slot2_map:
            if not any(k in slots[1] for k in slot2_map):
                slots[1] = (slots[1] + " " + slot2_map[0]).strip()
        if slot3_map:
            if not any(k in slots[2] for k in slot3_map):
                slots[2] = (slots[2] + " " + slot3_map[0]).strip()
        if slot4_map:
            if not any(k in slots[3] for k in slot4_map):
                slots[3] = (slots[3] + " " + slot4_map[0]).strip()

        # pad_pool rule change: Only if total BODY length < 300, append one pad sentence to slot4
        body_text = "\n".join(slots)
        if len(body_text) < 300 and pad_pool:
            pad_sentence = pad_pool[0]
            slots[3] = (slots[3].rstrip() + " " + pad_sentence).strip()
            body_text = "\n".join(slots)

        # After assembling, if length > 350, remove slot4 and recompute
        if len(body_text) > 350:
            slots[3] = ""
            body_text = "\n".join(slots)
        # If still > 350, return empty string
        if len(body_text) > 350:
            return ""

        # TITLE generation
        slots_text_for_title = "\n".join([f"SLOT{i+1}: {slots[i]}" for i in range(4)])
        title_prompt = self._build_user_prompt_title_from_slots(slots_text_for_title)
        title_messages = [
            {"role": "system", "content": system_p},
            {"role": "user", "content": title_prompt},
        ]
        title_out = self.llm.generate(messages=title_messages)
        title_text = self._s(title_out.get("text", "") if isinstance(title_out, dict) else title_out)
        # Enforce length + emoji for title
        title_text = self._ensure_title_25_40_with_emojis(title_text, brand_name, product_name, skin_concern, lifestyle)

        # Final assembly (hard format)
        return f"TITLE:\n{title_text}\nBODY:\n{slots[0]}\n{slots[1]}\n{slots[2]}\n{slots[3]}"
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