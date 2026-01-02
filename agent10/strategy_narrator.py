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
            "오늘 컨디션에 맞춰 가볍게 더하기 좋아요.",
            "부담 없이 매일 이어가기 좋아요.",
            "끈적임이 덜해 다음 단계까지 깔끔해요.",
            "바쁠수록 짧게 정리되는 루틴이 더 편해요.",
            "가볍게 마무리돼 아침에도 부담이 덜해요.",
        ]

        # slot4 전용 패딩 풀 (문단 단위 유지, 짧은 문장 나열 금지)
        self.slot4_pad_pool = [
            "부담 없이 이어가기 좋아요.",
            "관리 텀이 조금 비어도 다시 시작이 가벼워요.",
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
            # slot4 결론부 질문형 종결 차단용
            "어렵지 않죠?",
            "힘들진 않나요?",
            "괜찮지 않나요?",
        ]
        # slot4(결론부) 질문은 "결정 유도형"만 조건부 허용
        # - 허용: 행동 유도/제안형 질문
        # - 금지: 문제 제기형(힘들진 않나요? / 어렵지 않나요? 등)
        self.slot4_allow_question_patterns = [
            r"해보고\s*싶다면\?*$",
            r"해보는\s*건\s*어떨까요\?*$",
            r"해보고\s*싶지\s*않나요\?*$",
            r"시작해보셔도\s*좋아요\.?$",
            r"확인해보세요\.?$",
        ]
        self.slot4_ban_question_patterns = [
            r"힘들\s*진\s*않나요\?*$",
            r"어렵\s*지\s*않나요\?*$",
            r"괜찮\s*지\s*않나요\?*$",
        ]
        self.meta_ban_regex = [
            r"브랜드\s*톤(을|이)?\s*(유지|살리|살려|반영)",
            r"(클릭|구매\s*하기|구매하기|더\s*알아\s*보(려면|기)|자세히\s*보(기|려면))",
            r"(전략적|기획된|설계된)\s*",
            r"지속\s*가능성\s*측면",
            r"(이다|있다)$",
        ]
    def _strip_emojis(self, text: str) -> str:
        # Broad emoji unicode blocks
        return re.sub(r"[\U0001F300-\U0001FAFF]", "", self._s(text)).strip()

    def _replace_softeners(self, text: str) -> str:
        """
        광고 카피 톤에서 판단을 흐리는 완곡 표현을 최소 치환한다.
        (의미 재작성/확장 금지, 단순 치환만)
        """
        t = self._s(text)
        if not t:
            return t
        replacements = {
            "편이에요": "루틴이에요",
            "것 같아요": "느껴져요",
            "같아요": "느껴져요",
        }
        for a, b in replacements.items():
            t = t.replace(a, b)
        return t

    def _enforce_slot_punct(self, slot_text: str, slot_id: int) -> str:
        """
        slot별 문장부호/이모지 규칙을 사후 통제한다.
        - slot1: '?' 최대 1회 허용, '!' 제거
        - slot2/3: '?' 제거, '!' 0~2회 허용(과다 시 2회로 축소), 이모지 제거
        - slot4: 기본은 '?' 금지. 단, "결정 유도형(제안형)" 질문만 조건부 허용
                (문제 제기형 질문은 금지)
        """
        t = self._hard_clean(slot_text)
        t = self._replace_softeners(t)

        if slot_id in (1, 2, 3):
            t = self._strip_emojis(t)

        if slot_id == 1:
            t = t.replace("!", "")
            # keep at most one '?'
            if t.count("?") > 1:
                first = t.find("?")
                t = t[: first + 1] + t[first + 1 :].replace("?", "")
        elif slot_id in (2, 3):
            t = t.replace("?", "")
            # allow up to 2 '!'
            if t.count("!") > 2:
                # remove extras from the end
                extras = t.count("!") - 2
                while extras > 0:
                    idx = t.rfind("!")
                    if idx == -1:
                        break
                    t = t[:idx] + t[idx + 1 :]
                    extras -= 1
        else:  # slot4
            # slot4는 기본적으로 결론부 질문을 금지하되,
            # "결정 유도형(제안형)" 질문 패턴만 조건부 허용한다.
            tt = t

            # 1) 문제 제기형 질문은 무조건 제거
            for rx in getattr(self, "slot4_ban_question_patterns", []):
                if re.search(rx, tt):
                    tt = tt.replace("?", "").strip()
                    break

            # 2) 허용 패턴이면 '?'를 유지 (없으면 추가하지 않음)
            if "?" in tt:
                allowed = False
                for rx in getattr(self, "slot4_allow_question_patterns", []):
                    if re.search(rx, tt):
                        allowed = True
                        break
                if not allowed:
                    tt = tt.replace("?", "").strip()

            # 3) 느낌표는 최대 1회
            if tt.count("!") > 1:
                extras = tt.count("!") - 1
                while extras > 0:
                    idx = tt.rfind("!")
                    if idx == -1:
                        break
                    tt = tt[:idx] + tt[idx + 1 :]
                    extras -= 1

            # emoji only in slot4, but prevent obvious spam like "!!!" or repeated sparkles
            tt = re.sub(r"(!){2,}", "!", tt)
            t = tt

        return t.strip()
    def _build_slot23_expansion_sentence(self, row: Dict[str, Any], plan: Dict[str, Any], slot_id: int) -> str:
        """Deterministic, non-LLM expansion sentence for slot2/slot3.

        - 목적: BODY가 300자 미만일 때 slot4 패딩 남발 없이 길이를 확보.
        - 원칙: 의미 왜곡/추정 금지. row/plan/persona_fields에 실제 존재하는 값만 사용.
        - slot2/slot3에만 사용(이모지 금지, '?' 금지).
        """
        pf = plan.get("persona_fields") or {}

        texture = self._s(pf.get("texture_preference") or row.get("texture_preference"))
        finish = self._s(pf.get("finish_preference") or row.get("finish_preference"))
        scent = self._s(pf.get("scent_preference") or row.get("scent_preference"))
        routine_steps = self._s(pf.get("routine_step_count") or row.get("routine_step_count"))
        time_of_use = self._s(pf.get("time_of_use") or row.get("time_of_use"))
        seasonality = self._s(pf.get("seasonality") or row.get("seasonality"))
        shopping_channel = self._s(pf.get("shopping_channel") or row.get("shopping_channel"))
        repurchase = self._s(pf.get("repurchase_tendency") or row.get("repurchase_tendency"))
        allergy = self._s(pf.get("allergy_sensitivity") or row.get("allergy_sensitivity"))
        avoid = self._s(pf.get("ingredient_avoid_list") or row.get("ingredient_avoid_list"))

        # Build a single sentence using only available facts.
        parts: List[str] = []

        if texture:
            parts.append(f"{texture} 결을 좋아한다면")
        if finish:
            parts.append(f"마무리는 {finish} 쪽이 편하고")
        if scent:
            parts.append(f"향은 {scent} 쪽이 더 안정적이에요")

        # Allergy/avoid: only mention if present (no new ingredient claims)
        if allergy or avoid:
            tmp = []
            if allergy:
                tmp.append(allergy)
            if avoid:
                tmp.append(avoid)
            parts.append(f"민감 포인트는 {', '.join(tmp)}처럼 가볍게 챙기면 좋고")

        if routine_steps or time_of_use:
            rs = routine_steps if routine_steps else "짧은"
            to = time_of_use if time_of_use else "하루"
            parts.append(f"{to} {rs}단계 루틴에도 부담 없이 붙어요")

        if seasonality:
            parts.append(f"{seasonality}처럼 컨디션이 흔들리는 때에도")

        if shopping_channel or repurchase:
            ch = shopping_channel if shopping_channel else "구매"
            rp = repurchase if repurchase else "재구매"
            parts.append(f"{ch}에서 {rp} 흐름으로 이어가기에도 좋아요")

        # Fallback if everything is empty
        if not parts:
            return "가벼운 사용감으로 루틴에 자연스럽게 이어지도록 잡아줍니다!"

        sent = " ".join(parts).strip()
        # Ensure it ends as a confident ad copy sentence.
        if not sent.endswith(".") and not sent.endswith("!"):
            sent = sent + "!"

        # slot2/3 rule enforcement (no '?' / no emoji)
        sent = sent.replace("?", "")
        sent = self._strip_emojis(sent)
        return self._hard_clean(sent)

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

            # (2) 그래도 300 미만이면 slot4에 문장을 더 쌓지 않고,
            #     slot2/slot3에 '사실 기반' 확장 문장 1개씩만 추가한다.
            if len(body) < 300:
                exp2 = self._build_slot23_expansion_sentence({}, {}, 2)
                exp3 = self._build_slot23_expansion_sentence({}, {}, 3)

                # row/plan 정보가 있는 경우 generate()에서 다시 주입할 수 있도록,
                # 여기서는 lines에 이미 들어있는 문장을 우선 확장한다.
                # (fallback 문장만 쓰지 않도록, generate()에서 row/plan을 전달해 재호출하는 구조가 가장 좋지만
                #  이 함수 시그니처를 유지하기 위해 아래는 최소 안전 확장만 수행)
                if exp2 and exp2 not in lines[1]:
                    lines[1] = self._hard_clean((lines[1] + " " + exp2).strip())
                    lines[1] = self._enforce_slot_punct(lines[1], 2)
                body = self._join_4lines(lines)

            if len(body) < 300:
                exp3 = self._build_slot23_expansion_sentence({}, {}, 3)
                if exp3 and exp3 not in lines[2]:
                    lines[2] = self._hard_clean((lines[2] + " " + exp3).strip())
                    lines[2] = self._enforce_slot_punct(lines[2], 3)
                body = self._join_4lines(lines)

        # 최종 slot 규칙 재강제(확장/패딩 이후)
        lines[0] = self._enforce_slot_punct(lines[0], 1)
        lines[1] = self._enforce_slot_punct(lines[1], 2)
        lines[2] = self._enforce_slot_punct(lines[2], 3)
        lines[3] = self._enforce_slot_punct(lines[3], 4)
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
- 정보 문장이 아니라 '정제된 광고 카피'를 쓴다.
- "광고처럼 보이는 것"은 문제가 아니라 목표다.
- BODY는 문장 리스트가 아니라 광고 문단(카피) 흐름이다.

