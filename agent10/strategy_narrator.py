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

        # slot4 전용 패딩 풀 (문단 단위 유지, 짧은 문장 나열 금지)
        self.slot4_pad_pool = [
            "부담 없이 이어가기 좋고, 손이 자주 가는 편이에요.",
            "관리 텀이 조금 비어도 다시 시작하기 어렵지 않아요.",
            "일상 흐름을 끊지 않고 자연스럽게 이어져요.",
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

    def _as_text(self, v: Any) -> str:
        """Normalize possible list/tuple fields into a clean, single string."""
        if v is None:
            return ""
        if isinstance(v, (list, tuple)):
            parts: List[str] = []
            for x in v:
                s = self._s(x)
                if not s:
                    continue
                # remove leading bullet markers like "- ", "• "
                s = re.sub(r"^\s*[-•]\s*", "", s)
                if s:
                    parts.append(s)
            return " ".join(parts).strip()
        return self._s(v)

    def _lifestyle_phrase(self, lifestyle: str) -> str:
        """
        slot1(환경/상황)용 라이프스타일 문구 생성.
        - 행동/루틴/시간(예: "출근 전 5분 루틴")은 slot1에서 제거한다.
        - 숫자만 남아 "5에" 같은 파편이 생기지 않도록 방지한다.
        - "마스크 잦음"처럼 명사 키워드는 자연어로 최소 정규화한다.
        """
        raw = self._s(lifestyle)
        if not raw:
            return ""

        # 1) 콤마 기반 키워드 분리
        tokens = [t.strip() for t in raw.split(",") if t and t.strip()]
        if not tokens:
            return ""

        # 2) slot1에서 배제해야 하는(행동/루틴/시간) 마커
        routine_markers = ["루틴", "출근", "분", "아침", "저녁", "단계", "전", "후", "세안", "토너"]

        env_tokens: List[str] = []
        for t in tokens:
            # 루틴/시간 토큰은 slot1에서 제외
            if any(m in t for m in routine_markers):
                continue

            # 숫자/기호만 남은 토큰 제거 (예: "5")
            if re.fullmatch(r"[0-9]+", t):
                continue

            # 최소 자연어 정규화
            tt = t
            # '잦음' → '잦은' 형태로 정규화
            tt = tt.replace("잦음", "잦은")
            # '마스크 잦은' → '마스크 착용이 잦은'
            if "마스크" in tt and "착용" not in tt:
                # '마스크 잦은' / '마스크 잦은 환경' 등
                tt = tt.replace("마스크", "마스크 착용")
            if "마스크 착용" in tt and "잦" in tt and "착용이" not in tt:
                tt = tt.replace("마스크 착용", "마스크 착용이")

            # '사무실 에어컨'은 '에어컨 바람'으로 자연화
            if "에어컨" in tt and "바람" not in tt:
                tt = tt.replace("에어컨", "에어컨 바람")

            tt = tt.strip()
            if not tt:
                continue
            env_tokens.append(tt)

        # 3) 환경 토큰이 하나도 없으면 무리하게 만들지 않고 빈 문자열 반환
        # (slot1 기본 문장 템플릿에서 안전한 기본값으로 처리)
        if not env_tokens:
            return ""

        # 4) slot1 문장 앞부분용 구문 생성 (조사 충돌/중복 최소화)
        if len(env_tokens) == 1:
            return env_tokens[0]
        if len(env_tokens) == 2:
            return f"{env_tokens[0]}까지 겹치는 날엔"

        # 3개 이상이면 앞 3개만 사용
        a, b, c = env_tokens[0], env_tokens[1], env_tokens[2]
        return f"{a}까지 겹치고, {b}도 느껴지는 데다 {c}까지 신경 쓰이는 날엔"

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

    def _build_slot4_paragraph(self, brand_name: str, avoid_phrases: Optional[List[str]] = None) -> str:
        """
        slot4는 항상 하나의 문단으로 생성한다.
        - pad_pool/slot4_pad_pool 문구는 slot4에서만 1회 사용(콘텐츠 주도 금지)
        - 같은 완곡 문구를 여러 번 누적하지 않는다.
        """
        avoid_phrases = avoid_phrases or []

        # 기본 2문장 + (선택) pad 1문장 + (선택) 브랜드 클로징 1문장
        base_1 = "관리 텀이 조금 비어도 괜찮아요."

        # slot4_pad_pool에서 1개만 선택하되, 동일 문구 반복을 피한다.
        pad = ""
        if self.slot4_pad_pool:
            # 첫 문장(관리 텀)과 의미가 겹치지 않는 문장 우선
            candidates = [s for s in self.slot4_pad_pool if s and s not in base_1]
            pad = candidates[0] if candidates else self.slot4_pad_pool[0]

        base_2 = "오늘 컨디션에 맞춰 가볍게 얹기 좋아요."

        closing = ""
        if self._s(brand_name):
            closing = f"{brand_name}와 함께라면 일상 흐름을 끊지 않고 자연스럽게 이어져요."

        # pad는 1회만 포함
        parts = [base_1]
        if pad:
            parts.append(pad)
        parts.append(base_2)
        if closing:
            parts.append(closing)

        paragraph = " ".join([self._s(p) for p in parts if self._s(p)])

        for p in avoid_phrases:
            paragraph = paragraph.replace(p, "")

        return self._hard_clean(paragraph)

    def _fit_len_300_350(self, lines: List[str]) -> Tuple[List[str], str]:
        lines = [self._hard_clean(x) for x in lines]
        body = self._join_4lines(lines)

        # 길이 보정은 slot4에서만 수행한다.
        # - pad_pool/slot4_pad_pool 문구는 slot4에서 1회만 사용
        # - slot1~3에는 어떤 경우에도 pad를 붙이지 않는다.
        if len(body) < 300:
            # slot4가 비어 있으면 기본 문단으로 채움
            if not self._s(lines[3]):
                lines[3] = self._build_slot4_paragraph("")
            else:
                lines[3] = self._hard_clean(lines[3])

            # (1) pad 풀 문구는 1회만 추가 (중복이면 스킵)
            pad_added = False
            pad_sources = []
            if self.slot4_pad_pool:
                pad_sources.extend(self.slot4_pad_pool)
            elif self.pad_pool:
                pad_sources.extend(self.pad_pool)

            for cand in pad_sources:
                cand = self._s(cand)
                if not cand:
                    continue
                if cand in lines[3]:
                    continue
                lines[3] = self._hard_clean(lines[3] + " " + cand)
                pad_added = True
                break

            body = self._join_4lines(lines)

            # (2) 그래도 300 미만이면 pad 풀 없이 slot4에만 짧은 연결 문장 1회 추가
            #     (pad가 콘텐츠를 주도하지 않게 최소한으로만)
            if len(body) < 300:
                extra = "오늘 루틴에 가볍게 더해도 부담 없어요."
                if extra not in lines[3]:
                    lines[3] = self._hard_clean(lines[3] + " " + extra)
                body = self._join_4lines(lines)

        # 상한은 자르되, 줄 구조는 유지
        if len(body) > 350:
            body = body[:350].rstrip()

        return lines, body
    def _dedupe_body_ngrams(self, body: str, n: int = 6) -> str:
        """
        BODY 전체 기준 n-gram 중복을 제거한다.
        - 원칙: "삭제만" 수행 (대체 문장 생성 금지)
        - 줄(슬롯) 구조는 유지
        - 같은 구문이 반복되면 "뒤쪽" 문장부터 제거
        """
        text = self._s(body)
        if not text:
            return ""

        # 줄(슬롯) 단위 유지
        lines = [ln.strip() for ln in text.split("\n")]

        def split_sentences(s: str) -> List[str]:
            # 과도한 분해를 피하기 위해 마침표/물음표/느낌표/물결/… 기준만 분리
            parts = re.split(r"(?<=[\.!?…~])\s+", self._s(s))
            return [p.strip() for p in parts if p and p.strip()]

        seen = set()
        out_lines: List[str] = []

        for line in lines:
            sents = split_sentences(line)
            kept: List[str] = []
            for sent in sents:
                toks = sent.split()
                # 너무 짧으면 n-gram 기반 중복 판단을 하지 않음
                if len(toks) < n:
                    kept.append(sent)
                    continue

                dup = False
                for i in range(len(toks) - n + 1):
                    ng = tuple(toks[i : i + n])
                    if ng in seen:
                        dup = True
                        break

                if dup:
                    # "삭제만": 중복 문장은 버린다.
                    continue

                # 최초 등장 n-gram 기록
                for i in range(len(toks) - n + 1):
                    seen.add(tuple(toks[i : i + n]))
                kept.append(sent)

            out_lines.append(" ".join(kept).strip())

        # 모든 문장이 삭제되는 극단 케이스 방어
        joined = "\n".join([self._s(x) for x in out_lines])
        return joined if self._s(joined) else text

    def _ensure_len_300_350(self, body: str) -> str:
        """
        Compatibility wrapper.
        generate() expects _ensure_len_300_350, but legacy logic uses _fit_len_300_350.
        This method adapts the existing implementation without changing behavior.
        """
        lines = self._split_4lines(body)
        _, final_body = self._fit_len_300_350(lines)
        # 빈 바디 방어: 절대 빈 문자열 반환 금지
        if not self._s(final_body):
            _, final_body = self._fit_len_300_350(["", "", "", ""])
        return final_body

    # -------------------------
    # prompt builders
    # -------------------------
    def _build_system_prompt(self, brand_name: str) -> str:
        """
        시스템 프롬프트: STRICT SLOT-ONLY, TITLE/BODY 예시·라벨·구조 금지
        """
        return """
너는 고객 상담자나 CS 직원이 아니다.
너는 내부 마케팅 담당자다.

목표:
- 설명이 아니라 '제안형 광고 문구'를 작성한다.
- 독자가 한 번에 읽히는 하나의 흐름을 만든다.
- 문장 간 단절을 금지한다.

핵심 사고 규칙:
- 각 슬롯은 독립 문장이 아니다.
- 다음 슬롯은 반드시 이전 슬롯의 마지막 의미를 받아 이어 말해야 한다.
- 질문 → 제안 → 사용 장면 → 완곡한 마무리 흐름을 유지한다.

말하기 규칙:
- slot1 끝은 질문형 또는 공감형 종결을 사용한다.
- slot2는 반드시 연결어(이럴 때, 그래서, 이렇게)를 포함해 slot1을 이어간다.
- slot3은 사용 방법을 설명하지 말고, slot2 문장 안에서 자연스럽게 이어 붙인다는 사고로 작성한다.
- slot4는 감탄사·이모지·완곡 표현으로 가볍게 닫는다.

허용 표현:
- "~느껴지죠?", "~이럴 때는", "~어떨까요?"
- "~부담 없이", "~가볍게 이어가요"
- "오늘 같은 컨디션에는"

금지:
- 정보 나열식 설명
- 문장 간 끊김이 느껴지는 전개
- 설명체/하다체/~이다/~합니다
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
- 상황(Lifestyle): {self._as_text(plan.get('lifestyle_expanded') or row.get('lifestyle', ''))}
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
        lifestyle_raw = self._as_text(row.get("lifestyle", ""))
        lifestyle_phrase = self._lifestyle_phrase(lifestyle_raw)
        if not lifestyle_phrase:
            lifestyle_phrase = "실내 환경이 건조한 날엔"

        # Prepare free paragraph generation prompt
        messages = [
            {"role": "system", "content": self._build_system_prompt(brand_name)},
            {"role": "user", "content": self._build_user_prompt_free(row, plan, brand_rule)},
        ]
        raw_text = self.llm.generate(messages=messages)
        paragraph_text = raw_text["text"] if isinstance(raw_text, dict) else raw_text
        paragraph_text = self._hard_clean(paragraph_text)

        # 문단 분리 (절대 쪼개거나 재작성 금지)
        paragraphs = [p.strip() for p in paragraph_text.split("\n\n") if p.strip()]
        slot1 = paragraphs[0] if len(paragraphs) > 0 else ""
        slot2 = paragraphs[1] if len(paragraphs) > 1 else ""
        slot3 = paragraphs[2] if len(paragraphs) > 2 else ""
        slot4 = paragraphs[3] if len(paragraphs) > 3 else ""

        # slot4만 pad 허용 (최대 1회)
        lines = [slot1, slot2, slot3, slot4]
        body = "\n".join(lines).strip()
        body = self._dedupe_body_ngrams(body)
        body = self._ensure_len_300_350(body)

        title_prompt = f"""
브랜드: {brand_name}
제품: {product_name}
피부 고민: {skin_concern}
라이프스타일: {lifestyle_phrase}

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
            lifestyle_phrase,
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
        lines = self._split_4lines(b)
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