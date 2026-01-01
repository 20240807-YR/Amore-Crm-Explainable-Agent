import os
import time
import sys
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"
RULES_PATH = DATA_DIR / "amore_brand_tone_rules.csv"

if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from crm_loader import CRMLoader
from product_selector import ProductSelector
from react_reasoning_agent import ReActReasoningAgent
from strategy_narrator import StrategyNarrator
from openai_client import OpenAIChatCompletionClient
from verifier import MessageVerifier, verify_brand_rules
from tone_profiles import ToneProfiles
from market_context_tool import MarketContextTool
from brand_rules import load_brand_rules


def normalize_brand(b):
    if not b:
        return ""
    return str(b).strip().replace("\u200b", "").replace("\ufeff", "")


def main(persona_id, topk=3, use_market_context=False, verbose=True):
    t0 = time.time()

    if verbose:
        print("[controller] START")
        print("[controller] OPENAI_OFFLINE:", os.getenv("OPENAI_OFFLINE", "0"))
        print(f"[controller] DATA_DIR: {DATA_DIR}")

    # -------------------------------------------------
    # 1. Load rules / tools
    # -------------------------------------------------
    brand_rules = load_brand_rules(RULES_PATH)
    if verbose:
        print("[controller] loaded brand rules:", list(brand_rules.keys()))

    llm = OpenAIChatCompletionClient()
    loader = CRMLoader()
    tones = ToneProfiles(DATA_DIR)
    verifier = MessageVerifier()
    selector = ProductSelector()
    market = MarketContextTool(enabled=use_market_context)

    rows = loader.load(persona_id, topk)
    tone_map = tones.load_tone_profile_map()

    planner = ReActReasoningAgent(llm, tone_map)
    narrator = StrategyNarrator(llm, tone_profile_map=tone_map)

    results = []

    # -------------------------------------------------
    # 2. Main loop
    # -------------------------------------------------
    for i, row in enumerate(rows, 1):
        if verbose:
            print(f"[controller] row {i}/{len(rows)} select product")

        raw_brand = row.get("brand", "")
        brand = normalize_brand(raw_brand)

        # ---------------------------
        # 브랜드 규칙 로딩
        # ---------------------------
        brand_rule_list = brand_rules.get(brand)
        if brand_rule_list:
            brand_rule = brand_rule_list[0]
        else:
            if verbose:
                print(
                    f"[Warning] 브랜드 규칙 없음 → fallback | "
                    f"raw='{raw_brand}' normalized='{brand}'"
                )
            brand_rule = {
                "brand": brand,
                "viewpoint": "뷰티 카운셀러",
                "opening": "",
                "routine": "",
                "closing": "",
                "style_note": "",
                "banned": "",
                "must_include": "",
                "avoid": "",
            }

        # ---------------------------
        # 상품 선택
        # ---------------------------
        product = selector.select_one(row=row)
        row.update(product)

        # 🔥 브랜드 명시 강제 슬롯 (narrator에서 활용)
        row["brand_name_slot"] = brand

        # ---------------------------
        # 시장 맥락
        # ---------------------------
        row["market_context"] = (
            market.fetch(brand) if use_market_context else {}
        )

        if verbose:
            print(f"[controller] row {i}/{len(rows)} plan")

        # ---------------------------
        # ReAct Plan
        # ---------------------------
        plan = planner.plan(row)
        if not plan or not plan.get("message_outline"):
            if verbose:
                print(f"[Error] Plan generation failed for brand={brand}")
            continue

        # 🔥 브랜드 필수어를 plan으로 명시적으로 내려보냄
        must_include = brand_rule.get("must_include", "")
        if must_include:
            plan["brand_must_include"] = [
                w.strip() for w in str(must_include).split(",") if w.strip()
            ]
        else:
            plan["brand_must_include"] = []

        if verbose:
            print(f"[controller] row {i}/{len(rows)} generate")

        # ---------------------------
        # 1차 생성
        # ---------------------------
        msg = narrator.generate(
            row=row,
            plan=plan,
            brand_rule=brand_rule,
            repair_errors=None,
        )

        try:
            title, body = msg.split("\n", 1)
        except Exception:
            title = "TITLE: 제목 없음"
            body = "BODY: " + msg

        # ---------------------------
        # 1차 검증
        # ---------------------------
        errs = verifier.validate(row, title, body)
        clean_body = body.replace("BODY:", "", 1).strip()
        errs.extend(verify_brand_rules(clean_body, brand_rule))

        final_errs = list(errs)
        retry_count = 0

        # ---------------------------
        # Retry (Self-Repair)
        # ---------------------------
        if final_errs and not getattr(llm, "offline", False):
            for retry_cnt in range(1, 3):
                retry_count = retry_cnt
                if verbose:
                    print(f"[controller] retry {retry_cnt} due to errors: {final_errs}")

                msg = narrator.generate(
                    row=row,
                    plan=plan,
                    brand_rule=brand_rule,
                    repair_errors=final_errs,
                )

                try:
                    title, body = msg.split("\n", 1)
                except Exception:
                    title = "TITLE: 제목 없음"
                    body = "BODY: " + msg

                new_errs = verifier.validate(row, title, body)
                clean_body = body.replace("BODY:", "", 1).strip()
                new_errs.extend(verify_brand_rules(clean_body, brand_rule))

                if not new_errs:
                    final_errs = []
                    break

                final_errs = new_errs

        # ---------------------------
        # 결과 기록 (🔥 최종 상태만 저장)
        # ---------------------------
        results.append({
            "persona_id": row.get("persona_id"),
            "brand": brand,
            "score": row.get("score"),
            "row": row,                 # 실제 검증에 사용된 row
            "message": msg,
            "plan": plan,
            "errors": final_errs,        # 🔥 최종 오류만
            "retry_count": retry_count,
        })

    if verbose:
        print(f"[controller] DONE {time.time()-t0:.2f}s")

    return results