문단(슬롯) 구성:
- BODY는 4개 슬롯(4줄) 구조를 가진다.
- 각 슬롯은 2~3문장까지 허용된다(문장 나열식 1문장만 반복 금지).
- slot2 + slot3은 하나의 광고 문단처럼 자연스럽게 연결되어도 된다.

문장부호/이모지 규칙(강제):
- slot1: '?' 최대 1회 허용, '!' 금지, 이모지 금지
- slot2/slot3: '?' 금지, '!' 1~2회 허용, 이모지 금지
- slot4: '?' 기본 금지. 단, 결론부는 단정적 문장 또는 '결정 유도형(제안형)' 질문으로 마무리 가능(문제 제기형 질문 금지). '!' 0~1회 허용, 이모지는 ✨💧 정도만 1회 허용

전개 규칙:
- slot1은 상황 도입/공감으로 관심을 끌고, 질문은 여기서만 제한적으로 쓴다.
- slot2는 "그래서/이럴 때/이런 분께" 같은 연결어로 slot1을 이어서 제품 제안을 한다(제품명 자연스럽게 1회 이상 포함).
- slot3은 사용 장면/루틴을 '설명'하지 말고, slot2의 흐름을 이어 체감/사용감을 붙여준다.
- slot4는 단정적·확신형 카피로 마무리하고, 질문을 남기지 않는다.

