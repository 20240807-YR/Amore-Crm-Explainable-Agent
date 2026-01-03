from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple
import sys
import random
import numpy as np
import pandas as pd
from pathlib import Path

class ProductSelector:
    """
    [ProductSelector v4.0 - Self Healing]
    - 데이터가 주입되지 않았을 경우, 스스로 ./data 폴더에서 파일을 찾아 로드합니다.
    - 절대 '추천 제품 없음'을 반환하지 않도록 최후의 수단(Random Fallback)을 가동합니다.
    """

    # --- Anti-collapse knobs (minimal intervention) ---
    # Brand score cap: prevents a single "centroid" brand from always winning.
    # If a brand key is not present, no cap is applied.
    BRAND_CAP: Dict[str, float] = {
        # examples / defaults (tune as needed)
        "프리메라": 0.32,
        "메이크온": 0.32,
        "설화수": 0.35,
    }

    # Softmax temperature for sampling among top candidates.
    # Higher => flatter distribution (less deterministic).
    SOFTMAX_TEMPERATURE: float = 1.7

    def _brand_key(self, raw: Any) -> str:
        """Normalize brand string for dictionary lookup."""
        s = self._s(raw)
        return s.replace(" ", "")

    def _apply_brand_cap(self, score: float, brand_raw: Any) -> float:
        """Method A: cap score by brand."""
        b = self._brand_key(brand_raw)
        cap = self.BRAND_CAP.get(b)
        if cap is None:
            return float(score)
        return float(min(score, cap))

    def _softmax_probs(self, scores: List[float], temperature: float) -> List[float]:
        """Method B: brand-level softmax sampling over scores (numerically stable)."""
        if not scores:
            return []
        t = float(temperature) if float(temperature) > 0 else 1.0
        x = np.array(scores, dtype=np.float64) / t
        x = x - np.max(x)
        ex = np.exp(x)
        s = float(np.sum(ex))
        if s <= 0.0 or not np.isfinite(s):
            # fallback to uniform
            return [1.0 / len(scores)] * len(scores)
        probs = (ex / s).tolist()
        return [float(p) for p in probs]

    def __init__(self, df: Optional[Any] = None, name_col: Optional[str] = None, brand_col: Optional[str] = None):
        print(">>> [DEBUG] ProductSelector v4.0 (Self-Healing) Loaded", file=sys.stdout, flush=True)
        self.df = df
        self.name_col = name_col
        self.brand_col = brand_col

    def configure(self, df: Any, name_col: str, brand_col: str) -> None:
        self.df = df
        self.name_col = name_col
        self.brand_col = brand_col

    def _s(self, val: Any) -> str:
        return str(val).strip() if val is not None else ""

    def _ensure_df_loaded(self):
        """데이터가 없으면 스스로 찾아서 로드하는 함수"""
        if self.df is not None and not self.df.empty:
            return

        print(">>> [DEBUG] 🚨 DataFrame is missing! Attempting auto-load...", file=sys.stdout, flush=True)

        current_dir = Path(__file__).resolve().parent
        candidates = [
            current_dir.parent / "data" / "amore_with_category.csv",
            current_dir / "data" / "amore_with_category.csv",
            Path("/Users/mac/Desktop/AMORE/Amore-Crm-Explainable-Agent/data/amore_with_category.csv"),
        ]

        for path in candidates:
            if path.exists():
                try:
                    print(f">>> [DEBUG] Found data file at: {path}", file=sys.stdout, flush=True)
                    self.df = pd.read_csv(path)
                    self.name_col = "상품명" if "상품명" in self.df.columns else self.df.columns[0]
                    self.brand_col = "brand" if "brand" in self.df.columns else "브랜드"
                    print(f">>> [DEBUG] Auto-loaded {len(self.df)} products.", file=sys.stdout, flush=True)
                    return
                except Exception as e:
                    print(f">>> [DEBUG] Failed to load {path}: {e}", file=sys.stdout, flush=True)

        print(">>> [DEBUG] ❌ CRITICAL: Could not auto-load any data file.", file=sys.stdout, flush=True)

    def select_product(self, row: Dict[str, Any], topk: int = 3) -> Tuple[str, float]:
        # 1. 데이터 확인 및 자가 복구
        self._ensure_df_loaded()

        if self.df is None or self.df.empty:
            return "추천 제품 없음 (데이터 로드 실패)", 0.0

        # 2. 타겟 브랜드 확인
        target_brand_raw = row.get("brand", "")
        target_brand = self._s(target_brand_raw).replace(" ", "").lower()
        print(f">>> [DEBUG] Target Brand: '{target_brand}'", file=sys.stdout, flush=True)

        def _get_candidates(filter_brand: str = ""):
            cands = []
            unique_names = self.df[self.name_col].unique()
            for name in unique_names:
                sub_df = self.df[self.df[self.name_col] == name]
                if sub_df.empty:
                    continue

                p_brand_raw = self._s(sub_df.iloc[0][self.brand_col])
                p_brand = p_brand_raw.replace(" ", "").lower()

                if filter_brand:
                    if (filter_brand not in p_brand) and (p_brand not in filter_brand):
                        continue

                sim_benefit = float(sub_df.iloc[0]["benefit_score"]) if "benefit_score" in sub_df.columns else 0.0
                sim_identity = float(sub_df.iloc[0]["identity_score"]) if "identity_score" in sub_df.columns else 0.0
                final_score = (0.5 * sim_benefit) + (0.5 * sim_identity)

                lifestyle = str(row.get("lifestyle", ""))
                if "바쁜" in lifestyle or "간편" in lifestyle:
                    if "메이크온" in p_brand_raw or "디바이스" in name:
                        final_score *= 0.1

                # Method A: brand score cap (prevents collapse)
                final_score = self._apply_brand_cap(float(final_score), p_brand_raw)

                cands.append((name, float(final_score)))
            return cands

        candidates = []
        if target_brand:
            candidates = _get_candidates(target_brand)
            print(f">>> [DEBUG] Found {len(candidates)} products for '{target_brand}'", file=sys.stdout, flush=True)

        if not candidates:
            print(">>> [DEBUG] ⚠️ No products found! Fallback to ALL brands.", file=sys.stdout, flush=True)
            candidates = _get_candidates("")

        if not candidates:
            first_prod = self.df.iloc[0][self.name_col]
            return first_prod, 0.1

        candidates.sort(key=lambda x: x[1], reverse=True)
        top_candidates = candidates[:topk]

        best = top_candidates[0]
        print(f">>> [DEBUG] Selected: {best[0]} ({best[1]:.4f})", file=sys.stdout, flush=True)

        # Method B: softmax sampling (flattens small score gaps)
        scores = [float(c[1]) for c in top_candidates]
        probs = self._softmax_probs(scores, self.SOFTMAX_TEMPERATURE)

        if probs and len(probs) == len(top_candidates):
            idx = int(np.random.choice(len(top_candidates), p=probs))
            chosen = top_candidates[idx]
        else:
            chosen = top_candidates[0]

        return chosen[0], float(chosen[1])