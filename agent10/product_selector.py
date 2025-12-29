import pandas as pd
from pathlib import Path

# [경로 설정]
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"

class ProductSelector:
    def __init__(self):
        csv_path = DATA_DIR / "amore_with_category.csv"
        
        if not csv_path.exists():
            raise FileNotFoundError(f"데이터 파일을 찾을 수 없습니다: {csv_path}")

        # [수정된 부분] -------------------------------------------------------
        # CSV 파일에 헤더가 없으므로 header=None을 주고, names로 이름을 직접 붙여줍니다.
        # 에러 로그의 데이터 순서를 보고 추정한 컬럼명입니다.
        # (상품명, URL, 가격, 용량, ..., 전성분, 카테고리, 서브카테고리, 브랜드)
        column_names = [
            "상품명", "URL", "가격", "용량", "평점", "단위", 
            "전성분", "category", "subcategory", "brand"
        ]
        
        try:
            # header=0 (기본값) 대신 header=None을 사용
            self.df = pd.read_csv(csv_path, header=None, names=column_names)
        except Exception as e:
            # 혹시라도 파일 형식이 다를 경우를 대비해 예외 처리
            print(f"CSV 로딩 중 경고: 강제 헤더 적용 실패. 기본 로딩 시도. ({e})")
            self.df = pd.read_csv(csv_path)

        # ---------------------------------------------------------------------

        self.cols = list(self.df.columns)

        # 이제 위에서 강제로 '상품명', 'URL'이라고 이름을 붙였으므로 잘 찾아질 것입니다.
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
        # 'brand' 컬럼을 사용하므로, 위 column_names 리스트에 'brand'가 꼭 있어야 합니다.
        brand = row.get("brand", "")
        
        # 데이터프레임에 'brand' 컬럼이 있는지 확인
        if "brand" in self.df.columns:
            sub = self.df[self.df["brand"] == brand]
        else:
            sub = pd.DataFrame() # 브랜드 컬럼이 없으면 빈 DF 처리

        if sub.empty:
            sub = self.df.iloc[[0]]

        r = sub.iloc[0]

        return {
            "상품명": str(r[self.name_col]),
            "URL": str(r[self.url_col]),
        }