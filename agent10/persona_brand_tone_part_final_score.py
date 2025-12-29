# persona_brand_tone_part_final_score.py
from pathlib import Path
import pandas as pd

def build_score_table(data_dir: Path, out_csv: Path):
    base = pd.read_csv(data_dir / "persona_brand_tone_part_final.csv")
    base.to_csv(out_csv, index=False)
    return out_csv