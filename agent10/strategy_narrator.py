
# agent10/strategy_narrator.py
import re
from typing import Any, Dict, List, Optional, Tuple

# Optional import for tone_templates
try:
    from tone_templates import SLOT4_PAD_POOL, PAD_POOL
except Exception:
    SLOT4_PAD_POOL = None
    PAD_POOL = None

# Optional import for tone_profiles / brand_rules (indirect reference only)
try:
    from tone_profiles import ToneProfiles
except Exception:
    ToneProfiles = None

try:
    import brand_rules
except Exception:
    brand_rules = None


class StrategyNarrator:
    # [ADD] awkward phrasing fix
    def _fix_awkward_phrasing(self, text: str) -> str:
        table = {
            '광채하게': '광채 나는',
            '수분 광채하게': '수분 광채로',
        }
        for k, v in table.items():
            text = text.replace(k, v)
        return text

    # [ADD] time-saving persuasion for busy morning
    def _inject_timesaving_hook(self, text: str, time_of_use: str) -> str:
        if time_of_use == '아침':
            hook = '머리 말리는 5분 동안만 가볍게 붙여보세요. 짧은 시간에도 수분을 빠르게 채워줍니다.'
            if hook not in text:
                parts = text.split('\n', 1)
                if len(parts) == 2:
                    return parts[0] + '\n' + hook + '\n' + parts[1]
        return text

    # [ADD] sentence completion guard (end of generate())
    def _ensure_complete_ending(self, text: str) -> str:
        text = text.strip()
        if not text:
            return text
        endings = ('.', '!', '?', '요.', '니다.')
        if text.endswith(endings):
            return text
        parts = re.split(r'(?<=[.!?요니다])\s+', text)
        if len(parts) > 1:
            text = ' '.join(parts[:-1]).strip()
        return text.rstrip() + ' 지금 바로 만나보세요.'
    def _repair_missing_nouns(self, text: str) -> str:
        """
        Repair critical Korean grammar issues where nouns are missing
        (e.g., '~해주는 이 가득').
        """
        replacements = {
            "해주는 이 가득": "해주는 수분 에너지가 가득",
            "완화해주는 이 가득": "완화해주는 유효 성분이 가득",
        }
        for k, v in replacements.items():
            text = text.replace(k, v)
        return text
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
        # pad_pool: argument > PAD_POOL from tone_templates > fallback default
        if pad_pool is not None:
            self.pad_pool = pad_pool
        elif PAD_POOL is not None:
            self.pad_pool = PAD_POOL
        else:
            self.pad_pool = [
                "오늘 컨디션에 맞춰 가볍게 더해보셔도 좋아요.",
                "프리메라와 함께 아침 루틴을 가볍게 시작해보셔도 좋아요.",
                "바쁠수록 짧게 정리되는 루틴이 더 편해요.",
                "끈적임이 덜해 다음 단계까지 깔끔하게 이어져요.",
                "지금 같은 날엔 한 단계만 더해도 피부가 편해져요.",
            ]

        # slot4_pad_pool: SLOT4_PAD_POOL from tone_templates > fallback default
        if SLOT4_PAD_POOL is not None:
            self.slot4_pad_pool = SLOT4_PAD_POOL
        else:
            self.slot4_pad_pool = [
                "오늘부터 루틴에 가볍게 더해보셔도 좋아요.",
                "프리메라와 함께 아침 루틴을 가볍게 시작해보셔도 좋아요.",
                "지금 컨디션에 맞춰 한 단계만 더해도 충분해요.",
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
            # slot4 결론부 질문형 종결 차단용
            "어렵지 않죠?",
            "힘들진 않나요?",
            "괜찮지 않나요?",
            # 감성팔이/사랑/자기애/힐링 금지 추가
            "자신을 더 사랑",
            "사랑하게",
            "사랑하게 될",
            "사랑하게 될 거",
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
        ]
        # indirect / reference-only handles (no decision logic here)
        self._tone_profiles_ref = ToneProfiles
        self._brand_rules_ref = brand_rules

    def _normalize_choice_phrase(self, raw: str, kind: str) -> str:
        """Turn code-like preference strings into natural phrases.
        - Avoid leaking raw CSV values like '워터리 로션,젤크림' or '무향/저향'.
        - Return an empty string if nothing usable.
        """
        s = self._s(raw)
        if not s:
            return ""

        # Split by common delimiters and pick first non-empty token
        toks = re.split(r"[,/|·\s]+", s)
        toks = [t.strip() for t in toks if t and t.strip()]
        token = toks[0] if toks else s.strip()

        # Minimal mapping per kind
        if kind == "texture":
            if "워터리" in s or "워터" in s:
                return "물처럼 가볍게 스며드는 제형"
            if "젤" in s:
                return "산뜻한 젤 제형"
            if "로션" in s:
                return "가벼운 로션 제형"
            if "크림" in s:
                return "부담 없는 크림 제형"
            return "가볍게 발리는 제형"

        if kind == "finish":
            if "세미" in s and "매트" in s:
                return "번들거림 없이 산뜻한 마무리"
            if "매트" in s:
                return "보송하게 정리되는 마무리"
            if "글로" in s or "광" in s:
                return "은은하게 맑아 보이는 마무리"
            return "깔끔한 마무리"

        if kind == "scent":
            if "무향" in s:
                return "향이 거의 없는 쪽"
            if "저향" in s or "약" in s:
                return "향이 강하지 않은 쪽"
            return "부담 없는 향"

        if kind == "routine":
            # keep only digits if present
            m = re.search(r"(\d+)", s)
            if m:
                return f"{m.group(1)}단계 안팎의 짧은 루틴"
            return "짧은 루틴"

        if kind == "time":
            if "아침" in s and "저녁" in s:
                return "아침과 저녁"
            if "아침" in s:
                return "아침"
            if "저녁" in s:
                return "저녁"
            return "하루"

        if kind == "season":
            # keep as gentle hint, but avoid raw arrows/symbols
            return "계절 따라 컨디션이 흔들릴 때"

        return token

    def _safe_hint(self, value: Any, kind: str) -> str:
        """Public helper to produce safe natural hint strings for prompts/output."""
        return self._normalize_choice_phrase(self._s(value), kind)

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
            "완벽한 선택": "추천드리는 쪽",
            "최고의 선택": "많이 찾는 쪽",
            "해결책": "관리 방법",
            "동반자": "루틴 한 단계",
        }
        for a, b in replacements.items():
            t = t.replace(a, b)
        return t

    def _finalize_text(self, text: str) -> str:
        """
        Final post-processing for Korean naturalness.
        Purpose: remove translationese particles that break native flow.
        """
        t = self._s(text)
        if not t:
            return t

        # 조사 '의' 과잉 제거 (번역투 교정)
        # 대표 케이스만 명시적으로 치환 (과잉 수정 방지)
        t = t.replace("요즘의 ", "요즘 ")
        t = t.replace("최근의 ", "최근 ")
        t = t.replace("현재의 ", "현재 ")

        return t

    def _polish_final_text(self, text: str) -> str:
        """
        [마지막 2% 폴리싱]
        1) 이모지 뒤에 붙은 어색한 마침표/느낌표 제거 (✨. → ✨)
        2) 반복되는 '이 크림' 표현 완화
        """
        import re

        t = self._s(text)
        if not t:
            return t

        # 1. 이모지 뒤 마침표/느낌표 제거
        # (사람이 쓰는 문장처럼 이모지 뒤에는 종결부호를 두지 않음)
        t = re.sub(r'([✨🌟💧🌿💖])\s*[.!]', r'\1', t)

        # 2. '이 크림' 반복 완화
        # 첫 등장은 유지, 이후 등장만 완화
        if t.count("이 크림") > 1:
            # 두 번째 이후의 대표적 패턴만 최소 치환
            t = t.replace("이 크림은", "", 1)
            t = t.replace("이 크림을", "", 1)

        # 공백 정리
        t = re.sub(r"\s{2,}", " ", t).strip()
        return t

    def _hard_clean_keep_newlines(self, text: str) -> str:
        """Like _hard_clean, but preserves newline structure."""
        raw = self._s(text)
        if not raw:
            return ""
        lines = raw.split("\n")
        cleaned: List[str] = []
        for ln in lines:
            t = self._s(ln)
            if not t:
                cleaned.append("")
                continue
            t = self._strip_markdown_link(t)
            t = re.sub(r"https?://[^\s]+", "", t, flags=re.IGNORECASE)
            t = re.sub(r"\s+", " ", t).strip()
            cleaned.append(t)
        return "\n".join(cleaned).strip()

    def _fix_missing_inner_punct(self, text: str) -> str:
        """Insert missing sentence punctuation inside a slot when two sentences are glued.
        Minimal, conservative heuristic for Korean ad copy.
        """
        t = self._s(text)
        if not t:
            return ""
        # Add a period between common sentence endings and a following sentence starter
        starters = r"(이\s*크림은|이\s*제품은|이\s*라인은|또한|그리고|게다가|다만|특히|그래서|이럴\s*때|이\s*때|덕분에|바로)"
        endings = r"(입니다|돼요|해요|줘요|돼요|되어요|됩니다|했어요|했죠|했어요|할\s*수\s*있어요|할\s*수\s*있습니다|선사해요|도와줘요|잡아줘요|유지해요|완성해요|추천해요|필요해요)"
        # If there's no punctuation between ending and starter, insert a period.
        t = re.sub(rf"({endings})\s+{starters}", r"\1. \2", t)
        # Also handle '...습니다 이...' style
        t = re.sub(r"(습니다|입니다|돼요|해요|줘요)\s+(이|그|저)\b", r"\1. \2", t)
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
        t = self._fix_missing_inner_punct(t)
        t = self._replace_softeners(t)
        # prevent glued sentences like "...?이럴 때" by ensuring a space after ?/!
        t = re.sub(r"([?!])(?=[가-힣A-Za-z])", r"\1 ", t)

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

        tt2 = self._s(t).strip()
        if tt2 and tt2[-1] not in [".", "!", "?"]:
            # avoid adding '.' after an already valid closing quote/bracket
            if tt2[-1] not in ["\"", "'", ")", "]", "}" ]:
                tt2 += "."
            else:
                # if ends with quote/bracket, add '.' before it
                tt2 = tt2[:-1] + "." + tt2[-1]
        t = tt2
        return t.strip()
    def _build_slot23_expansion_sentence(self, row: Dict[str, Any], plan: Dict[str, Any], slot_id: int) -> str:
        """Deterministic, non-LLM expansion sentence for slot2/slot3.

        - 목적: BODY가 300자 미만일 때 slot4 패딩 남발 없이 길이를 확보.
        - 원칙: 의미 왜곡/추정 금지. row/plan/persona_fields에 실제 존재하는 값만 사용.
        - slot2/slot3에만 사용(이모지 금지, '?' 금지).
        """
        pf = plan.get("persona_fields") or {}

        # Use SAFE naturalized hints (avoid raw CSV values)
        texture_hint = self._safe_hint(pf.get("texture_preference") or row.get("texture_preference"), "texture")
        finish_hint = self._safe_hint(pf.get("finish_preference") or row.get("finish_preference"), "finish")
        scent_hint = self._safe_hint(pf.get("scent_preference") or row.get("scent_preference"), "scent")
        routine_hint = self._safe_hint(pf.get("routine_step_count") or row.get("routine_step_count"), "routine")
        time_hint = self._safe_hint(pf.get("time_of_use") or row.get("time_of_use"), "time")
        season_hint = self._safe_hint(pf.get("seasonality") or row.get("seasonality"), "season")

        # Build ONE sentence, ad-style, without leaking raw data strings.
        parts: List[str] = []

        if texture_hint:
            parts.append(f"{texture_hint}을 좋아한다면")
        if finish_hint:
            parts.append(f"{finish_hint}으로 정리되는 쪽이 더 편하고")
        if scent_hint:
            parts.append(f"{scent_hint}라서 더 안정적이에요")

        # Add routine/time gently
        if time_hint or routine_hint:
            th = time_hint or "하루"
            rh = routine_hint or "짧은 루틴"
            parts.append(f"{th} {rh}에도 부담 없이 붙어요")

        if season_hint:
            parts.append(f"{season_hint}에도")

        # Fallback if hints are empty
        if not parts:
            sent = "가볍게 스며드는 사용감이라 루틴에 자연스럽게 이어져요!"
        else:
            sent = " ".join(parts).strip()
            # Ensure it ends as a confident ad copy sentence.
            if not sent.endswith("!"):
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

    def _get_ingredient_text(self, row: Dict[str, Any]) -> str:
        """Try to fetch ingredient/actives text from common columns.
        Returns empty string if not available."""
        keys = [
            "성분",
            "전성분",
            "주요성분",
            "유효성분",
            "actives",
            "active_ingredients",
            "ingredients",
            "ingredient",
        ]
        for k in keys:
            v = self._s(row.get(k))
            if v and v.lower() != "nan":
                return v
        return ""

    def _is_mask_pack(self, row: Dict[str, Any]) -> bool:
        """Heuristic: detect sheet/mask pack products."""
        hay = " ".join(
            [
                self._s(row.get("상품명")),
                self._s(row.get("product_name")),
                self._s(row.get("category")),
                self._s(row.get("제품유형")),
                self._s(row.get("제형")),
                self._s(row.get("type")),
            ]
        )
        return any(x in hay for x in ["마스크", "마스크팩", "시트", "sheet"])

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
        # Ensure sentence-ending punctuation
        if t and not t.endswith(('.', '!', '?')):
            t += "."
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

    def _build_slot4_paragraph(self, brand_name: str, lifestyle_hint: str = "", avoid_phrases: Optional[List[str]] = None) -> str:
        """
        slot4는 항상 하나의 문단으로 생성한다.
        - pad_pool/slot4_pad_pool 문구는 slot4에서만 1회 사용(콘텐츠 주도 금지)
        - 같은 완곡 문구를 여러 번 누적하지 않는다.
        """
        avoid_phrases = avoid_phrases or []

        # 기본 2문장 + (선택) pad 1문장 + (선택) 브랜드 클로징 1문장
        lh = self._s(lifestyle_hint)
        if lh:
            base_1 = f"{lh}처럼 바쁜 날엔, 오늘부터 가볍게 다시 시작해도 좋아요."
        else:
            base_1 = "요즘 루틴이 바빴다면, 오늘부터 가볍게 다시 시작해도 좋아요."

        # slot4_pad_pool에서 1개만 선택하되, 동일 문구 반복을 피한다.
        pad = ""
        if self.slot4_pad_pool:
            # 첫 문장(관리 텀)과 의미가 겹치지 않는 문장 우선
            candidates = [s for s in self.slot4_pad_pool if s and s not in base_1]
            pad = candidates[0] if candidates else self.slot4_pad_pool[0]

        base_2 = "프리메라와 함께 한 단계만 더해도 피부가 한결 편해져요."

        closing = ""
        if self._s(brand_name):
            closing = f"{brand_name}와 함께 오늘 루틴을 가볍게 이어가 보시겠어요?"

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

    def _fit_len_300_350(self, lines: List[str], row: Optional[Dict[str, Any]] = None, plan: Optional[Dict[str, Any]] = None) -> Tuple[List[str], str]:
        lines = [self._hard_clean(x) for x in lines]
        row = row or {}
        plan = plan or {}
        body = self._join_4lines(lines)

        # 길이 보정은 slot4에서만 수행한다.
        # - pad_pool/slot4_pad_pool 문구는 slot4에서 1회만 사용
        # - slot1~3에는 어떤 경우에도 pad를 붙이지 않는다.
        if len(body) < 300:
            # slot4가 비어 있으면 기본 문단으로 채움
            if not self._s(lines[3]):
                lh = self._s((plan.get("persona_fields") or {}).get("routine_phrase"))
                if not lh:
                    lh = self._lifestyle_phrase(self._as_text(row.get("lifestyle", "")))
                lines[3] = self._build_slot4_paragraph("", lifestyle_hint=lh)
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
                exp2 = self._build_slot23_expansion_sentence(row, plan, 2)
                if exp2 and exp2 not in lines[1]:
                    lines[1] = self._hard_clean((lines[1] + " " + exp2).strip())
                    lines[1] = self._enforce_slot_punct(lines[1], 2)
                body = self._join_4lines(lines)

            if len(body) < 300:
                exp3 = self._build_slot23_expansion_sentence(row, plan, 3)
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

    def _ensure_len_300_350(self, body: str, row: Optional[Dict[str, Any]] = None, plan: Optional[Dict[str, Any]] = None) -> str:
        """
        Compatibility wrapper.
        generate() expects _ensure_len_300_350, but legacy logic uses _fit_len_300_350.
        This method adapts the existing implementation without changing behavior.
        """
        row = row or {}
        plan = plan or {}

        lines = self._split_4lines(body)
        _, final_body = self._fit_len_300_350(lines, row=row, plan=plan)

        # Dedupe again AFTER padding/expansion (prevents pad self-clone)
        final_body = self._dedupe_body_ngrams(final_body)

        # If dedupe shortened below min, insert exactly one sentence via LLM (final safety)
        if len(final_body) < 300:
            final_body = self._llm_insert_one_sentence(final_body, row, plan)
            # Keep 4-slot structure, then dedupe once more
            final_lines = self._split_4lines(final_body)
            final_lines = [self._enforce_slot_punct(final_lines[0], 1),
                          self._enforce_slot_punct(final_lines[1], 2),
                          self._enforce_slot_punct(final_lines[2], 3),
                          self._enforce_slot_punct(final_lines[3], 4)]
            final_body = self._join_4lines(final_lines)
            final_body = self._dedupe_body_ngrams(final_body)

        # Hard guard: never return empty
        if not self._s(final_body):
            _, final_body = self._fit_len_300_350(["", "", "", ""], row=row, plan=plan)

        # --- New overflow handling: drop the previous sentence, keep the last ---
        if len(final_body) > 350:
            # Split into sentences while preserving punctuation
            import re
            sent_regex = re.compile(r'([^.!?…~]+[.!?…~])', re.UNICODE)
            sents = sent_regex.findall(final_body)
            sents = [s.strip() for s in sents if s.strip()]

            # If we have at least 2 sentences, drop the one before the last
            if len(sents) >= 2:
                # Keep everything except the penultimate sentence
                new_sents = sents[:-2] + [sents[-1]]
                rebuilt = "".join(new_sents).strip()
            else:
                rebuilt = final_body

            # Re-split into 4 slots and enforce punctuation again
            lines_new = self._split_4lines(rebuilt)
            lines_new = [
                self._enforce_slot_punct(lines_new[0], 1),
                self._enforce_slot_punct(lines_new[1], 2),
                self._enforce_slot_punct(lines_new[2], 3),
                self._enforce_slot_punct(lines_new[3], 4),
            ]
            final_body = self._join_4lines(lines_new)

        # Final hard guard (should rarely trigger)
        if len(final_body) > 350:
            final_body = final_body[:350].rstrip()

        return final_body

    def _llm_shorten_last_sentence(self, body: str) -> str:
        """
        Shorten only the last sentence of the body using the LLM,
        so that the total length becomes <= 350, preserving meaning, no new info.
        - Output must preserve the 4-slot newline structure.
        """
        import re
        # Split into lines (slots)
        lines = self._split_4lines(body)
        # Join to one text for sentence splitting
        full_text = self._join_4lines(lines)
        # Find sentences using punctuation
        # This will split on .!? (Korean and English)
        # Keep punctuation with sentence
        sentence_pattern = r'[^.!?]*[.!?]'
        # But to preserve Korean sentence endings, let's use a better pattern:
        # Split on . ! ? … ~ (Korean/English, fullwidth/halfwidth)
        # Keep punctuation
        sent_regex = re.compile(r'([^.!?…~]+[.!?…~])', re.UNICODE)
        sents = sent_regex.findall(full_text)
        if not sents:
            # fallback: treat whole as one sentence
            sents = [full_text]
        # Remove trailing whitespace in each
        sents = [s.strip() for s in sents if s.strip()]
        if not sents:
            return body
        # All except last sentence stay the same
        prefix = "".join(sents[:-1])
        last_sentence = sents[-1]
        # Compute how many chars can be used for last sentence
        max_total = 350
        prefix_len = len(prefix)
        allowed_last = max_total - prefix_len
        # Compose prompt for LLM
        prompt = (
            f"아래 광고 문장의 마지막 문장만 짧게 줄여 주세요.\n"
            f"- 반드시 한 문장만 반환\n"
            f"- 의미는 그대로 유지, 새로운 정보 추가 금지\n"
            f"- 문장 길이는 {allowed_last}자 이내로 줄이세요\n"
            f"- 이모지 ❌, 질문형 ❌, 새로운 사실 ❌\n"
            f"- 어투/톤은 그대로\n"
            f"- 한글로 작성\n"
            f"\n[마지막 문장]\n{last_sentence}\n"
        )
        messages = [
            {"role": "system", "content": "너는 광고 카피 편집자다."},
            {"role": "user", "content": prompt},
        ]
        out = self.llm.generate(messages=messages)
        shortened = out["text"] if isinstance(out, dict) else out
        # Clean result
        shortened = self._hard_clean(shortened)
        # Ensure it's not longer than allowed
        if len(shortened) > allowed_last:
            shortened = shortened[:allowed_last].rstrip()
        # Reassemble body
        new_full = prefix + shortened
        # Now split back into 4 lines, preserving slot structure
        lines_new = self._split_4lines(new_full)
        # Enforce slot punctuation
        lines_new = [
            self._enforce_slot_punct(lines_new[0], 1),
            self._enforce_slot_punct(lines_new[1], 2),
            self._enforce_slot_punct(lines_new[2], 3),
            self._enforce_slot_punct(lines_new[3], 4),
        ]
        return self._join_4lines(lines_new)

    def _llm_insert_one_sentence(self, body: str, row: Dict[str, Any], plan: Dict[str, Any]) -> str:
        """
        Final safety valve.
        - Triggered only if BODY < 300 after all deterministic padding.
        - Asks LLM to insert exactly ONE sentence.
        - Sentence must be ad-style, connective, no new facts.
        - Insertion position is 자유 (LLM decides).
        """
        prompt = f"""
아래 광고 문단은 글자 수가 부족합니다.
의미를 바꾸지 말고, **접속사로 시작하는 광고 문장 1문장만** 추가해 주세요.

규칙:
- 반드시 한 문장만 추가
- 새로운 정보, 수치, 주장 추가 금지
- 기존 문장 삭제/수정 금지
- 광고 톤 유지
- 질문형 ❌
- 위치는 자유롭게 삽입

[기존 문단]
{body}
"""
        messages = [
            {"role": "system", "content": "너는 마케팅 카피 편집자다."},
            {"role": "user", "content": prompt},
        ]
        out = self.llm.generate(messages=messages)
        text = out["text"] if isinstance(out, dict) else out
        # Preserve slot/newline structure
        text = self._hard_clean_keep_newlines(text)
        # Ensure 4 slots
        lines = self._split_4lines(text)
        lines = [self._enforce_slot_punct(lines[0], 1),
                 self._enforce_slot_punct(lines[1], 2),
                 self._enforce_slot_punct(lines[2], 3),
                 self._enforce_slot_punct(lines[3], 4)]
        return self._join_4lines(lines)

    # -------------------------
    # prompt builders
    # -------------------------
    def _build_system_prompt(self, brand_name: str) -> str:
        """
        시스템 프롬프트: STRICT SLOT-ONLY, TITLE/BODY 예시·라벨·구조 금지
        """
        base_prompt = """
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

절대 규칙(위반 시 오답 처리):
- 입력 데이터 값을 그대로 복사하지 마라. (예: "워터리 로션,젤크림", "자사몰/앱", "높음")
- 콤마(,), 슬래시(/), 파이프(|)로 나열된 원문 값을 문장에 그대로 노출하지 마라.
- "민감 포인트/선호/유형/채널/재구매" 같은 필드명 표현을 문장에 쓰지 마라.
- 문장은 반드시 완전한 문장으로 끝내라(명사형/메모형 종결 금지).
- 문장 부호(. ! ?)로 문장을 정확히 끊어라.

[톤앤매너 - 절대 금지 표현]
1. 추상적 찬양 금지:
   - "완벽한 동반자", "세련된 느낌", "최고의 선택", "기적 같은 변화" 사용 금지
   - 대신 실제 체감 변화로 표현할 것
     (예: "속당김이 줄어듭니다", "화장이 밀리지 않습니다")

2. 과한 감정 호소 금지:
   - "자신감 있는 하루", "여유로운 아침" 사용 금지
   - 대신 실용적 결과로 표현
     (예: "준비 시간이 짧아집니다", "오후까지 번들거림이 적어요")

3. 서술어 반복 금지:
   - 문장 끝을 "~해요"로만 반복하지 말 것
   - "~죠 / ~입니다 / ~돼요" 등 자연스럽게 변주

[광고 카피 품질 규칙 - 추가]
1. 다음 단어는 절대 사용 금지:
   - 완벽한, 최고의, 해결책, 동반자, 필수템, 인생템, 기적, 혁신
   → 대신 '현상'이나 '체감 결과'를 묘사할 것
     (예: "오후에도 화장이 밀리지 않아요", "번들거림이 덜해요")

2. 말투 규칙:
   - 기본은 해요체(~요, ~죠) 사용
   - "~입니다", "~합니다" 사용 금지
   - 공문/설명체 어미 금지

3. 마지막 문단(slot4) 강화 지침:
   - 반드시 '행동을 떠올리게 하는 구체성'을 포함할 것
   - 추상적 마무리 금지 ("촉촉한 피부를 느껴보세요" ❌)
   - 예시 허용:
     · "재구매가 잦은 이유가 느껴질 거예요"
     · "요즘 자사몰에서 제일 반응 좋은 크림이에요"
     · "한 번 쓰고 다시 찾게 되는 타입이에요"

[작성 스타일]
- 광고 문구처럼 보이지 않게, 옆자리 동료가 경험담을 말하듯 담백하게 작성
- 느낌표(!)는 전체 BODY 기준 최대 2회까지만 허용
"""
        # 브랜드 혼종 금지/우선 규칙 추가
        brand_rule_block = """
[브랜드 표기 강제 규칙]
- 제목과 본문에 **브랜드는 하나만 사용**한다.
- 제품명에 포함된 브랜드가 있을 경우, CSV의 brand 값보다 **제품명 브랜드를 우선**한다.
- "프리메라 메이크온", "아모레 메이크온" 같은 **혼종 브랜드 표기는 즉시 오답**이다.
"""
        return base_prompt + brand_rule_block

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
        # --- Persona guards (Fear Factor / Time / Tone) ---
        persona_fields = plan.get("persona_fields") or {}
        skin_concern = self._s(row.get("skin_concern", ""))
        time_of_use = self._s(persona_fields.get("time_of_use") or row.get("time_of_use", ""))
        tone_pref = self._s(persona_fields.get("message_tone_preference") or row.get("message_tone_preference", ""))

        is_sensitive = any(k in skin_concern for k in ["민감", "홍조", "따가움"])

        negative_keywords: List[str] = []
        preferred_keywords: List[str] = []
        if is_sensitive:
            negative_keywords = ["고농축", "영양", "활력", "채워", "리치", "탄탄", "밀도", "집중 케어"]
            preferred_keywords = ["진정", "장벽", "편안", "순한", "부드럽", "다독", "안정"]

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
- 아래 고객 정보의 '값'을 그대로 복사하지 말고, 자연스러운 문장으로 풀어 써라(콤마/슬래시 그대로 금지)
- "높음/중/낮음" 같은 등급 표현을 문장에 그대로 쓰지 마라
- 설명/분석/자기소개 금지, 광고 카피 톤 유지

