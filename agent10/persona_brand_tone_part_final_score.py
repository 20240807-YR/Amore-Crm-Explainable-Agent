# persona_brand_tone_part_final_score.py
from pathlib import Path
import pandas as pd

def build_score_table(data_dir: Path, out_csv: Path):
    base = pd.read_csv(data_dir / "persona_brand_tone_part_final.csv")
    base.to_csv(out_csv, index=False)
    return out_csv
# persona_brand_tone_part_final_score.py
# Utility: build final persona-brand-tone-part score table
# This file is intentionally lightweight and observable for pipeline validation.

from pathlib import Path
import pandas as pd


def build_score_table(data_dir: Path, out_csv: Path) -> Path:
    """
    Build final score table from persona_brand_tone_part_final.csv.

    This function is designed to be used either:
    1) As a utility function imported by other modules, or
    2) As a standalone executable for offline preprocessing / validation.

    Args:
        data_dir (Path): directory containing persona_brand_tone_part_final.csv
        out_csv (Path): output csv path

    Returns:
        Path: output csv path
    """
    input_path = data_dir / "persona_brand_tone_part_final.csv"

    if not input_path.exists():
        raise FileNotFoundError(f"[score_table] input file not found: {input_path}")

    print(f"[score_table] loading: {input_path}")
    base = pd.read_csv(input_path)

    print(f"[score_table] rows={len(base)} cols={list(base.columns)}")
    base.to_csv(out_csv, index=False)

    print(f"[score_table] saved: {out_csv}")
    return out_csv


if __name__ == "__main__":
    # Standalone execution mode (for debugging / preprocessing)
    DEFAULT_DATA_DIR = Path(__file__).resolve().parents[1] / "data"
    DEFAULT_OUT = DEFAULT_DATA_DIR / "persona_brand_tone_part_final_score.csv"

    print("[score_table] standalone execution")
    print(f"[score_table] data_dir={DEFAULT_DATA_DIR}")

    build_score_table(
        data_dir=DEFAULT_DATA_DIR,
        out_csv=DEFAULT_OUT,
    )