import pandas as pd
from pathlib import Path

class CRMLoader:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)

    def load(self, persona_id, topk):
        base = pd.read_csv(self.data_dir / "persona_brand_tone_part_final.csv")
        persona = pd.read_csv(self.data_dir / "persona_meta_v2.csv")

        df = base.merge(persona, on="persona_id", how="left")
        df = df[df["persona_id"] == persona_id].sort_values("score", ascending=False)

        return df.head(topk).to_dict("records")

    def load_tone_profile_map(self):
        p = self.data_dir / "tone_profile_map.csv"
        if not p.exists():
            return {}
        df = pd.read_csv(p)
        return dict(zip(df.iloc[:, 0], df.iloc[:, 1]))