[고객 정보]
- 라이프스타일: {row.get('lifestyle', '')}
- 피부 고민: {row.get('skin_concern', '')}
- 추천 제품: {product_name}
- 제형/마무리/향 취향: {self._safe_hint((plan.get('persona_fields') or {}).get('texture_preference') or row.get('texture_preference'), 'texture')}, {self._safe_hint((plan.get('persona_fields') or {}).get('finish_preference') or row.get('finish_preference'), 'finish')}, {self._safe_hint((plan.get('persona_fields') or {}).get('scent_preference') or row.get('scent_preference'), 'scent')}
- 주요 성분/유효성분(있으면 반영): {self._get_ingredient_text(row)}

[제형/컨텍스트 특수 규칙]
- 만약 추천 제품이 '마스크팩/시트팩' 계열이면, '데일리 크림/매일 바르는 로션'처럼 묘사하지 마라.
- 마스크팩은 스페셜 케어(집중 케어)로 다뤄라: "지친 저녁 15분", "중요한 날 전날", "집중 케어", "고농축 영양" 같은 표현을 자연스럽게 사용.
- 마스크팩이면 사용 맥락은 주로 저녁/휴식 시간으로 두고, 아침 매일 루틴 표현은 지양.

[효능 기반 표현 규칙]
- 감성팔이(사랑/자기애/힐링)로 마무리하지 마라.
- 가능한 경우, 성분 기반 효능을 결과 중심으로 풀어 써라.
  · 아데노신: 탄력/주름 케어 맥락
  · 세라마이드: 장벽/속당김 완화 맥락
  · 나이아신아마이드: 톤/맑기(미백) 맥락