금지:
- 정보 나열식 설명
- 결론부 질문(예: "힘들진 않나요?", "어렵지 않죠?")
- 과도한 일상 회화 완곡(예: "~인 것 같아요", "손이 자주 가는 편이에요")
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
아래 정보를 참고하여 {brand_name}의 마케팅 메시지를 작성하세요.

- 출력은 반드시 4개 문단(슬롯)로만 구성
- 문단과 문단 사이는 '빈 줄(\\n\\n)'로 구분
- 각 문단은 2~3문장까지 허용 (문장 리스트처럼 1문장만 나열 금지)
- 질문('?')은 1문단(slot1)에서만 최대 1회 허용, 4문단(slot4)은 기본 금지(단, '결정 유도형(제안형)' 질문만 허용)
- 2~3문단(slot2/slot3)에서는 '!' 1~2회 허용, 이모지 금지
- 4문단(slot4)만 이모지 1개 허용(✨ 또는 💧), '!'은 1회까지 허용
- 제품명은 2~3문단 어딘가에 자연스럽게 1회 이상 포함
- 설명/분석/자기소개 금지, 광고 카피 톤 유지

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

        # slot별 문장부호/이모지 규칙 강제
        slot1 = self._enforce_slot_punct(slot1, 1)
        slot2 = self._enforce_slot_punct(slot2, 2)
        slot3 = self._enforce_slot_punct(slot3, 3)
        slot4 = self._enforce_slot_punct(slot4, 4)
        # slot4는 기본적으로 결론부 질문을 금지하되,
        # 제안형(결정 유도형) 질문은 조건부 허용한다.
        slot4 = slot4.rstrip()
        if slot4.endswith("?"):
            allowed = False
            for rx in getattr(self, "slot4_allow_question_patterns", []):
                if re.search(rx, slot4):
                    allowed = True
                    break
            if not allowed:
                slot4 = slot4.rstrip("?").rstrip()

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