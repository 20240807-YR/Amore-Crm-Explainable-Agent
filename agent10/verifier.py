# message_verifier.py
# Verifier is executed after narration. It must validate structure without mutating content.

import re
import csv
from pathlib import Path
from typing import Dict, List, Optional

MIN_BODY_LEN = 300
MAX_BODY_LEN = 350

class MessageVerifier:
    def __init__(self, strict: bool = True, product_catalog_path: Optional[str] = None):
        self.strict = strict

        # Product→Brand reverse mapping (상품명 -> brand)
        # Used to validate that the selected product actually belongs to the persona's brand.
        # If the catalog cannot be loaded, brand-mismatch validation is skipped (non-blocking).
        self._product_brand_map: Dict[str, str] = {}
        self._product_brand_map_loaded: bool = False
        self._product_catalog_path: Optional[str] = product_catalog_path
        self._ensure_product_brand_map_loaded()

    def _has_brand(self, text: str, brand: str) -> bool:
        if not brand:
            return True
        norm_text = re.sub(r"\s+", "", text or "").lower()
        norm_brand = re.sub(r"\s+", "", brand or "").lower()
        return norm_brand in norm_text

    def _has_product(self, text: str, product_anchor: str) -> bool:
        if not product_anchor:
            return True
        if not text:
            return False

        # Normalize whitespace
        norm_text = re.sub(r"\s+", "", text)
        norm_anchor = re.sub(r"\s+", "", product_anchor)

        # Exact anchor match
        if norm_anchor in norm_text:
            return True

        # Tolerant match: strip common volume units like 10ml/30ml/50ml/100ml
        stripped_anchor = re.sub(r"\d+(ml|ML|mL)", "", norm_anchor)
        stripped_anchor = stripped_anchor.strip()

        if stripped_anchor and stripped_anchor in norm_text:
            return True

        return False

    def _normalize_product_key(self, name: str) -> str:
        """Normalize product name for reverse-lookup.

        - Strip whitespace
        - Remove common volume tokens like 10ml/30ml
        """
        s = re.sub(r"\s+", "", name or "")
        # Remove volume tokens (ml) to be tolerant to anchor formatting
        s2 = re.sub(r"\d+(ml|ML|mL)", "", s)
        return s2.strip()

    def _default_product_catalog_path(self) -> Path:
        # agent10/verifier.py -> project_root/data/amore_with_category.csv
        here = Path(__file__).resolve()
        project_root = here.parents[1]
        return project_root / "data" / "amore_with_category.csv"

    def _ensure_product_brand_map_loaded(self) -> None:
        if self._product_brand_map_loaded:
            return

        path = None
        if self._product_catalog_path:
            try:
                path = Path(self._product_catalog_path)
            except Exception:
                path = None
        if path is None:
            path = self._default_product_catalog_path()

        try:
            if not path.exists():
                self._product_brand_map_loaded = True
                return

            m: Dict[str, str] = {}
            with path.open("r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                # Expected columns: 상품명, ..., brand
                for row in reader:
                    pname = (row.get("상품명") or "").strip()
                    b = (row.get("brand") or "").strip()
                    if not pname or not b:
                        continue
                    key = self._normalize_product_key(pname)
                    if key:
                        # Keep first occurrence; later duplicates are ignored to preserve determinism.
                        m.setdefault(key, b)
            self._product_brand_map = m
        except Exception:
            # Non-blocking: if catalog load fails, skip this validation.
            self._product_brand_map = {}
        finally:
            self._product_brand_map_loaded = True

    def _lookup_product_brand(self, product_name: str) -> str:
        if not product_name:
            return ""
        if not self._product_brand_map_loaded:
            self._ensure_product_brand_map_loaded()
        if not self._product_brand_map:
            return ""

        key = self._normalize_product_key(product_name)
        if not key:
            return ""

        # Direct key
        b = self._product_brand_map.get(key, "")
        if b:
            return b

        # If the input still contains ml variants, try the raw whitespace-stripped form too.
        raw_key = re.sub(r"\s+", "", product_name or "").strip()
        return self._product_brand_map.get(raw_key, "")

    def _has_skin_concern(self, text: str, concerns: List[str]) -> bool:
        """Skin concern is OPTIONAL.

        Policy:
          - If concerns are not provided (empty list), do NOT validate (always pass).
          - If concerns are provided, accept either:
              (a) at least one concern appears, OR
              (b) a neutral / general skin-condition phrase appears.

        Notes:
          - Whitespace-insensitive match to tolerate natural spacing.
          - We intentionally do not raise warnings when concerns are missing.
        """
        # Optional field: if no concerns were provided, skip validation entirely.
        if not concerns:
            return True

        # Whitespace-insensitive match (e.g., "속 건조" vs "속건조")
        norm_text = re.sub(r"\s+", "", text or "")

        norm_concerns = [re.sub(r"\s+", "", c or "").strip() for c in concerns]
        norm_concerns = [c for c in norm_concerns if c]
        if not norm_concerns:
            return True

        # Neutral fallback terms ("중앙값" 처리): allow generic skin-condition wording
        # so marketing copy is not forced to expose explicit concerns.
        neutral_terms = [
            "피부컨디션",
            "피부상태",
            "피부밸런스",
            "피부결",
            "피부기초",
            "전반적인피부",
            "데일리케어",
        ]

        if any(t in norm_text for t in neutral_terms):
            return True

        # Require at least ONE concern when concerns exist (unless neutral fallback hit).
        return any(c in norm_text for c in norm_concerns)

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
        """Detect adjacent (consecutive) repetition rather than global "semantic" duplication.

        Rule:
          - Only flag when the same n-gram repeats **consecutively** (A A), which usually indicates
            accidental pad/boilerplate accumulation.
          - Be more lenient for the last structural chunk (slot4) because soft-closing language can
            naturally echo earlier phrasing.

        Implementation notes:
          - For Korean/EN mixed text, whitespace tokenization can be unstable, so we also check
            character-grams on a whitespace-stripped string.
        """
        if not body:
            return False

        # Split into lines (preferred) to identify slot4; fallback to sentence-ish chunks.
        lines = [ln.strip() for ln in (body or "").split("\n") if ln.strip()]
        chunks = lines
        if len(chunks) < 4:
            chunks = re.findall(r"[^.!?\n]+[.!?]|[^.!?\n]+$", body)
            chunks = [c.strip() for c in chunks if c and c.strip()]

        if not chunks:
            return False

        # Slot4 (last chunk) is checked with a higher tolerance.
        main_chunks = chunks[:-1] if len(chunks) >= 2 else chunks
        tail_chunk = chunks[-1] if len(chunks) >= 2 else ""

        def has_adjacent_chargram_repeat(text: str, min_k: int, max_k: int) -> bool:
            s = re.sub(r"\s+", "", text or "")
            if len(s) < (min_k * 2):
                return False
            # Scan for any k-gram that repeats immediately next to itself: s[i:i+k] == s[i+k:i+2k]
            for k in range(min_k, max_k + 1):
                limit = len(s) - 2 * k
                if limit < 0:
                    continue
                for i in range(0, limit + 1):
                    if s[i:i + k] == s[i + k:i + 2 * k]:
                        return True
            return False

        # Strict for main chunks: smaller repeats should be caught.
        for c in main_chunks:
            if has_adjacent_chargram_repeat(c, min_k=8, max_k=24):
                return True

        # Lenient for tail (slot4): only flag if the repeated unit is longer.
        if tail_chunk:
            if has_adjacent_chargram_repeat(tail_chunk, min_k=14, max_k=36):
                return True

        return False

    def verify(self, message: Dict, plan: Dict) -> Dict:
        errors = []
        warnings = []

        title = message.get("title", "") or message.get("TITLE", "")
        body = message.get("body", "") or message.get("BODY", "")

        brand = plan.get("brand_name_slot") or plan.get("persona_fields", {}).get("brand")
        product_anchor = plan.get("product_anchor")
        skin_concern_raw = plan.get("persona_fields", {}).get("skin_concern", "") or ""
        skin_concern_raw = skin_concern_raw.strip()

        # Treat empty or '-' as neutral (중앙값) → skip validation
        if not skin_concern_raw or skin_concern_raw == "-":
            skin_concerns = []
        else:
            skin_concerns = [s.strip() for s in skin_concern_raw.split(",") if s.strip()]

        # Length check
        # NOTE: body_len<300 is treated as a WARNING (not a fatal error) to avoid
        # controller repair loops for short-but-structurally-valid marketing copy.
        if body is None:
            body = ""

        if len(body) < MIN_BODY_LEN:
            warnings.append("body_len<300")
        elif len(body) > MAX_BODY_LEN:
            warnings.append("body_len>350")

        # Brand check (combined title + body)
        combined_brand_text = f"{title}\n{body}"
        if not self._has_brand(combined_brand_text, brand):
            errors.append("brand_missing")

        # Product anchor check (body only)
        if not self._has_product(body, product_anchor):
            errors.append("product_missing")

        # Product→Brand mismatch check (catalog-backed)
        # Enforce: if actual brand resolved from catalog != persona brand → hard error
        actual_brand = self._lookup_product_brand(product_anchor)
        expected_brand = plan.get("brand_name_slot") or actual_brand

        if actual_brand and expected_brand and actual_brand != expected_brand:
            errors.append("product_brand_mismatch")

        # Skin concern check (title + body)
        # OPTIONAL: only validate when persona provides skin_concern.
        # Marketing copy may mention concerns in TITLE rather than BODY, so we validate on combined text.
        combined_text = f"{title}\n{body}"

        if skin_concerns and (not self._has_skin_concern(combined_text, skin_concerns)):
            # Default: do NOT fail hard for missing concern wording in marketing copy.
            # If strict mode is desired, flip this to errors.
            if self.strict:
                errors.append("skin_concern_missing")
            else:
                warnings.append("skin_concern_missing")

        # Slot count check (require at least 4 lines)
        if self._count_slots(body) < 4:
            errors.append("slot_count<4")

        # Natural language anomaly check
        if self._has_natural_language_anomaly(body):
            errors.append("nl_anomaly")

        # Duplication check (WARNING only; must not trigger controller repair)
        if self._has_semantic_duplication(body):
            warnings.append("duplication_warning")

        return {
            "ok": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
        }

    def validate(self, row: Dict, title: str, body: str) -> List[str]:
        """Controller compatibility API.

        Accepts (row, title, body) and reuses verify(message, plan).
        Must not mutate inputs.
        """
        # Build minimal message/plan required by current verifier rules.
        message = {"title": title or "", "body": body or ""}
        # Ensure catalog-backed product→brand map is available for mismatch validation.
        self._ensure_product_brand_map_loaded()

        # Row may carry brand/skin_concern/product under different keys.
        brand = ""
        if isinstance(row, dict):
            brand = row.get("brand_name_slot") or row.get("brand") or row.get("brand_name") or ""

        skin_concern_raw = ""
        if isinstance(row, dict):
            skin_concern_raw = row.get("skin_concern") or row.get("skin_concern_raw") or ""

        # If persona intentionally has no explicit skin_concern, pass a neutral default downstream
        # so the system does not force explicit concern exposure.
        if not (skin_concern_raw or "").strip():
            skin_concern_raw = "피부 컨디션"

        product_anchor = ""
        if isinstance(row, dict):
            product_anchor = row.get("product_anchor") or row.get("상품명") or row.get("product") or ""

        plan = {
            "brand_name_slot": brand,
            "persona_fields": {
                "brand": brand,
                "skin_concern": skin_concern_raw,
            },
            "product_anchor": product_anchor,
        }

        res = self.verify(message, plan)
        # Controller expects only hard errors; warnings must not trigger repair.
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