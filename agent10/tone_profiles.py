# tone_profiles.py
from pathlib import Path
import pandas as pd

class ToneProfiles:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)

    def _read_csv(self, name):
        p = self.data_dir / name
        if not p.exists():
            return None
        return pd.read_csv(p)

    def load_tone_profiles(self):
        df = self._read_csv("brand_tone_definitions.csv")
        if df is None:
            df = self._read_csv("tone_centroid_profile.csv")
        if df is None:
            df = self._read_csv("brand_tone_cluster.csv")
        return df if df is not None else pd.DataFrame()

    def load_tone_profile_map(self):
        df = self.load_tone_profiles()
        if df is None or df.empty:
            return {}

        cols = [str(c).strip() for c in df.columns]

        def pick(cands):
            for c in cands:
                if c in cols:
                    return c
            return None

        kcol = pick(["brand_tone_cluster", "cluster", "tone_cluster", "tone_id", "id"])
        tcol = pick(["full_description", "tone_full", "description", "desc", "profile", "tone_profile", "text"])
        pcol = pick(["description_preview", "preview", "short", "summary"])

        if kcol is None:
            kcol = cols[0]
        if tcol is None and len(cols) >= 2:
            tcol = cols[1]
        if tcol is None:
            return {}

        m = {}
        for _, r in df.iterrows():
            key = str(r.get(kcol, "")).strip()
            full = str(r.get(tcol, "")).strip()
            prev = str(r.get(pcol, "")).strip() if pcol else ""
            if not key:
                continue
            blob = full
            if prev and prev not in blob:
                blob = f"{prev} {full}".strip()
            m[key] = blob
        return m