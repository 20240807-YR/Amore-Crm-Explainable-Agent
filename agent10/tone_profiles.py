# tone_profiles.py
from pathlib import Path
import pandas as pd
import sys

class ToneProfiles:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        print(f"[ToneProfiles] initialized with data_dir={self.data_dir}", file=sys.stderr)

    def _read_csv(self, name):
        p = self.data_dir / name
        if not p.exists():
            print(f"[ToneProfiles] CSV not found: {p}", file=sys.stderr)
            return None
        df = pd.read_csv(p)
        print(f"[ToneProfiles] loaded CSV: {p} rows={len(df)}", file=sys.stderr)
        return df

    def load_tone_profiles(self):
        print("[ToneProfiles] load_tone_profiles()", file=sys.stderr)
        df = self._read_csv("brand_tone_definitions.csv")
        if df is None:
            df = self._read_csv("tone_centroid_profile.csv")
        if df is None:
            df = self._read_csv("brand_tone_cluster.csv")
        if df is not None:
            print(f"[ToneProfiles] tone profiles loaded rows={len(df)}", file=sys.stderr)
        return df if df is not None else pd.DataFrame()

    def load_tone_profile_map(self):
        print("[ToneProfiles] load_tone_profile_map()", file=sys.stderr)
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
        print(f"[ToneProfiles] tone profile map size={len(m)}", file=sys.stderr)
        return m


# Standalone execution block for testing/logging
if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--data_dir", required=True)
    args = ap.parse_args()

    tp = ToneProfiles(args.data_dir)
    df = tp.load_tone_profiles()
    mp = tp.load_tone_profile_map()

    print("rows:", len(df))
    print("map_keys:", list(mp.keys())[:5])