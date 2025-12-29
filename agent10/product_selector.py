import pandas as pd
from pathlib import Path

DATA_DIR = Path("/Users/mac/Desktop/AMORE/Amore-Crm-Explainable-Agent/data")

class ProductSelector:
    def __init__(self):
        self.df = pd.read_csv(DATA_DIR / "amore_with_category.csv")
        self.cols = list(self.df.columns)

        self.name_col = self._pick([
            "상품명", "product_name", "name", "prod_name", "product"
        ])

        self.url_col = self._pick([
            "URL", "url", "product_url", "link", "detail_url"
        ])

        if self.name_col is None or self.url_col is None:
            raise RuntimeError(
                f"[ProductSelector] 컬럼 매핑 실패\n"
                f"columns={self.cols}\n"
                f"name_col={self.name_col}, url_col={self.url_col}"
            )

    def _pick(self, candidates):
        for c in candidates:
            if c in self.cols:
                return c
        return None

    def select_one(self, row):
        brand = row.get("brand", "")
        sub = self.df[self.df["brand"] == brand]

        if sub.empty:
            sub = self.df.iloc[[0]]

        r = sub.iloc[0]

        return {
            "상품명": str(r[self.name_col]),
            "URL": str(r[self.url_col]),
        }