# StrategyNarrator (LLM 1-call + deterministic editor)
# - LLM is used exactly once to write a single coherent paragraph (no slot labels)
# - No LLM retry / rewrite / shorten loops in narrator
# - Deterministic post-process only: de-dup, trim/expand to 300~350, title from body
# - Title: 25~40 chars, emojis at both ends (1 each), body-based + 1 hook

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

try:
    from tone_templates import PAD_POOL as _PAD_POOL, SLOT4_PAD_POOL as _SLOT4_PAD_POOL
except Exception:
    _PAD_POOL = None
    _SLOT4_PAD_POOL = None

MIN_BODY_LEN = 300
MAX_BODY_LEN = 350

_EMOJI_RE = re.compile(r"[\U0001F300-\U0001FAFF]")


class StrategyNarrator:
    """
    LLM 1-call + deterministic editor narrator.

    Contract:
    - generate() performs exactly ONE LLM call (paragraph generation).
    - no LLM-based retry/rewrite/shorten inside narrator.
    - deterministic editing to satisfy 300~350 body and 25~40 title.
    """

    def __init__(
        self,
        llm: Optional[Any] = None,
        tone_profile_map: Optional[Dict[str, Any]] = None,
        pad_pool: Optional[List[str]] = None,
        slot4_pad_pool: Optional[List[str]] = None,
        temperature: float = 0.7,
        **kwargs,
    ):
        self.llm = llm
        self.temperature = float(temperature)

        self.tone_profile_map = tone_profile_map or {}
        self.pad_pool = list(pad_pool) if pad_pool is not None else list(_PAD_POOL or [])
        self.slot4_pad_pool = list(slot4_pad_pool) if slot4_pad_pool is not None else list(_SLOT4_PAD_POOL or [])

        # meta / CTA bans (deterministic removal)
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
            "지속 가능성 측면에서도 부담 없이 이어갈 수",
            "이 과정에서 루틴 내 위치, 지속 가능성 측면에서도",
            "어렵지 않죠?",
            "힘들진 않나요?",
            "괜찮지 않나요?",
            "자신을 더 사랑",
            "사랑하게",
            "사랑하게 될",
            "사랑하게 될 거",
        ]

        self.meta_ban_regex = [
            r"브랜드\s*톤(을|이)?\s*(유지|살리|살려|반영)",
            r"(클릭|구매\s*하기|구매하기|더\s*알아\s*보(려면|기)|자세히\s*보(기|려면))",
            r"(전략적|기획된|설계된)\s*",
            r"지속\s*가능성\s*측면",
        ]

    # -------------------------
    # tiny utils
    # -------------------------
    def _s(self, v: Any) -> str:
        return str(v).strip() if v is not None else ""

    def _strip_markdown_link(self, text: str) -> str:
        return re.sub(r"\[([^\]]+)\]\(https?://[^\)]+\)", r"\1", text)

    def _hard_clean(self, text: str) -> str:
        t = self._s(text)
        t = self._strip_markdown_link(t)
        t = re.sub(r"https?://[^\s]+", "", t, flags=re.IGNORECASE)
        t = re.sub(r"\s+", " ", t).strip()
        return t

    def _visible_len(self, text: str) -> int:
        return len(text.replace("\r", "").replace("\n", ""))

    def _norm_for_dup(self, s: str) -> str:
        s = self._s(s)
        s = re.sub(_EMOJI_RE, "", s)
        s = re.sub(r"[\"'“”‘’]", "", s)
        s = re.sub(r"[^0-9A-Za-z가-힣\s]", " ", s)
        s = re.sub(r"\s+", " ", s).strip().lower()
        return s

    # -------------------------
    # sentence splitter (NO lookbehind)
    # -------------------------
    def _split_sentences(self, text: str) -> List[str]:
        t = self._hard_clean(text)
        if not t:
            return []
        out: List[str] = []
        buf: List[str] = []
        for ch in t:
            buf.append(ch)
            if ch in ".!?":
                s = "".join(buf).strip()
                if s:
                    out.append(s)
                buf = []
        tail = "".join(buf).strip()
        if tail:
            out.append(tail if tail.endswith((".", "!", "?")) else (tail + "."))
        # final normalize
        out2: List[str] = []
        for s in out:
            ss = re.sub(r"\s+", " ", s).strip()
            if ss:
                out2.append(ss)
        return out2

    def _dedupe_sentences(self, sentences: List[str]) -> List[str]:
        seen = set()
        out: List[str] = []
        for s in sentences:
            key = self._norm_for_dup(s)
            if not key:
                continue
            if key in seen:
                continue
            seen.add(key)
            out.append(s)
        return out

    # -------------------------
    # LLM (single call)
    # -------------------------
    def _build_llm_messages(self, row: Any, plan: Any) -> List[Dict[str, str]]:
        # safe extracts
        brand = self._s(getattr(row, "get", lambda k, d=None: d)("brand", "")) if isinstance(row, dict) else ""
        if isinstance(row, dict):
            brand = self._s(row.get("brand") or row.get("brand_name_slot") or row.get("brand_name") or row.get("brand", ""))
        product = ""
        if isinstance(row, dict):
            product = self._s(row.get("상품명") or row.get("product_anchor") or row.get("product_name") or "")
        skin_concern = self._s(row.get("skin_concern", "")) if isinstance(row, dict) else ""
        lifestyle = self._s(row.get("lifestyle", "")) if isinstance(row, dict) else ""
        env_ctx = self._s(row.get("environment_context", "")) if isinstance(row, dict) else ""
        time_of_use = self._s(row.get("time_of_use", "")) if isinstance(row, dict) else ""
        message_tone = self._s(row.get("message_tone_preference", "")) if isinstance(row, dict) else ""
        scent_pref = self._s(row.get("scent_preference", "")) if isinstance(row, dict) else ""
        texture_pref = self._s(row.get("texture_preference", "")) if isinstance(row, dict) else ""
        avoid = self._s(row.get("ingredient_avoid_list", "")) if isinstance(row, dict) else ""

        # plan fields
        slot_flow = []
        mandatory = []
        tone_rules = ""
        if isinstance(plan, dict):
            slot_flow = plan.get("slot_flow") or plan.get("message_outline") or []
            mandatory = plan.get("mandatory_keywords") or plan.get("brand_must_include") or []
            tone_rules = self._s(plan.get("tone_rules") or "")

        # normalize to list[str]
        if isinstance(slot_flow, (tuple, list)):
            slot_flow_list = [self._s(x) for x in slot_flow if self._s(x)]
        else:
            slot_flow_list = [self._s(slot_flow)] if self._s(slot_flow) else []

        if isinstance(mandatory, (tuple, list)):
            mandatory_list = [self._s(x) for x in mandatory if self._s(x)]
        else:
            mandatory_list = [self._s(mandatory)] if self._s(mandatory) else []

        system = (
            "너는 한국어 CRM 마케팅 카피라이터다.\n"
            "반드시 아래 지침을 지켜라.\n"
            "1) 결과는 JSON 하나만 출력한다: {\"paragraph\": \"...\"}\n"
            "2) slot 이름/레이블을 절대 쓰지 말고, 문단은 자연스럽게 이어지는 '한 단락'이다.\n"
            "3) 중복 문장/반복 표현을 만들지 말고, 전체 흐름(도입→제안→사용→마무리)을 고려해 쓴다.\n"
            "4) 과장/선동/메타(전략/톤 언급)/CTA(클릭·구매하기 등) 문구는 쓰지 않는다.\n"
            "5) 문단은 너무 짧지 않게(여유 있게) 작성하되, 길이 조정은 시스템이 한다.\n"
        )

        user = (
            f"[브랜드] {brand}\n"
            f"[제품] {product}\n"
            f"[피부고민] {skin_concern}\n"
            f"[라이프스타일] {lifestyle}\n"
            f"[환경/맥락] {env_ctx}\n"
            f"[사용 시간대] {time_of_use}\n"
            f"[톤 선호] {message_tone}\n"
            f"[향 선호] {scent_pref}\n"
            f"[제형 선호] {texture_pref}\n"
            f"[회피 성분] {avoid}\n"
        )

        if slot_flow_list:
            user += "\n[내부 구조(slot 흐름, 레이블 출력 금지)]\n- " + "\n- ".join(slot_flow_list) + "\n"

        if mandatory_list:
            user += "\n[반드시 자연스럽게 포함할 키워드]\n- " + "\n- ".join(mandatory_list) + "\n"

        if tone_rules:
            user += "\n[톤 규칙]\n" + tone_rules.strip() + "\n"

        user += "\n위 정보를 바탕으로, 한 단락짜리 자연스러운 마케팅 문단을 작성하라.\n"

        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

    def _llm_write_paragraph_once(self, row: Any, plan: Any) -> str:
        # narrator 내부에서는 재호출/재시도/재작성 없음 (LLM client 내부 재시도는 API 안정성 목적)
        if self.llm is None:
            return ""

        messages = self._build_llm_messages(row, plan)
        raw = self.llm.generate(messages=messages, temperature=self.temperature)
        raw = self._s(raw)

        # Attempt JSON parse (best effort; no second LLM call)
        paragraph = ""
        try:
            # find first json object
            m = re.search(r"\{.*\}", raw, flags=re.DOTALL)
            candidate = m.group(0) if m else raw
            data = json.loads(candidate)
            paragraph = self._s(data.get("paragraph", ""))
        except Exception:
            # fallback: strip any TITLE/BODY labels if present
            t = raw
            t = re.sub(r"(?is)^\s*TITLE\s*:\s*.*?$", "", t).strip()
            t = re.sub(r"(?is)^\s*BODY\s*:\s*", "", t).strip()
            paragraph = t

        return self._hard_clean(paragraph)

    # -------------------------
    # deterministic editor (paragraph)
    # -------------------------
    def _remove_meta_phrases(self, text: str) -> str:
        t = self._s(text)
        for p in self.meta_ban_phrases:
            if p and p in t:
                t = t.replace(p, "")
        for rx in self.meta_ban_regex:
            try:
                t = re.sub(rx, "", t)
            except Exception:
                pass
        t = re.sub(r"\s{2,}", " ", t).strip()
        return t

    def _pad_sentence_pool(self, idx: int, slot4: bool = False) -> str:
        pool = (self.slot4_pad_pool if slot4 else self.pad_pool) or []
        fallbacks = [
            "오늘은 피부 컨디션이 흔들리기 쉬운 날이었다.",
            "유분과 건조가 같이 느껴질 때는 균형 잡힌 루틴이 중요하다.",
            "가볍게 마무리해도 하루 컨디션이 달라지는 편이다.",
            "최근 관리 텀이 길어졌다면 다시 리듬을 잡는 게 도움이 된다.",
        ]
        if not pool:
            return fallbacks[idx % len(fallbacks)]
        s = self._s(pool[idx % len(pool)])
        s = self._hard_clean(s)
        if s and not s.endswith((".", "!", "?")):
            s += "."
        return s

    def _fit_len_300_350(self, paragraph: str) -> str:
        p = self._remove_meta_phrases(self._hard_clean(paragraph))
        if not p:
            p = "오늘은 피부 컨디션이 흔들리기 쉬운 날이었다."

        # split → dedupe
        sents = self._split_sentences(p)
        sents = self._dedupe_sentences(sents)

        if not sents:
            sents = ["오늘은 피부 컨디션이 흔들리기 쉬운 날이었다."]

        # Ensure ending punctuation
        if sents and not sents[-1].endswith((".", "!", "?")):
            sents[-1] += "."

        # Expand deterministically if too short (insert before last sentence)
        insert_idx = max(0, len(sents) - 1)
        pad_i = 0
        while self._visible_len(" ".join(sents).strip()) < MIN_BODY_LEN and pad_i < 50:
            add = self._pad_sentence_pool(pad_i, slot4=False)
            # avoid duplicates
            cand = self._norm_for_dup(add)
            if cand and cand not in {self._norm_for_dup(x) for x in sents}:
                sents.insert(insert_idx, add)
                insert_idx = max(0, len(sents) - 1)
            pad_i += 1

        # Trim deterministically if too long (remove mid sentences first)
        def mid_remove_index(ss: List[str]) -> int:
            if len(ss) <= 2:
                return 0
            # remove from middle, keep first and last
            return max(1, len(ss) // 2)

        guard = 0
        while self._visible_len(" ".join(sents).strip()) > MAX_BODY_LEN and guard < 80:
            idx = mid_remove_index(sents)
            if len(sents) == 1:
                break
            sents.pop(idx)
            guard += 1

        body = " ".join(sents).strip()
        if self._visible_len(body) > MAX_BODY_LEN:
            body = body[:MAX_BODY_LEN].rstrip()
        return body.strip()

    # -------------------------
    # title (deterministic, body-based)
    # -------------------------
    def _title_clean_text(self, text: str) -> str:
        if not text:
            return ""
        s = str(text).replace("\r", " ").replace("\n", " ")
        return " ".join(s.split()).strip()

    def _title_pick_hook(self, body_clean: str) -> str:
        b = body_clean
        if any(k in b for k in ["운동", "땀", "피지", "번들", "유분"]):
            return "운동 후에도 산뜻"
        if any(k in b for k in ["진정", "붉", "열감", "자극", "민감", "따가움"]):
            return "민감할 때 딱"
        if any(k in b for k in ["건조", "당김", "각질", "속당김", "속건조"]):
            return "속건조 급정리"
        if any(k in b for k in ["탄력", "주름", "리프팅", "탱탱"]):
            return "탄탄하게 채우는"
        return "지금 필요한 한 가지"

    def _title_pick_emojis(self, body_clean: str) -> Tuple[str, str]:
        # exactly 1 emoji prefix + 1 emoji suffix
        b = body_clean
        if any(k in b for k in ["운동", "땀", "피지", "번들", "유분"]):
            return ("💦", "💦")
        if any(k in b for k in ["진정", "민감", "자극", "붉", "열감", "따가움"]):
            return ("🌿", "🌿")
        if any(k in b for k in ["건조", "당김", "각질", "속당김", "속건조"]):
            return ("💧", "💧")
        return ("✨", "✨")

    def _ensure_title_len_25_40(self, title: str, hook: str) -> str:
        t = self._s(title)
        # enforce max first
        if len(t) > 40:
            t = t[:40].rstrip()

        # ensure min 25
        if len(t) < 25:
            # add deterministic tail without meta/CTA
            tail = " 루틴" if "루틴" not in t else " 가볍게"
            t2 = (t + tail).strip()
            if len(t2) <= 40:
                t = t2
            else:
                # last resort: pad with hook variant
                t = (t + " " + hook).strip()
                if len(t) > 40:
                    t = t[:40].rstrip()

        # still too short: repeat a safe noun
        if len(t) < 25:
            t = (t + " 추천").strip()
            if len(t) > 40:
                t = t[:40].rstrip()

        return t

    def _make_title_from_body(self, body: str) -> str:
        body_clean = self._title_clean_text(body)
        hook = self._title_pick_hook(body_clean)
        pre, suf = self._title_pick_emojis(body_clean)
        core = f"{hook}"
        title = f"{pre}{core}{suf}"
        title = self._ensure_title_len_25_40(title, hook=hook)
        return title

    # -------------------------
    # public
    # -------------------------
    def generate(self, row, plan, brand_rule=None, **kwargs):
        # 1) LLM paragraph (single call)
        paragraph = self._llm_write_paragraph_once(row, plan)

        # 2) deterministic edit to 300~350
        body = self._fit_len_300_350(paragraph)

        # 3) deterministic title
        title = self._make_title_from_body(body)

        return {
            "title_line": f"TITLE: {title}",
            "body_line": f"BODY: {body}",
        }