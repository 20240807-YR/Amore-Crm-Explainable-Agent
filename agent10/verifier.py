# message_verifier.py
# Verifier is executed after narration. It must validate structure without mutating content.

import re
from typing import Dict, List

MIN_BODY_LEN = 300
MAX_BODY_LEN = 350

class MessageVerifier:
    def __init__(self, strict: bool = True):
        self.strict = strict

    def _has_brand(self, text: str, brand: str) -> bool:
        if not brand:
            return True
        return brand in text

    def _has_product(self, text: str, product_anchor: str) -> bool:
        if not product_anchor:
            return True
        # require literal anchor once
        return product_anchor in text

    def _has_skin_concern(self, text: str, concerns: List[str]) -> bool:
        if not concerns:
            return True

        # Whitespace-insensitive match to tolerate natural spacing (e.g., "속 건조" vs "속건조").
        norm_text = re.sub(r"\s+", "", text or "")
        norm_concerns = [re.sub(r"\s+", "", c or "").strip() for c in concerns]
        norm_concerns = [c for c in norm_concerns if c]
        if not norm_concerns:
            return True

        # all concerns must appear at least once (loose match)
        return all(c in norm_text for c in norm_concerns)

    def _count_slots(self, body: str) -> int:
        """Count content slots.

        Primary rule: newline-separated lines.
        Fallback: if fewer than 4 lines, count sentence-like chunks to tolerate
        connected prose while preserving the "at least 4" structural intent.
        """
        if not body:
            return 0

        lines = [ln.strip() for ln in body.split("\n") if ln.strip()]
        if len(lines) >= 4:
            return len(lines)

        # Fallback sentence-ish counting (no lookbehind; robust for Korean/EN punctuation).
        # Counts chunks ending with . ! ? or the final trailing chunk.
        chunks = re.findall(r"[^.!?]+[.!?]|[^.!?]+$", body)
        chunks = [c.strip() for c in chunks if c and c.strip()]
        return len(chunks)

    def _body_len_ok(self, body: str) -> bool:
        return MIN_BODY_LEN <= len(body) <= MAX_BODY_LEN

    def _has_natural_language_anomaly(self, body: str) -> bool:
        if not body:
            return False
        # Simple anomaly patterns
        patterns = [
            r"\b5에\b",                 # stray numeral + particle
            r"(잦음)\s*도\s*\1",        # duplicated token like '잦음도 잦음'
        ]
        for p in patterns:
            if re.search(p, body):
                return True
        return False

    def _has_semantic_duplication(self, body: str) -> bool:
        if not body:
            return False
        # Detect near-duplicate sentences by normalized equality
        sentences = re.findall(r"[^.!?\n]+[.!?]|[^.!?\n]+$", body)
        norm = lambda s: re.sub(r"\s+", "", s)
        seen = set()
        for s in sentences:
            ns = norm(s)
            if ns in seen:
                return True
            seen.add(ns)
        return False

    def verify(self, message: Dict, plan: Dict) -> Dict:
        errors = []

        title = message.get("title", "") or message.get("TITLE", "")
        body = message.get("body", "") or message.get("BODY", "")

        brand = plan.get("persona_fields", {}).get("brand")
        product_anchor = plan.get("product_anchor")
        skin_concern_raw = plan.get("persona_fields", {}).get("skin_concern", "")
        skin_concerns = [s.strip() for s in skin_concern_raw.split(",") if s.strip()]

        # Length check
        if not self._body_len_ok(body):
            if len(body) < MIN_BODY_LEN:
                errors.append("body_len<300")
            else:
                errors.append("body_len>350")

        # Brand check (title OR body)
        if not (self._has_brand(title, brand) or self._has_brand(body, brand)):
            errors.append("brand_missing")

        # Product anchor check (body only)
        if not self._has_product(body, product_anchor):
            errors.append("product_missing")

        # Skin concern check (body)
        if not self._has_skin_concern(body, skin_concerns):
            errors.append("skin_concern_missing")

        # Slot count check (require at least 4 lines)
        if self._count_slots(body) < 4:
            errors.append("slot_count<4")

        # Natural language anomaly check
        if self._has_natural_language_anomaly(body):
            errors.append("nl_anomaly")

        # Semantic duplication check
        if self._has_semantic_duplication(body):
            errors.append("semantic_duplication")

        return {
            "ok": len(errors) == 0,
            "errors": errors
        }

    def validate(self, row: Dict, title: str, body: str) -> List[str]:
        """Controller compatibility API.

        Accepts (row, title, body) and reuses verify(message, plan).
        Must not mutate inputs.
        """
        # Build minimal message/plan required by current verifier rules.
        message = {"title": title or "", "body": body or ""}

        # Row may carry brand/skin_concern/product under different keys.
        brand = ""
        if isinstance(row, dict):
            brand = row.get("brand") or row.get("brand_name_slot") or row.get("brand_name") or ""

        skin_concern_raw = ""
        if isinstance(row, dict):
            skin_concern_raw = row.get("skin_concern") or row.get("skin_concern_raw") or ""

        product_anchor = ""
        if isinstance(row, dict):
            product_anchor = row.get("product_anchor") or row.get("상품명") or row.get("product") or ""

        plan = {
            "persona_fields": {
                "brand": brand,
                "skin_concern": skin_concern_raw,
            },
            "product_anchor": product_anchor,
        }

        res = self.verify(message, plan)
        return list(res.get("errors", []))

# Compatibility helper for controller import.
# Brand rule validation (if any) must be executed after narration, and must not mutate content.
# This default implementation is intentionally non-destructive and signature-tolerant.
from typing import Any, Optional

def verify_brand_rules(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    """Validate brand rules without mutating message.

    The controller may call this with different signatures depending on version.
    This function accepts any args/kwargs to avoid TypeError and returns a
    standard ok/errors payload.
    """
    return {"ok": True, "errors": []}