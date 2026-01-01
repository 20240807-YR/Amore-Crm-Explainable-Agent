# agent10/product_selector.py
import re
import pandas as pd
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"


class ProductSelector:
    def __init__(self):
        csv_path = DATA_DIR / "amore_with_category.csv"
        if not csv_path.exists():
            raise FileNotFoundError(f"[ProductSelector] 데이터 파일 없음: {csv_path}")

        df = pd.read_csv(csv_path)
        df.columns = [str(c).strip() for c in df.columns]

        if "상품명" not in df.columns:
            raise RuntimeError(
                f"[ProductSelector] '상품명' 컬럼 없음: {df.columns.tolist()}"
            )

        if "brand" not in df.columns:
            raise RuntimeError(
                f"[ProductSelector] 'brand' 컬럼 없음: {df.columns.tolist()}"
            )

        self.df = df
        self.name_col = "상품명"
        self.brand_col = "brand"

        self.df[self.name_col] = (
            self.df[self.name_col]
            .astype(str)
            .fillna("")
            .str.strip()
        )

        self.df[self.brand_col] = (
            self.df[self.brand_col]
            .astype(str)
            .fillna("")
            .str.strip()
        )

        # -------------------------------------------------
        # ❌ 제품이 아닌 단독 표현 (이것만 있을 때만 제거)
        # -------------------------------------------------
        self.banned_exact = {
            "미니", "본품", "리필", "세트", "팩", "키트",
            "기획", "증정", "샘플", "사은품",
        }

        # ❌ 수량/단위만 있는 경우
        self.only_quantity_pattern = re.compile(
            r"^\s*\d+(\.\d+)?\s*(ml|mL|g|kg|ea|EA|개입|입|매|팩|세트)\s*$"
        )

    # -------------------------------------------------
    # helpers
    # -------------------------------------------------
    def _s(self, v):
        return "" if v is None else str(v).strip()

    def _is_quantity_only(self, s: str) -> bool:
        if not s:
            return True

        if self.only_quantity_pattern.fullmatch(s):
            return True

        # 숫자/기호만 있는 경우
        stripped = re.sub(r"[0-9\W_]+", "", s)
        return stripped == ""

    def _collect_candidates(self, df: pd.DataFrame):
        results = []
        if df is None or df.empty:
            return results

        for raw in df[self.name_col]:
            name = self._s(raw)

            if not name:
                continue

            # 단독 비제품 표현
            if name in self.banned_exact:
                continue

            # 순수 수량
            if self._is_quantity_only(name):
                continue

            # 🔥 절대 가공하지 않음
            results.append(name)

        return results

    # -------------------------------------------------
    # main
    # -------------------------------------------------
    def select_one(self, row: dict):
        """
        ✅ brand 기준으로 1차 필터
        ✅ 없으면 전체 CSV fallback
        ❌ 상품명 가공/절단 없음
        """
        brand = self._s(row.get("brand"))

        # 1️⃣ brand 매칭 우선
        brand_df = self.df[self.df[self.brand_col] == brand] if brand else pd.DataFrame()
        results = self._collect_candidates(brand_df)

        # 2️⃣ brand 기준 실패 → 글로벌 fallback
        if not results:
            results = self._collect_candidates(self.df)

        if not results:
            raise RuntimeError(
                "[ProductSelector] 유효한 상품명 없음 (모두 수량/비제품으로 판단됨)"
            )

        # 현재는 첫 번째 제품 사용
        return {"상품명": results[0]}