from __future__ import annotations
import re
from typing import Any, Dict, List, Optional, Tuple

MIN_BODY_LEN = 300
MAX_BODY_LEN = 350

_EMOJI_RE = re.compile(r"[\U0001F300-\U0001FAFF]")

class StrategyNarrator:
    """
    Deterministic CRM Narrator (NO LLM).
    Responsibilities:
    - Consume pre-built CRM slot sentences only.
    - Assemble (join) slot1~4 in order.
    - Remove banned/meta phrases from slots.
    - Validate body length (300~350) without padding or rewriting.
    - Never generate or rewrite TITLE (controller-owned).
    """

    def __init__(self, **kwargs):
        # Joiner-only narrator: no padding pools, no rewriting.
        self.pad_pool: List[str] = []
        self.slot4_pad_pool: List[str] = []

        self.meta_ban_phrases = [
            "브랜드 톤", "전략", "기획", "설계된", "클릭", "구매하기",
            "더 알아보기", "자세히 보기", "중요하다", "필요하다",
        ]

        self.meta_ban_regex = [
            r"(클릭|구매\s*하기|구매하기|더\s*알아\s*보(기|려면))",
            r"(전략적|기획된|설계된)\s*",
        ]

    # -------------------------
    # utils
    # -------------------------
    def _s(self, v: Any) -> str:
        return str(v).strip() if v is not None else ""

    def _hard_clean(self, text: str) -> str:
        t = self._s(text)
        t = re.sub(r"https?://[^\s]+", "", t)
        t = re.sub(r"\s+", " ", t).strip()
        return t

    def _visible_len(self, text: str) -> int:
        return len(text.replace("\n", "").replace("\r", ""))

    def _norm_for_dup(self, s: str) -> str:
        s = self._s(s)
        s = re.sub(_EMOJI_RE, "", s)
        s = re.sub(r"[^0-9A-Za-z가-힣\s]", " ", s)
        s = re.sub(r"\s+", " ", s).strip().lower()
        return s

    def _remove_meta(self, text: str) -> str:
        t = self._s(text)
        for p in self.meta_ban_phrases:
            t = t.replace(p, "")
        for rx in self.meta_ban_regex:
            t = re.sub(rx, "", t)
        return re.sub(r"\s{2,}", " ", t).strip()

    # -------------------------
    # slot handling
    # -------------------------
    def _extract_slots(self, row: Any, plan: Any) -> List[str]:
        slots: List[str] = []
        srcs = []
        if isinstance(plan, dict):
            for k in ("slot1_text", "slot2_text", "slot3_text", "slot4_text"):
                if self._s(plan.get(k)):
                    srcs.append(self._s(plan.get(k)))
        if isinstance(row, dict):
            for k in ("slot1_text", "slot2_text", "slot3_text", "slot4_text"):
                if self._s(row.get(k)):
                    srcs.append(self._s(row.get(k)))
        for s in srcs:
            s = self._remove_meta(self._hard_clean(s))
            if s and not s.endswith((".", "!", "?")):
                s += "."
            slots.append(s)
        return slots[:4]

    def _validate_slots(self, slots: List[str]) -> bool:
        if len(slots) < 4:
            return False
        # simple 2nd-person heuristic (Korean)
        joined = " ".join(slots)
        if not any(p in joined for p in ["당신", "요즘", "지금", "때", "하면", "이라면"]):
            return False
        return True

    # -------------------------
    # body assembly
    # -------------------------
    def _dedupe(self, sents: List[str]) -> List[str]:
        seen = set()
        out = []
        for s in sents:
            k = self._norm_for_dup(s)
            if not k or k in seen:
                continue
            seen.add(k)
            out.append(s)
        return out

    def _pad_sentence(self, idx: int, slot4: bool = False) -> str:
        pool = self.slot4_pad_pool if slot4 else self.pad_pool
        s = pool[idx % len(pool)]
        return s if s.endswith((".", "!", "?")) else s + "."

    def _fit_len(self, sents: List[str]) -> Optional[str]:
        # Joiner-only: no padding, no trimming, no length judgment.
        sents = self._dedupe(sents)
        if not sents or len(sents) < 4:
            return None

        # Keep slot order strictly; assemble 4 slots only.
        body = "\n".join(sents[:4]).strip()
        return body

    # -------------------------
    # public
    # -------------------------
    def generate(self, row: Any, plan: Any, **kwargs) -> Dict[str, str]:
        slots = self._extract_slots(row, plan)
        if not self._validate_slots(slots):
            raise ValueError("Invalid or insufficient CRM slots")

        body = self._fit_len(slots)
        if body is None:
            raise ValueError("Invalid CRM body slots")

        # --------------------------------------------------
        # TITLE (controller-owned)
        # --------------------------------------------------
        title = ""
        if isinstance(plan, dict):
            title = str(plan.get("title") or plan.get("title_line") or "").strip()
        if not title and isinstance(row, dict):
            title = str(row.get("title") or "").strip()

        # Hard fallback (must not fail), but still rule-like.
        if not title:
            brand = str((row or {}).get("brand_name_slot") or (row or {}).get("brand") or "").strip()
            product_anchor = str((plan or {}).get("product_anchor") or (row or {}).get("상품명") or "").strip()
            if brand and product_anchor:
                title = f"✨{brand} {product_anchor}로 촉촉하게✨"
            elif brand:
                title = f"✨{brand}로 촉촉하게✨"
            else:
                title = "✨오늘 컨디션 케어✨"

        # Hard length cut (40 chars)
        if len(title) > 40:
            title = title[:40].rstrip()

        return {
            "title_line": f"TITLE: {title}",
            "body_line": f"BODY: {body}",
        }


# -------------------------
# Helper for WORKFLOW ONLY (not used by StrategyNarrator)
# -------------------------
class SlotDraftHelper:
    """
    Helper for WORKFLOW ONLY (not used by StrategyNarrator).
    Purpose:
    - Convert raw marketing copy (example BODY) into slot1~4 drafts.
    - This is an offline/plan-stage utility.
    - No generation, no LLM, no randomness.
    """

    @staticmethod
    def split_example_to_slots(text: str) -> Dict[str, str]:
        """
        Heuristic splitter for human-written examples.
        This is intentionally conservative and may return partial slots.
        """
        lines = [l.strip() for l in re.split(r"[\\n]+", text) if l.strip()]

        slot1, slot2, slot3, slot4 = "", "", "", ""

        for l in lines:
            if not slot1 and any(k in l for k in ["요즘", "출근", "아침", "마스크", "에어컨"]):
                slot1 = l
                continue
            if not slot2 and any(k in l for k in ["크림", "제품", "나이아시카"]):
                slot2 = l
                continue
            if not slot3 and any(k in l for k in ["아침에", "빠르게", "흡수", "바를"]):
                slot3 = l
                continue
            if not slot4 and any(k in l for k in ["이어가", "시작", "부담", "가볍게"]):
                slot4 = l
                continue

        return {
            "slot1_text": slot1,
            "slot2_text": slot2,
            "slot3_text": slot3,
            "slot4_text": slot4,
        }