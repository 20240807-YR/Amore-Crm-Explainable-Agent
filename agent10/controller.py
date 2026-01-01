import os
import time
import sys
import csv
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"
RULES_PATH = DATA_DIR / "amore_brand_tone_rules.csv"
PRODUCT_CSV_PATH = DATA_DIR / "amore_with_category.csv"

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


# -------------------------------------------------
# helpers
# -------------------------------------------------
DEFAULT_SKIN_CONCERN = "건조와 유수분 밸런스"
DEFAULT_LIFESTYLE = "일상적인 실내 생활"


def normalize_brand(b):
    if not b:
        return ""
    return str(b).strip().replace("\u200b", "").replace("\ufeff", "")


def _s(v):
    return "" if v is None else str(v).strip()


def _norm_text(v, default=""):
    s = _s(v)
    if not s:
        return default
    if s.lower() == "nan":
        return default
    return s


def _is_empty_product(v) -> bool:
    s = _s(v)
    return (not s) or (s.lower() == "nan")


def _parse_title_body(msg: str):
    s = (msg or "").strip()
    if not s:
        return "TITLE: 제목 없음", "BODY:"

    lines = s.splitlines()
    if (
        len(lines) >= 2
        and lines[0].startswith("TITLE:")
        and lines[1].startswith("BODY:")
    ):
        return lines[0].strip(), lines[1].strip()

    return "TITLE: 제목 없음", "BODY: " + s


def _looks_like_refusal(msg: str) -> bool:
    s = (msg or "").strip()
    if not s:
        return True
    return ("요청을 처리할 수 없습니다" in s) or ("죄송합니다" in s and "TITLE:" not in s)


def _choose_brand_rule(brand_rule_list, i: int):
    if not brand_rule_list:
        return None
    try:
        return brand_rule_list[(i - 1) % len(brand_rule_list)]
    except Exception:
        return brand_rule_list[0]


# -------------------------------------------------
# product fallback (raw csv, no pandas)
# -------------------------------------------------
_PRODUCT_NAME_CACHE = None


