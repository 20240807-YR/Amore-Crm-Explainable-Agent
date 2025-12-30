# agent10/brand_rules.py
import pandas as pd
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent        # agent10/
ROOT_DIR = BASE_DIR.parent                        # project root
DATA_DIR = ROOT_DIR / "data"                     # data/

RULES_CSV = DATA_DIR / "amore_brand_tone_rules.csv"


def load_brand_rules(csv_path: Path = RULES_CSV) -> dict:
    if not csv_path.exists():
        raise FileNotFoundError(f"[brand_rules] CSV not found: {csv_path}")

    df = pd.read_csv(csv_path)

    # 필수 컬럼 체크 
    required = [
        "brand",
        "opening",
        "product_link",
        "routine",
        "closing",
        "banned",
        "viewpoint",
        "must_include",
        "avoid",
        "style_note",
    ]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise RuntimeError(f"[brand_rules] missing columns: {missing}")

    rules = {}
    for _, row in df.iterrows():
        brand = str(row["brand"]).strip()
        rules.setdefault(brand, []).append(row.to_dict())

    return rules


if __name__ == "__main__":
    # sanity check
    rules = load_brand_rules()
    print(f"[brand_rules] loaded brands: {list(rules.keys())}")
    print(f"[brand_rules] sample rule: {list(rules.values())[0][0]}")