- "밀도", "영양감", "집중 케어" 같은 단어를 과장 없이 사용.
"""
        # Insert the hard persona-targeting guard immediately after [효능 기반 표현 규칙] block
        prompt += """
[페르소나 타게팅 강제 규칙]
- 만약 피부 타입에 '건성'이 포함되거나, 피부 고민에 '주름', '탄력', '안티에이징'이 포함되면 아래 규칙을 절대적으로 따른다.
- 다음 단어 및 개념은 절대 사용 금지:
  · 피지 · 트러블 · 유분 · 산뜻 · 상쾌 · 쿨링 · 진정 위주
- 반드시 아래 개념을 중심으로 서술한다:
  · 속건조 · 주름 · 탄력 저하 · 밀도 · 영양감 · 고농축 · 집중 케어 · 리페어(회복)
- 제형 표현 규칙:
  · '가볍다/산뜻하다'라는 표현을 쓰지 말고
    '끈적임 없이 고농축 영양만 남긴다',
    '피부 깊은 곳까지 밀도 있게 채워준다'
    같은 방향으로 재해석한다.
- 마무리 인상은 '상쾌함/가벼움'이 아니라
  '탄탄하게 채워진 느낌', '다음 날까지 이어지는 밀도감'으로 끝낸다.
"""
        # [작성 팁] 블록 추가 (프롬프트 마지막 줄 바로 아래)
        prompt += """
