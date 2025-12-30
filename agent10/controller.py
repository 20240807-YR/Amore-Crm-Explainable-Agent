import os, time
from pathlib import Path
import pandas as pd

from crm_loader import CRMLoader
from product_selector import ProductSelector
from react_reasoning_agent import ReActReasoningAgent
from strategy_narrator import StrategyNarrator
from openai_client import OpenAIChatCompletionClient
from verifier import MessageVerifier
from tone_profiles import ToneProfiles
from market_context_tool import MarketContextTool
from agent10.brand_rules import load_brand_rules

DATA_DIR = Path("./data")
RULES_PATH = DATA_DIR / "amore_brand_tone_rules.csv"


def main(persona_id, topk=3, use_market_context=False, verbose=True):
    t0 = time.time()
    if verbose:
        print("[controller] START")
        print("[controller] OPENAI_OFFLINE:", os.getenv("OPENAI_OFFLINE", "0"))

    brand_rules = load_brand_rules(str(RULES_PATH))

    llm = OpenAIChatCompletionClient()
    loader = CRMLoader(DATA_DIR)
    tones = ToneProfiles(DATA_DIR)
    verifier = MessageVerifier()
    selector = ProductSelector()
    market = MarketContextTool(enabled=use_market_context)

    rows = loader.load(persona_id, topk)
    tone_map = tones.load_tone_profile_map()

    planner = ReActReasoningAgent(llm, tone_map)
    narrator = StrategyNarrator(llm, tone_profile_map=tone_map)

    results = []

    for i, row in enumerate(rows, 1):
        if verbose:
            print(f"[controller] row {i}/{len(rows)} select product")

        row.update(selector.select_one(row))

        brand = str(row.get("brand", "")).strip()
        if brand not in brand_rules:
            raise RuntimeError(f"[controller] brand rule missing: {brand}")

        brand_rule = brand_rules[brand][0]

        row["market_context"] = (
            market.fetch(brand) if use_market_context else {}
        )

        if verbose:
            print(f"[controller] row {i}/{len(rows)} plan")
        plan = planner.plan(row)

        if verbose:
            print(f"[controller] row {i}/{len(rows)} generate")
        msg = narrator.generate(row, plan, brand_rule)

        title, body = msg.split("\n", 1)
        errs = verifier.validate(row, title, body)

        if errs and not getattr(llm, "offline", False):
            for _ in range(2):
                msg = narrator.generate(row, plan, brand_rule, repair_errors=errs)
                title, body = msg.split("\n", 1)
                errs = verifier.validate(row, title, body)
                if not errs:
                    break

        results.append({
            "persona_id": row.get("persona_id"),
            "brand": brand,
            "score": row.get("score"),
            "message": msg,
            "plan": plan,
            "errors": errs,
        })

    if verbose:
        print(f"[controller] DONE {time.time()-t0:.2f}s")

    return results