import pandas as pd
from pathlib import Path

# product_selector.py 위치 기준으로 ../data 를 잡는다
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR.parent / "data"

class ProductSelector:
    def __init__(self):
        csv_path = DATA_DIR / "amore_with_category.csv"

        if not csv_path.exists():
            raise FileNotFoundError(
                f"[ProductSelector] CSV not found: {csv_path}"
            )

        self.df = pd.read_csv(csv_path)
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