import os, time
from pathlib import Path

from crm_loader import CRMLoader
from product_selector import ProductSelector
from react_reasoning_agent import ReActReasoningAgent
from strategy_narrator import StrategyNarrator
from openai_client import OpenAIChatCompletionClient
from verifier import MessageVerifier
from tone_profiles import ToneProfiles
from market_context_tool import MarketContextTool

DATA_DIR = Path("/Users/mac/Desktop/AMORE/Amore-Crm-Explainable-Agent/data")

def main(persona_id, topk=3, use_market_context=False, verbose=True):
    t0 = time.time()
    if verbose:
        print("[controller] START")
        print("[controller] OPENAI_OFFLINE:", os.getenv("OPENAI_OFFLINE", "0"))

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

        row["market_context"] = (
            market.fetch(str(row.get("brand", "")).strip())
            if use_market_context else {}
        )

        if verbose:
            print(f"[controller] row {i}/{len(rows)} plan")
        plan = planner.plan(row)

        if verbose:
            print(f"[controller] row {i}/{len(rows)} generate")
        msg = narrator.generate(row, plan)

        title, body = msg.split("\n", 1)
        errs = verifier.validate(row, title, body)

        if errs and not getattr(llm, "offline", False):
            for _ in range(2):
                msg = narrator.generate(row, plan, repair_errors=errs)
                title, body = msg.split("\n", 1)
                errs = verifier.validate(row, title, body)
                if not errs:
                    break

        results.append({
            "persona_id": row.get("persona_id"),
            "brand": row.get("brand"),
            "score": row.get("score"),
            "message": msg,
            "plan": plan,
            "errors": errs,
        })

    if verbose:
        print(f"[controller] DONE {time.time()-t0:.2f}s")

    return results