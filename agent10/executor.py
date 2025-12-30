# agent10/executor.py
import time
from pathlib import Path

from crm_loader import CRMLoader
from product_selector import ProductSelector
from react_reasoning_agent import ReActPlanner
from strategy_narrator import StrategyNarrator
from verifier import MessageVerifier
from openai_client import OpenAIChatCompletionClient
from tone_profiles import ToneProfiles
from market_context_tool import MarketContextTool
from brand_rules import load_brand_rules
from rule_verifier import verify_brand_rules


class Executor:
    def __init__(self, data_dir: Path, use_market_context=False, verbose=True):
        self.data_dir = Path(data_dir)
        self.use_market_context = use_market_context
        self.verbose = verbose

        self.llm = OpenAIChatCompletionClient()
        self.loader = CRMLoader(self.data_dir)
        self.tones = ToneProfiles(self.data_dir)
        self.verifier = MessageVerifier()

        self.product_selector = ProductSelector(
            self.data_dir / "amore_with_category.csv"
        )

        self.market_tool = MarketContextTool(enabled=use_market_context)

        self.brand_rules = load_brand_rules(
            str(self.data_dir / "amore_brand_tone_rules.csv")
        )

        tone_map = self.tones.load_tone_profile_map()
        self.planner = ReActPlanner(
            llm_client=self.llm,
            tone_profile_map=tone_map,
        )
        self.narrator = StrategyNarrator(
            llm_client=self.llm,
            tone_profile_map=tone_map,
        )

    def run(self, persona_id: str, topk: int = 3):
        t0 = time.time()

        if self.verbose:
            print("[executor] load rows")
        rows = self.loader.load(persona_id=persona_id, topk=topk)

        if self.verbose:
            print("[executor] load tone profiles")
        self.tones.load_tone_profiles()

        tone_map = self.tones.load_tone_profile_map()
        self.planner.tone_profile_map = tone_map
        self.narrator.tone_profile_map = tone_map

        results = []

        for i, row in enumerate(rows, 1):
            brand = str(row.get("brand", "")).strip()
            if brand not in self.brand_rules:
                raise RuntimeError(f"[executor] brand rule missing: {brand}")

            brand_rule = self.brand_rules[brand][0]

            if self.verbose:
                print(f"[executor] row {i}/{len(rows)} select product")

            product = self.product_selector.select_one(
                brand=brand,
                skin_concern=str(row.get("skin_concern", "")).strip(),
                ingredient_avoid_list=str(row.get("ingredient_avoid_list", "")).strip(),
            )
            row.update(product)

            if self.use_market_context:
                row["market_context"] = self.market_tool.fetch(brand=brand)
            else:
                row["market_context"] = {}

            if self.verbose:
                print(f"[executor] row {i}/{len(rows)} plan")
            plan = self.planner.plan(row)
            if not plan or not plan.get("message_outline"):
                raise RuntimeError("plan missing message_outline")

            if self.verbose:
                print(f"[executor] row {i}/{len(rows)} generate")
            msg = self.narrator.generate(
                row=row,
                plan=plan,
                brand_rule=brand_rule,
                repair_errors=None,
            )

            title_line, body_line = msg.split("\n", 1)
            errs = self.verifier.validate(row, title_line, body_line)

            rule_errs = verify_brand_rules(
                body_line.replace("BODY:", "", 1).strip(),
                brand_rule,
            )
            errs.extend(rule_errs)

            if errs and not getattr(self.llm, "offline", False):
                if self.verbose:
                    print(f"[executor] row {i}/{len(rows)} repair: {errs}")
                for _ in range(2):
                    msg = self.narrator.generate(
                        row=row,
                        plan=plan,
                        brand_rule=brand_rule,
                        repair_errors=errs,
                    )
                    title_line, body_line = msg.split("\n", 1)
                    errs = self.verifier.validate(row, title_line, body_line)
                    errs.extend(
                        verify_brand_rules(
                            body_line.replace("BODY:", "", 1).strip(),
                            brand_rule,
                        )
                    )
                    if not errs:
                        break

            if self.verbose and errs:
                print(f"[executor] row {i}/{len(rows)} final errs: {errs}")

            results.append(
                {
                    "persona_id": row.get("persona_id", ""),
                    "brand": brand,
                    "part_id": row.get("part_id", ""),
                    "score": row.get("score", ""),
                    "message": msg,
                    "plan": plan,
                    "errors": errs,
                }
            )

        if self.verbose:
            print(f"[executor] runtime {time.time()-t0:.2f}s")

        return results