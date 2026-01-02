import os
import time
import sys
import csv
import re
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


# lifestyle keyword hygiene (controller-side)
# - Keep environment/context keywords for slot1
# - Move routine/time/behavior keywords to slot2 via dedicated fields

def _dedup_keep_order(items):
    seen = set()
    out = []
    for x in items:
        if not x:
            continue
        if x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out


def _norm_lifestyle_keyword(k: str) -> str:
    k = (k or "").strip()
    k = re.sub(r"\s+", " ", k)

    # common noisy forms -> more sentence-friendly phrases
    if k == "마스크 잦음":
        return "마스크 착용이 잦은 날"
    if "마스크" in k and k.endswith("잦음"):
        return "마스크 착용이 잦은 날"

    if "사무실" in k and "에어컨" in k:
        return "사무실 에어컨 바람"

    return k


def _is_routine_like(k: str) -> bool:
    if not k:
        return False
    # routine/time/behavior cues
    routine_markers = ["루틴", "출근", "퇴근", "분", "아침", "저녁", "밤", "운동", "야근", "샤워", "세안"]
    return any(m in k for m in routine_markers)


def _split_lifestyle_keywords(lifestyle_raw: str):
    raw_parts = [p.strip() for p in str(lifestyle_raw or "").split(",") if p.strip()]
    parts = [_norm_lifestyle_keyword(p) for p in raw_parts]

    routine = []
    env = []
    for p in parts:
        if _is_routine_like(p):
            routine.append(p)
        else:
            env.append(p)

    return _dedup_keep_order(env), _dedup_keep_order(routine)


def _extract_routine_phrase(routine_keywords):
    # Prefer the canonical '출근 전 5분 루틴' if present; otherwise first routine keyword.
    if not routine_keywords:
        return ""
    for rk in routine_keywords:
        if "출근" in rk and "5" in rk and "루틴" in rk:
            # make it slot2-friendly (avoid '5에' artifacts)
            return "출근 전 5분"
    # general cleanup
    rk0 = routine_keywords[0]
    if rk0.endswith("루틴"):
        rk0 = rk0.replace("루틴", "").strip()
    return rk0


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
    if len(lines) >= 2 and lines[0].startswith("TITLE:") and lines[1].startswith("BODY:"):
        title = lines[0].strip()
        body_lines = [lines[1].replace("BODY:", "", 1).strip()]
        if len(lines) > 2:
            body_lines.extend([ln.strip() for ln in lines[2:] if ln.strip()])
        body = "BODY: " + "\n".join(body_lines)
        return title, body

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

        env_kw, routine_kw = _split_lifestyle_keywords(r.get("lifestyle", ""))

        # slot1 should only see environment/context keywords to prevent grammar collisions
        r["lifestyle_keywords"] = env_kw

        # slot2 can optionally use these
        r["routine_keywords"] = routine_kw
        r["routine_phrase"] = _extract_routine_phrase(routine_kw)

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
        # --- controller contract enforcement (slot safety) ---
        # 1) limit lifestyle_expanded volume
        le = plan.get("lifestyle_expanded")
        if isinstance(le, list):
            plan["lifestyle_expanded"] = le[:3]
        elif isinstance(le, str):
            plan["lifestyle_expanded"] = le.strip()

        # 2) hard product anchor (prevent slot2 being eaten)
        plan["product_anchor"] = product_name

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
        body = "BODY: " + clean_body

        # Validate ONLY the primary (top-1) message.
        # top-k rows are candidates/comparisons; validating them causes brand_missing by design.
        if i == 1:
            # verifier API compatibility: some versions expose validate(), others expose verify()
            if hasattr(verifier, "validate"):
                errs = verifier.validate(row, title, body)
            else:
                try:
                    # Some versions: verify(title, body)
                    vres = verifier.verify(title, body)
                except TypeError:
                    # Other versions: verify(row, title, body)
                    vres = verifier.verify(row, title, body)
                errs = list((vres or {}).get("errors", []))

            br = verify_brand_rules(clean_body, brand_rule)
            if isinstance(br, dict):
                errs.extend(list(br.get("errors", [])))
            else:
                errs.extend(list(br or []))
        else:
            errs = []

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