[작성 팁]
- '선호 제형' 정보가 있다면, 그 제형이 주는 실제 사용감을 구체적으로 묘사하세요.
  (예: 세미매트 → "끈적이지 않아 바로 마스크를 써도 묻어나지 않아요")

- 고객의 라이프스타일과 제품 효능을 인과관계로 연결하세요.
  (예: 바쁜 아침 → 빠른 흡수, 마스크 착용 → 묻어남 최소화)

- 추상적인 평가 표현("좋다", "세련됐다") 대신
  손에 잡히는 변화(시간, 촉감, 번들거림, 밀림 여부)를 말하세요.

- 문장은 광고 문구처럼 짧고 리듬감 있게 작성하세요.
- "~필요합니다", "~해결해줍니다" 같은 교과서 표현은 쓰지 마세요.
- 마지막 문단에서는 고객의 구매 행동을 살짝 떠올리게 하세요.
  (예: 다시 찾게 되는 이유, 요즘 반응, 많이 쓰는 이유 등)
"""
        # [제품명 표기 규칙] 추가 (프롬프트 블록 맨 마지막)
        prompt += """
[제품명 표기 규칙]
- 첫 번째 언급: 제품 풀 네임 사용
- 두 번째 언급부터: "이 크림"처럼 짧게 줄여 지칭
"""
        # --- Negative keyword guard (Sensitive / Redness / Stinging) ---
        if is_sensitive:
            prompt += f"""