def _load_product_name_cache():
    global _PRODUCT_NAME_CACHE
    if _PRODUCT_NAME_CACHE is not None:
        return _PRODUCT_NAME_CACHE

    names = []
    try:
        if PRODUCT_CSV_PATH.exists():
            with PRODUCT_CSV_PATH.open("r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                if not reader.fieldnames:
                    _PRODUCT_NAME_CACHE = []
                    return _PRODUCT_NAME_CACHE

                # normalize headers
                field_map = {fn: (fn or "").strip() for fn in reader.fieldnames}

                # find "상품명"
                name_key = None
                for k, v in field_map.items():
                    if v == "상품명":
                        name_key = k
                        break

                if not name_key:
                    _PRODUCT_NAME_CACHE = []
                    return _PRODUCT_NAME_CACHE

                for row in reader:
                    raw = row.get(name_key, "")
                    nm = (raw or "").strip()
                    if nm and nm.lower() != "nan":
                        names.append(nm)
    except Exception:
        names = []

    _PRODUCT_NAME_CACHE = names
    return _PRODUCT_NAME_CACHE


def _global_product_fallback() -> str:
    names = _load_product_name_cache()
    for nm in names:
        s = nm.strip()
        if s and s.lower() != "nan":
            return s
    return ""


# -------------------------------------------------
# brand must-include enforcement
# -------------------------------------------------
def enforce_brand_must_include(body: str, must_words):
    if not body or not must_words:
        return body

    missing = [w for w in must_words if w and (w not in body)]
    if not missing:
        return body

    addon = " 이 과정에서 " + ", ".join(missing) + " 측면에서도 부담 없이 이어갈 수 있다."

    new_body = body.rstrip()
    if not new_body.endswith("."):
        new_body += "."
    new_body += addon
    return new_body.strip()


# -------------------------------------------------
# main
# -------------------------------------------------
def main(persona_id, topk=3, use_market_context=False, verbose=True):
    t0 = time.time()

    if verbose:
        print("[controller] START")
        print("[controller] OPENAI_OFFLINE:", os.getenv("OPENAI_OFFLINE", "0"))
        print(f"[controller] DATA_DIR: {DATA_DIR}")

    # 1) rules/tools
    brand_rules = load_brand_rules(RULES_PATH)
    if verbose:
        print("[controller] loaded brand rules:", list(brand_rules.keys()))

    llm = OpenAIChatCompletionClient()
    # --- LLM compatibility patch (keep logic; only adapt call shape) ---
    if not hasattr(llm, "generate"):
        if hasattr(llm, "invoke"):
            def _generate_adapter(*args, **kwargs):
                if "messages" in kwargs and isinstance(kwargs["messages"], list):
                    return llm.invoke(messages=kwargs["messages"], temperature=kwargs.get("temperature"))
                if len(args) == 2 and all(isinstance(x, str) for x in args):
                    system, user = args
                    return llm.invoke(
                        messages=[
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        temperature=kwargs.get("temperature"),
                    )
                if len(args) == 1 and isinstance(args[0], str):
                    return llm.invoke(
                        messages=[{"role": "user", "content": args[0]}],
                        temperature=kwargs.get("temperature"),
                    )
                return llm.invoke(*args, **kwargs)

            llm.generate = _generate_adapter
        elif hasattr(llm, "__call__"):
            llm.generate = llm
        elif hasattr(llm, "chat"):
            llm.generate = llm.chat
        else:
            raise AttributeError("OpenAIChatCompletionClient has no callable interface")
    # ---------------------------------------------------
    loader = CRMLoader()
    tones = ToneProfiles(DATA_DIR)
    verifier = MessageVerifier()
    selector = ProductSelector()
    market = MarketContextTool(enabled=use_market_context)

    # 2) load rows
    rows = loader.load(persona_id, topk) or []
    tone_map = tones.load_tone_profile_map()

    # ✅ 입력 결손 보정은 "여기서" 고정 (planner/narrator/verifier 공통 입력)
    for r in rows:
        if not isinstance(r, dict):
            continue
        r["skin_concern"] = _norm_text(r.get("skin_concern"), DEFAULT_SKIN_CONCERN)
        r["lifestyle"] = _norm_text(r.get("lifestyle"), DEFAULT_LIFESTYLE)

    planner = ReActReasoningAgent(llm, tone_map)
    narrator = StrategyNarrator(llm, tone_profile_map=tone_map)

    results = []

    # 3) loop
    for i, row in enumerate(rows, 1):
        if verbose:
            print(f"[controller] row {i}/{len(rows)} select product")

        raw_brand = row.get("brand", "")
        brand = normalize_brand(raw_brand)

        # brand rule pick
        brand_rule_list = brand_rules.get(brand)
        brand_rule = _choose_brand_rule(brand_rule_list, i)
        if not brand_rule:
            # 최소 필드 보장
            brand_rule = {
                "brand": brand,
                "viewpoint": "",
                "opening": "",
                "routine": "",
                "closing": "",
                "style_note": "",
                "banned": "",
                "must_include": "",
                "avoid": "",
            }

        # product select (with fallback)
        product_err = None
        product_name = ""
        try:
            product = selector.select_one(row=row) or {}
            product_name = _s(product.get("상품명"))
        except Exception as e:
            product_err = f"product_selector_failed: {e}"
            product_name = ""

        if _is_empty_product(product_name):
            fb = _global_product_fallback()
            if not _is_empty_product(fb):
                product_name = fb

        if _is_empty_product(product_name):
            errs = ["product_missing(hard_block)"]
            if product_err:
                errs.insert(0, product_err)
            results.append({
                "persona_id": row.get("persona_id"),
                "brand": brand,
                "message": "",
                "errors": errs,
            })
            continue

        row["상품명"] = product_name
        row["brand_name_slot"] = brand
        row["market_context"] = market.fetch(brand) if use_market_context else {}

        if verbose:
            print(f"[controller] row {i}/{len(rows)} plan")

        plan = planner.plan(row)
        if not plan or not plan.get("message_outline"):
            results.append({
                "persona_id": row.get("persona_id"),
                "brand": brand,
                "message": "",
                "errors": ["plan_missing"],
            })
            continue

        # must include -> plan
        must_include = brand_rule.get("must_include", "")
        plan["brand_must_include"] = [
            w.strip() for w in str(must_include).split(",") if w.strip()
        ]

        if verbose:
            print(f"[controller] row {i}/{len(rows)} generate")

        msg = narrator.generate(row=row, plan=plan, brand_rule=brand_rule)

        # StrategyNarrator returns dict; controller legacy expects string
        if isinstance(msg, dict):
            title = msg.get("title_line", "TITLE:")
            body = msg.get("body_line", "BODY:")
        else:
            title, body = _parse_title_body(msg)

        clean_body = body.replace("BODY:", "", 1).strip()
        clean_body = enforce_brand_must_include(clean_body, plan.get("brand_must_include") or [])
        body = "BODY: " + clean_body

        errs = verifier.validate(row, title, body)
        errs.extend(verify_brand_rules(clean_body, brand_rule))

        _refusal_text = msg
        if isinstance(msg, dict):
            _refusal_text = msg.get("body") or msg.get("body_line") or ""
        if _looks_like_refusal(_refusal_text if isinstance(_refusal_text, str) else str(_refusal_text)):
            errs = list(errs) + ["llm_refusal_like"]

        results.append({
            "persona_id": row.get("persona_id"),
            "brand": brand,
            "message": f"{title}\n{body}",
            "errors": errs,
            "plan": plan,
            "row": row,
            "brand_rule": brand_rule,
        })

    if verbose:
        print(f"[controller] DONE {time.time() - t0:.2f}s")

    return results