[민감성/홍조/따가움 금지어 규칙]
- 다음 단어/뉘앙스는 절대 사용 금지: {", ".join(negative_keywords)}
- 대신 아래 표현을 우선 사용: {", ".join(preferred_keywords)}
- '채워준다'보다 '다독여준다/감싸준다' 같은 뉘앙스로 작성.
"""
        # --- Time-of-use consistency ---
        if time_of_use:
            if "저녁" in time_of_use:
                prompt += """
[시간 일관성 규칙]
- 이 제품은 '저녁' 사용 맥락으로만 작성.
- '아침 루틴에 더해집니다' 같은 표현은 절대 금지.
- 허용되는 형태: '밤사이 편안하게 진정시켜, 다음 날 아침 달라진 컨디션을 만나세요'처럼 결과만 언급.
"""
            elif "아침" in time_of_use:
                prompt += """
[시간 일관성 규칙]
- 이 제품은 '아침' 사용 맥락으로만 작성.
- '저녁/밤/취침 전' 사용 제안은 절대 금지.
"""
        # --- Calm/Professional tone: suppress emojis and hype ---
        if ("차분" in tone_pref) or ("전문" in tone_pref):
            prompt += """
[톤 규칙: 차분/전문]
- 이모지 사용 금지(제목/본문 모두).
- 호들갑/과장/감성팔이 금지. 피부과 실장/더마 전문가처럼 담백하고 신뢰감 있게.
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
        import re
        brand_name = self._s(row.get("brand", "아모레퍼시픽"))
        product_name = self._s(row.get("상품명", ""))

        # --- Brand de-duplication / anti-hybrid rule ---
        # Only allow pure sub-brand, and ban any hybrid or mixed text
        brand_tokens = []
        if product_name:
            brand_tokens = re.findall(r"(메이크온|라네즈|헤라|이니스프리|설화수|마몽드)", product_name)
        if brand_tokens:
            brand_name = brand_tokens[0]
        # Brand isolation: ban any "프리메라의 메이크온" or "프리메라 메이크온" or similar hybrids
        def _brand_isolation_filter(text: str) -> str:
            # Remove hybrid brand phrases
            # Only allow one brand at a time, never "프리메라 메이크온", "아모레 메이크온", etc.
            text = re.sub(r"(프리메라의\s*메이크온|프리메라\s*메이크온|아모레\s*메이크온|아모레퍼시픽\s*메이크온)", "메이크온", text)
            # Remove any double-brand pattern (e.g. "라네즈 이니스프리", etc.)
            text = re.sub(r"(프리메라|아모레퍼시픽|아모레)\s+(메이크온|라네즈|헤라|이니스프리|설화수|마몽드)", r"\2", text)
            return text

        skin_concern = self._s(row.get("skin_concern", ""))
        lifestyle_raw = self._as_text(row.get("lifestyle", ""))
        lifestyle_phrase = self._lifestyle_phrase(lifestyle_raw)
        if not lifestyle_phrase:
            lifestyle_phrase = "실내 환경이 건조한 날엔"

        # reference-only: keep handles visible for explainability
        _tone_profiles_available = self._tone_profiles_ref is not None
        _brand_rules_available = self._brand_rules_ref is not None

        # --- Insert mask pack detection ---
        is_mask_pack = self._is_mask_pack(row)

        # --- Persona anti-aging / dry-skin hard override ---
        skin_type = self._s(row.get("skin_type", ""))
        skin_concern_val = self._s(row.get("skin_concern", ""))
        is_sensitive = any(k in skin_concern_val for k in ["민감", "홍조", "따가움"])

        persona_anti_aging = (
            (not is_sensitive)
            and (("건성" in skin_type) or any(k in skin_concern_val for k in ["주름", "탄력", "안티"]))
        )
        # --- Persona oily/trouble hard guard ---
        persona_oily_trouble = (
            ("지성" in skin_type)
            or any(k in skin_concern_val for k in ["트러블", "피지", "여드름"])
        )

        # --- Time-of-use and morning mask special rules ---
        persona_fields = plan.get("persona_fields") or {}
        time_of_use = self._s(persona_fields.get("time_of_use") or row.get("time_of_use", ""))
        time_of_use = time_of_use or ""
        tone_pref = self._s(persona_fields.get("message_tone_preference") or row.get("message_tone_preference", ""))
        calm_professional = ("차분" in tone_pref) or ("전문" in tone_pref)
        # Enforce morning-only context: if 아침 present, ban evening/15min/rest language
        enforce_morning_only = "아침" in time_of_use
        # For mask pack, if 아침 present, treat as morning booster, not special care
        maskpack_morning = is_mask_pack and enforce_morning_only
        # For mask pack, if not morning, treat as special care
        maskpack_special = is_mask_pack and not enforce_morning_only

        # --- Persona makeup/tone benefit alignment ---
        persona_makeup = False
        benefit_keywords = []
        # If persona preference includes makeup/tone, override benefit language
        # Check for tone-up, makeup, or similar in persona fields
        for v in [persona_fields.get("makeup_preference", ""), persona_fields.get("benefit_preference", ""), persona_fields.get("routine_goal", "")]:
            s = self._s(v)
            if any(x in s for x in ["메이크업", "톤업", "톤", "화장", "메컵", "메이크오버", "메이크업부스터", "베이스", "프라이머", "메이크업 지속"]):
                persona_makeup = True
        if persona_makeup:
            benefit_keywords = ["톤업", "맑은 피부", "메이크업 부스터", "화사함", "화장 잘 받음", "메이크업 지속", "피부 광채", "메이크업 전에"]

        # Prepare free paragraph generation prompt
        user_prompt = self._build_user_prompt_free(row, plan, brand_rule)
        # Compose additional instructions for persona/slot/benefit alignment
        extra_instructions = ""
        # 1. Mask-pack handling time-aware
        if is_mask_pack:
            if maskpack_morning:
                extra_instructions += (
                    "\n[마스크팩 아침 사용 규칙]\n"
                    "- 이 마스크팩은 아침 루틴(메이크업 전 부스터)으로 사용되는 맥락만 강조하세요.\n"
                    "- '15분 집중 케어', '저녁 휴식', '특별한 날'과 같은 문장은 절대 사용 금지.\n"
                    "- 대신 '아침에 빠르게 피부를 깨워준다', '메이크업 전에 피부 결을 정돈해준다', '화장이 잘 받게 도와준다' 같은 표현만 사용.\n"
                )
            elif maskpack_special:
                extra_instructions += (
                    "\n[마스크팩 스페셜케어 규칙]\n"
                    "- 이 마스크팩은 저녁/휴식 시간, 집중 케어/스페셜 케어 맥락으로만 서술하세요.\n"
                    "- '아침 루틴', '메이크업 전'과 같은 표현은 절대 사용 금지.\n"
                    "- '15분 집중 케어', '특별한 날', '고농축 영양', '피부 컨디션 회복' 등으로 표현.\n"
                )
        # 2. Morning-only context
        if enforce_morning_only:
            extra_instructions += (
                "\n[아침 루틴 강제 규칙]\n"
                "- '저녁', '15분', '휴식', '특별한 날', '집중 케어', '스페셜 케어', '고농축 영양' 등 저녁/스페셜/집중 키워드는 절대 사용 금지.\n"
                "- 오직 아침 루틴/빠른 흡수/메이크업 전/가벼운 사용감/즉각 효과/메이크업 지속/광채/톤업/메이크업 부스터 등만 사용.\n"
                "- '밤', '취침 전', '휴식 시간', '저녁 시간' 등 표현도 금지.\n"
            )
        # 3. Persona-makeup/tone benefit alignment
        if persona_makeup:
            extra_instructions += (
                "\n[메이크업/톤업 타겟 효능 규칙]\n"
                "- '영양', '고농축', '집중 케어', '리페어', '장벽', '주름', '탄력' 등 영양/리페어/안티에이징/장벽 중심 표현은 절대 사용 금지.\n"
                "- 반드시 '맑은 피부', '톤업', '광채', '화사함', '메이크업 부스터', '메이크업 지속', '메이크업 전에', '화장이 잘 받게' 등으로만 효능을 표현하세요.\n"
            )
        # 4. Brand isolation (ban any hybrid string)
        extra_instructions += (
            "\n[브랜드 표기 강제 규칙]\n"
            "- 본문/제목에서 '프리메라의 메이크온', '프리메라 메이크온', '아모레 메이크온' 등 혼종 브랜드 표기는 즉시 오답입니다.\n"
            "- 반드시 단일 브랜드명만 사용하세요.\n"
        )
        # 5. Slot-level constraints (slot3 must always mention routine/time, slot4 must fit length)
        extra_instructions += (
            "\n[슬롯별 규칙]\n"
            "- slot3(세 번째 문단)는 반드시 '아침 루틴', '빠른 흡수', '메이크업 전', '짧은 시간', '즉각 효과', '루틴', '단계', '시간' 등 시간/루틴 맥락을 포함해야 합니다.\n"
            "- slot4(네 번째 문단)는 60~80자 이내로 마무리하세요.\n"
        )
        # Inject all extra instructions at the end of user_prompt
        user_prompt += extra_instructions

        messages = [
            {"role": "system", "content": self._build_system_prompt(brand_name)},
            {"role": "user", "content": user_prompt},
        ]
        raw_text = self.llm.generate(messages=messages)
        paragraph_text = raw_text["text"] if isinstance(raw_text, dict) else raw_text
        paragraph_text = self._hard_clean_keep_newlines(paragraph_text)
        # Brand isolation: filter out any hybrid brand strings in LLM output
        paragraph_text = _brand_isolation_filter(paragraph_text)

        # 문단 분리 (절대 쪼개거나 재작성 금지)
        paragraphs = [p.strip() for p in paragraph_text.split("\n\n") if p.strip()]
        slot1 = paragraphs[0] if len(paragraphs) > 0 else ""
        slot2 = paragraphs[1] if len(paragraphs) > 1 else ""
        slot3 = paragraphs[2] if len(paragraphs) > 2 else ""
        slot4 = paragraphs[3] if len(paragraphs) > 3 else ""

        # --- Ensure slot2 begins with a transition phrase ---
        slot2_starts = ("그 해답은", "이런 고민을 위해", "그래서", "이럴 때")
        slot2_clean = slot2.lstrip()
        if not any(slot2_clean.startswith(phrase) for phrase in slot2_starts):
            slot2 = "이런 고민을 위해, " + slot2

        # slot별 문장부호/이모지 규칙 강제
        slot1 = self._enforce_slot_punct(slot1, 1)
        slot2 = self._enforce_slot_punct(slot2, 2)
        slot3 = self._enforce_slot_punct(slot3, 3)
        slot4 = self._enforce_slot_punct(slot4, 4)
        # slot4는 기본적으로 결론부 질문을 금지하되, 제안형(결정 유도형) 질문은 조건부 허용한다.
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
        body = self._ensure_len_300_350(body, row=row, plan=plan)
        body = self._dedupe_body_ngrams(body)
        # 마지막 안전망: 교과서적 광고 단어 제거
        cliche_words = ["완벽한", "최고의", "해결책", "동반자", "필수템", "인생템"]
        for w in cliche_words:
            body = body.replace(w, "")
        # Brand isolation: filter out any hybrid brand strings in BODY
        body = _brand_isolation_filter(body)
        # --- Post-generation safety & realism guards ---
        if "전달합니다." in body:
            body = body.replace("전달합니다.", "수분과 진정 효과를 전달합니다.")

        if "매일 아침" in body:
            body = body.replace("매일 아침", "운동 후 달아오른 피부에")

        if "아침 루틴에" in body:
            body = body.replace("아침 루틴에", "필요할 때 꺼내 쓰는 SOS 케어로")

        if "젤 제형" in body and "시트" not in body:
            body = body.replace("젤 제형", "젤 타입 에센스를 머금은 시트")
        # --- Mask-pack daily-use phrase replacement ---
        if is_mask_pack:
            # Replace any occurrence of "매일" or "매일 밤" with the required phrase, only in mask-pack context
            body = re.sub(r"매일\s*밤", "주 2~3회, 특별한 관리가 필요한 밤", body)
            body = re.sub(r"매일", "주 2~3회, 특별한 관리가 필요한 밤", body)
        # --- End guards ---

        # Benefit alignment: if persona_makeup, replace any nutrition/영양/리페어/장벽/주름/탄력/집중 케어/고농축 with glow/tone-up/makeup booster language
        if persona_makeup:
            # Remove or replace nutrition/repair words with tone-up/makeup-booster
            body = re.sub(r"(영양|고농축|리페어|장벽|주름|탄력|집중 케어|회복|탄탄|밀도)", "톤업", body)
            # If no benefit_keywords present, inject one
            if not any(k in body for k in benefit_keywords):
                body = re.sub(r"(피부[가-힣]*[.!?])", r"\1 맑은 피부와 메이크업 부스터 효과까지 경험해 보세요.", body, count=1)

        # Enforce morning-only context: if 아침 present, ban evening/15min/rest language
        if enforce_morning_only:
            body = re.sub(r"(저녁|15분|휴식|특별한 날|집중 케어|스페셜 케어|고농축 영양|밤|취침 전|저녁 시간|휴식 시간)", "", body)
        # If maskpack_morning, remove any "집중 케어", "저녁", "15분", etc.
        if maskpack_morning:
            body = re.sub(r"(15분|집중 케어|저녁|휴식|특별한 날|스페셜 케어|고농축 영양)", "", body)
        # If maskpack_special, remove any "아침", "메이크업 전", "부스터", etc.
        if maskpack_special:
            body = re.sub(r"(아침 루틴|아침|메이크업 전|메이크업 부스터|메이크업 전에|메이크업 지속|화장 잘 받게|광채|톤업)", "", body)

        # Slot 3 must mention routine/time
        slot_lines = self._split_4lines(body)
        slot3_keywords = ["루틴", "단계", "시간", "아침", "저녁", "밤사이", "취침 전", "메이크업 전", "빠른 흡수"]
        if not any(k in slot_lines[2] for k in slot3_keywords):
            if "저녁" in time_of_use:
                slot_lines[2] = slot_lines[2] + " 저녁 루틴에서 부담 없이 이어집니다."
            elif "아침" in time_of_use:
                slot_lines[2] = slot_lines[2] + " 아침 루틴에서 자연스럽게 이어집니다."
            else:
                slot_lines[2] = slot_lines[2] + " 오늘 루틴에서 부담 없이 이어집니다."
        # Slot 4 must fit 60~80 chars
        if len(slot_lines[3]) > 80:
            slot_lines[3] = slot_lines[3][:80].rstrip()
        body = self._join_4lines(slot_lines)
        # Brand isolation: filter out any hybrid brand strings again
        body = _brand_isolation_filter(body)

        # --- Calm/Professional tone: suppress emojis and hype ---
        if calm_professional:
            body = self._strip_emojis(body)
            # also remove leftover decorative hearts/sparkles that may not be caught by unicode range
            body = body.replace("💖", "").replace("✨", "").replace("🌟", "").replace("💧", "")

        # === [POST-PROCESSING GUARDS/REPAIRS] ===
        # 1. 목적어/명사 누락 자동 보정
        body = self._repair_missing_nouns(body)
        # 2. 어색한 한국어 표현 교정
        body = self._fix_awkward_phrasing(body)
        # 3. 바쁜 아침 TPO 자동 보정 (mask/팩 제품, 아침)
        if is_mask_pack:
            body = self._inject_timesaving_hook(body, plan.get('time_of_use'))
        # 4. 문장 완결 강제(post-check)
        body = self._ensure_complete_ending(body)

        # TITLE generation (brand isolation and benefit alignment enforced)
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
        title = _brand_isolation_filter(title)
        # If persona_makeup, enforce tone-up/glow benefit in title
        if persona_makeup and not any(k in title for k in benefit_keywords):
            title = title + " 맑은 톤업 효과"
        # Remove any nutrition/repair words from title if persona_makeup
        if persona_makeup:
            title = re.sub(r"(영양|고농축|리페어|장벽|주름|탄력|집중 케어|회복|탄탄|밀도)", "톤업", title)
        if calm_professional:
            title = self._strip_emojis(title)
            title = title.replace("💖", "").replace("✨", "").replace("🌟", "").replace("💧", "")

        final_text = f"TITLE: {title}\nBODY: {body}"
        final_text = self._finalize_text(final_text)
        final_text = self._polish_final_text(final_text)
        # --- FINAL HARD LENGTH GUARD (ABSOLUTE) ---
        body_text = body
        if len(body_text) < 300:
            body_text = self._llm_insert_one_sentence(body_text, row, plan)
            body_text = self._dedupe_body_ngrams(body_text)
            final_lines = self._split_4lines(body_text)
            final_lines = [
                self._enforce_slot_punct(final_lines[0], 1),
                self._enforce_slot_punct(final_lines[1], 2),
                self._enforce_slot_punct(final_lines[2], 3),
                self._enforce_slot_punct(final_lines[3], 4),
            ]
            body_text = self._join_4lines(final_lines)
        if len(body_text) < 300:
            body_text = body_text + " 오늘 루틴에 자연스럽게 이어가도 부담 없어요."
        body = body_text
        body = _brand_isolation_filter(body)
        # --- HARD GUARD: incomplete soft close ---
        # If BODY ends with a bare brand name or truncated fragment, replace slot4 with a fixed close.
        def _fix_truncated_close(body_text: str, brand: str) -> str:
            lines = body_text.split("\n")
            if not lines:
                return body_text
            last = lines[-1].strip()
            # Detect bare brand or very short fragment (e.g., "메이크온.")
            if last == f"{brand}." or len(last) <= len(brand) + 1:
                lines[-1] = "지금 바로 만나보세요."
            return "\n".join(lines)
        body = _fix_truncated_close(body, brand_name)
        # [POST-CHECK] 명사/목적어/어색/아침TPO/문장완결 보정 (최종 리턴 직전, 순서대로)
        body = self._repair_missing_nouns(body)
        body = self._fix_awkward_phrasing(body)
        if is_mask_pack:
            body = self._inject_timesaving_hook(body, plan.get('time_of_use'))
        body = self._ensure_complete_ending(body)
        final_text = f"TITLE: {title}\nBODY: {body}"
        # --- Tone upgrade for weak finishing phrases ---
        body = body.replace("부담 없이 맑은 느낌을 남깁니다", "피부 속부터 차오르는 고급스러운 윤기를 선사합니다")
        body = body.replace("은은한 마무리는", "고급스러운 윤기는")
        final_text = f"TITLE: {title}\nBODY: {body}"
        final_text = self._finalize_text(final_text)
        final_text = self._polish_final_text(final_text)
        # Hard guard: ensure final output ends with punctuation
        if final_text and final_text[-1] not in ".!?":
            final_text += "."
        return final_text
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
        # --- Reduce duplicate moisture keyword repetition ---
        # Specifically, if "촉촉" appears more than once, keep first, replace subsequent with "수분 광채"
        if title.count("촉촉") > 1:
            # Find all occurrences and replace after the first
            parts = []
            first_found = False
            i = 0
            while i < len(title):
                idx = title.find("촉촉", i)
                if idx == -1:
                    parts.append(title[i:])
                    break
                if not first_found:
                    parts.append(title[i:idx+2])
                    i = idx+2
                    first_found = True
                else:
                    parts.append(title[i:idx])
                    parts.append("수분 광채")
                    i = idx+2
            title = "".join(parts)
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