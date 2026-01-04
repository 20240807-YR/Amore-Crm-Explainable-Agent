# -------------------------------------------------
# Persona-level brand rule filtering (post brand-sample)
# -------------------------------------------------
def _apply_persona_brand_rules(persona_id: str, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Persona-level brand filtering / deprioritization.
    This function must NOT invent brands.
    It only filters or reorders existing rows.
    """
    if not rows:
        return rows

    # Persona-specific hard rules (minimal, explicit)
    EXCLUDE_BRANDS_BY_PERSONA = {
        "persona_6": ["설화수", "헤라"],          # 가성비 → 초고가 제외
        "persona_2": ["헤라"],                    # 민감 → 향 중심 브랜드 제외
        "persona_8": ["설화수"],                  # 남성 간편 → 프리미엄 스킵
    }

    DEPRIORITIZE_BRANDS_BY_PERSONA = {
        "persona_4": ["설화수"],                  # 트러블 → 고영양 후순위
    }

    pid = str(persona_id)

    # 1) hard exclude
    banned = set(EXCLUDE_BRANDS_BY_PERSONA.get(pid, []))
    if banned:
        rows = [r for r in rows if str(r.get("brand")) not in banned]

    if not rows:
        return rows

    # 2) soft deprioritize (stable sort)
    deprioritized = set(DEPRIORITIZE_BRANDS_BY_PERSONA.get(pid, []))

    def _rank(r):
        b = str(r.get("brand"))
        return (1 if b in deprioritized else 0)

    rows = sorted(rows, key=_rank)
    return rows
import os
import time
import sys
import csv
import re
from pathlib import Path
import pandas as pd
import numpy as np
from typing import Any, Dict, List

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

# Prevent already-rendered message from being re-input to narrator
def _is_already_rendered_message(text: Any) -> bool:
    if not isinstance(text, str):
        return False
    t = text.strip()
    return t.startswith("TITLE:") and "BODY:" in t
DEFAULT_SKIN_CONCERN = "건조와 유수분 밸런스"
DEFAULT_LIFESTYLE = "일상적인 실내 생활"

# -------------------------------------------------
# Rule-based TITLE generator (controller-side only)
# -------------------------------------------------
def build_title_rule(brand: str, product_name: str, skin_concern: str = "", benefit: str = "") -> str:
    def _strip_ml(name: str) -> str:
        return re.sub(r"\s*\d+\s*ml", "", name, flags=re.I).strip()

    product_core = _strip_ml(product_name)

    if skin_concern:
        return f"✨{brand} {product_core}으로 {skin_concern} 케어✨"
    if benefit:
        return f"✨{brand} {product_core}으로 {benefit}!✨"
    return f"✨{brand} {product_core}으로 촉촉하게✨"

# -------------------------------------------------
# Controller-side CRM slot_text builder (rule-based)
# - Goal: controller must fulfill narrator contract by providing slot1_text~slot4_text.
# - Narrator should only assemble/control, not invent missing slots.
# -------------------------------------------------

_CRM_SLOT_BANNED_FRAGMENTS = [
    "오늘은",
    "중요하다",
    "필요하다",
    "어쩌라고",
    "설명",
    "관찰",
]

# -------------------------------------------------
# Slot text surface normalization (NO generation)
# -------------------------------------------------
PHRASE_NORMALIZE = {
    "야외/운동": "야외 활동이나 운동이 잦은 날",
    "야외활동/운동 잦음": "야외 활동이나 운동이 잦은 경우",
    "트러블,피지": "트러블과 피지가 함께 고민될 때",
    "아침/저녁": "아침과 저녁 모두",
    "여름 집중": "여름처럼 피부 컨디션이 쉽게 흔들리는 시기",
}

def _normalize_slot_surface(text: str) -> str:
    if not text:
        return text
    t = text
    for k, v in PHRASE_NORMALIZE.items():
        t = t.replace(k, v)
    # comma list -> conjunction
    t = re.sub(r"([가-힣]+),([가-힣]+)", r"\1과 \2", t)
    return t


def _is_ha_da_style(s: str) -> bool:
    """Heuristic: block strong declarative narration style (..이다/..다.)"""
    t = (s or "").strip()
    if not t:
        return True
    # 흔한 '이다/다.' 종결 과다를 간단히 차단
    return t.endswith("다.") or t.endswith("이다.") or t.endswith("합니다.") or t.endswith("되었습니다.")


def _has_second_person_cue(s: str) -> bool:
    t = (s or "").strip()
    if not t:
        return False
    cues = ["요즘", "이라면", "면", "때", "신경", "느껴", "다면"]
    return any(c in t for c in cues)


# -------------------------------------------------
# Slot length expanders (deterministic, no LLM)
# -------------------------------------------------
SLOT1_EXPANDERS = [
    "피부 컨디션이 흔들릴수록 관리가 더 번거롭게 느껴질 수 있어요.",
    "이럴 때일수록 루틴을 복잡하게 만들지 않는 게 중요해요.",
]

SLOT2_EXPANDERS = [
    "지금처럼 컨디션이 예민할 때도 부담 없이 사용할 수 있는 쪽이에요.",
]

SLOT3_EXPANDERS = [
    "사용 순서를 단순하게 유지하는 것만으로도 루틴 관리가 훨씬 편해져요.",
]

SLOT4_EXPANDERS = [
    "지금 리듬에 맞춰 무리 없이 이어가기 좋은 선택이에요.",
]


def build_slot_texts_rule(
    row: Dict[str, Any],
    plan: Dict[str, Any],
    product_name: str,
    brand_name_slot: str,
    brand_rule: Dict[str, Any],
) -> Dict[str, str]:
    """Deterministic slot builder.

    Returns a dict with keys: slot1_text, slot2_text, slot3_text, slot4_text.
    Each slot is a CRM utterance (not explanatory prose).
    """
    lifestyle = _norm_text(row.get("lifestyle"), DEFAULT_LIFESTYLE)
    skin_concern = _norm_text(row.get("skin_concern"), DEFAULT_SKIN_CONCERN)
    time_of_use = _norm_text(row.get("time_of_use"), "")
    seasonality = _norm_text(row.get("seasonality"), "")
    env_ctx = _norm_text(row.get("environment_context"), "")
    texture = _norm_text(row.get("texture_preference"), "")
    finish = _norm_text(row.get("finish_preference"), "")
    price_sens = _norm_text(row.get("price_sensitivity"), "")
    bundle_pref = _norm_text(row.get("bundle_preference"), "")
    cta_style = _norm_text(row.get("cta_style"), "")

    # controller-side keyword hints
    env_keywords = row.get("lifestyle_keywords") or []
    routine_phrase = _norm_text(row.get("routine_phrase"), "")

    # slot1: context (why message now)
    ctx_bits = []
    if seasonality:
        ctx_bits.append(seasonality)
    if env_ctx:
        ctx_bits.append(env_ctx)
    if env_keywords:
        ctx_bits.append(env_keywords[0])
    if lifestyle and lifestyle not in ctx_bits:
        ctx_bits.append(lifestyle)

    ctx = " · ".join([b for b in ctx_bits if b])
    if ctx:
        slot1 = f"요즘 {ctx}에서 피부가 쉽게 {skin_concern} 쪽으로 기울면, 관리가 부담스럽게 느껴질 때가 있어요."
    else:
        slot1 = f"요즘 피부가 쉽게 {skin_concern} 쪽으로 기울면, 간단한 관리부터 다시 잡고 싶어질 때가 있어요."
    if len(slot1) < 70:
        slot1 = slot1 + " " + SLOT1_EXPANDERS[0]

    # slot2: offer (why this product)
    # keep it 1~2 reasons, avoid '도움이 됩니다' style
    offer_bits = []
    if texture:
        offer_bits.append(f"{texture} 타입이라")
    if finish:
        offer_bits.append(f"마무리가 {finish}하게")

    offer_reason = " ".join(offer_bits).strip()
    if offer_reason:
        slot2 = f"그래서 {brand_name_slot}의 {product_name}은(는) {offer_reason} 루틴에 끼워 넣기 편해요."
    else:
        slot2 = f"그래서 {brand_name_slot}의 {product_name}은(는) 지금 컨디션에 맞춰 루틴에 가볍게 얹기 편해요."
    if len(slot2) < 80:
        slot2 = slot2 + " " + SLOT2_EXPANDERS[0]

    # slot3: usage flow (when/how)
    use_bits = []
    if time_of_use:
        use_bits.append(time_of_use)
    if routine_phrase:
        use_bits.append(routine_phrase)
    use_ctx = " ".join([b for b in use_bits if b]).strip()

    if use_ctx:
        slot3 = f"{use_ctx}에 손에 덜어 얇게 펴 바르고, 들뜨는 부분만 한 번 더 눌러주면 깔끔하게 마무리돼요."
    else:
        slot3 = "세안 후 바로 얇게 펴 바르고, 들뜨는 부분만 한 번 더 눌러주면 깔끔하게 마무리돼요."
    if len(slot3) < 60:
        slot3 = slot3 + " " + SLOT3_EXPANDERS[0]

    # slot4: soft close (next action without heavy CTA)
    close_bits = []
    if price_sens and "높" in price_sens:
        close_bits.append("세일 타이밍만 잘 맞추면 부담이 덜해요")
    if bundle_pref and ("세트" in bundle_pref):
        close_bits.append("세트 구성이면 루틴을 한 번에 정리하기 좋아요")
    if cta_style and ("혜택" in cta_style or "가격" in cta_style):
        close_bits.append("혜택이 있는 구간에 맞춰 가볍게 시작해도 충분해요")

    close = " · ".join(_dedup_keep_order(close_bits))
    if close:
        slot4 = f"루틴을 과하게 늘리지 말고, {close} 쪽으로만 잡아도 컨디션이 안정되는 편이에요."
    else:
        slot4 = "루틴을 과하게 늘리지 말고, 오늘 컨디션에 맞게 가볍게 이어가도 충분해요."
    if len(slot4) < 60:
        slot4 = slot4 + " " + SLOT4_EXPANDERS[0]

    # -------------------------------------------------
    # BODY-length cumulative padding (controller responsibility)
    # - Ensure total BODY length >= 300 before narrator
    # - Deterministic, no LLM, no tone/judgment sentences
    # -------------------------------------------------
    slots = [slot1, slot2, slot3, slot4]
    expanders = [SLOT1_EXPANDERS, SLOT2_EXPANDERS, SLOT3_EXPANDERS, SLOT4_EXPANDERS]

    def _body_len(ss):
        return len("".join(ss))

    i = 0
    MAX_ITERS = 20  # hard safety cap
    while _body_len(slots) < 300 and i < MAX_ITERS:
        idx = i % 4
        pool = expanders[idx]
        if pool:
            slots[idx] = slots[idx] + " " + pool[i % len(pool)]
        i += 1

    slot1, slot2, slot3, slot4 = slots
    slot1 = _normalize_slot_surface(slot1)
    slot2 = _normalize_slot_surface(slot2)
    slot3 = _normalize_slot_surface(slot3)
    slot4 = _normalize_slot_surface(slot4)

    return {
        "slot1_text": slot1.strip(),
        "slot2_text": slot2.strip(),
        "slot3_text": slot3.strip(),
        "slot4_text": slot4.strip(),
    }


def validate_slot_texts(slot_texts: Dict[str, str]) -> List[str]:
    """Return a list of errors. Empty list means OK."""
    errs: List[str] = []
    warnings: List[str] = []
    if not isinstance(slot_texts, dict):
        return ["slot_texts_not_dict"]

    required = ["slot1_text", "slot2_text", "slot3_text", "slot4_text"]
    for k in required:
        v = (slot_texts.get(k) or "").strip()
        if not v:
            errs.append(f"{k}_missing")
            continue
        if len(v) < 18:
            errs.append(f"{k}_too_short")
        if any(b in v for b in _CRM_SLOT_BANNED_FRAGMENTS):
            errs.append(f"{k}_banned_fragment")
        if _is_ha_da_style(v):
            errs.append(f"{k}_hada_style")
        # second-person cue is SOFT: do not hard-block slot validity
        # handled later as warning, not error
        pass

    return _dedup_keep_order(errs)


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


# --- New helper: normalize narrator dict output into (title_line, body_line) ---
from typing import Any, Dict
def _normalize_title_body_from_dict(d: Dict[str, Any]):
    """Normalize narrator dict output into (title_line, body_line).
    - Enforces non-empty TITLE content.
    - Strips accidental 'TITLE:'/'BODY:' prefixes inside values.
    - Falls back to parsing embedded raw text if present.
    """
    if not isinstance(d, dict):
        return "TITLE: 제목 없음", "BODY:"

    # 1) pull candidates
    title_raw = d.get("title")
    if title_raw is None:
        title_raw = d.get("title_line")

    body_raw = d.get("body")
    if body_raw is None:
        body_raw = d.get("body_line")

    # 2) normalize strings
    t = "" if title_raw is None else str(title_raw).strip()
    b = "" if body_raw is None else str(body_raw).strip()

    # strip accidental label prefixes inside values
    if t.upper().startswith("TITLE:"):
        t = t.split(":", 1)[1].strip()
    if b.upper().startswith("BODY:"):
        b = b.split(":", 1)[1].strip()

    # 3) fallback: try to parse any embedded full message string
    if (not t) or (not b):
        raw_text = d.get("message")
        if raw_text is None:
            raw_text = d.get("text")
        if raw_text is None:
            raw_text = d.get("raw")
        if raw_text is None:
            raw_text = d.get("output")
        if isinstance(raw_text, str) and raw_text.strip():
            pt, pb = _parse_title_body(raw_text)
            # pb is like 'BODY: ...'
            pb_clean = pb.replace("BODY:", "", 1).strip()
            if not t:
                t2 = pt.replace("TITLE:", "", 1).strip()
                if t2:
                    t = t2
            if not b and pb_clean:
                b = pb_clean

    # 4) final guards
    if not t:
        t = "제목 없음"

    title_line = f"TITLE: {t}" if not str(t).strip().upper().startswith("TITLE:") else str(t).strip()
    body_line = "BODY: " + (b or "").strip()

    return title_line, body_line


def _looks_like_refusal(msg: str) -> bool:
    s = (msg or "").strip()
    if not s:
        return True
    return ("요청을 처리할 수 없습니다" in s) or ("죄송합니다" in s and "TITLE:" not in s)


# --- Literal warnings detector: controller must not rewrite message content. ---
def _detect_literal_warnings(clean_body: str, brand: str, product_name: str, skin_concern: str) -> list:
    """
    Controller must not rewrite message content.
    This helper only detects potential literal/structure issues and returns warnings.
    """
    warnings = []
    body = (clean_body or "").strip()
    if not body:
        warnings.append("empty_body")
        return warnings

    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]

    if brand:
        if brand not in body:
            warnings.append("brand_missing")
        # dangling brand token line (common artifact)
        if lines and lines[-1] == brand:
            warnings.append("dangling_brand_token")

    if product_name and product_name not in body:
        warnings.append("product_missing")

    concerns = []
    for c in str(skin_concern or "").split(","):
        cc = c.strip()
        if cc:
            concerns.append(cc)
    if concerns:
        primary = concerns[0]
        if primary and primary not in body:
            warnings.append("skin_concern_missing")

    return warnings

def _ensure_required_literals(clean_body: str, brand: str, product_name: str, skin_concern: str) -> str:
    """
    Controller-side literal injection (single pass, post-narration).
    Narrator should not be forced to append dangling brand tokens.
    """
    body = (clean_body or "").strip()
    if not body:
        return body

    # Normalize lines
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    if not lines:
        return body

    # If last line is ONLY the brand token, rewrite it into a proper closing sentence.
    if brand and lines[-1] == brand:
        lines[-1] = f"{brand}로 마무리해요."

    joined = "\n".join(lines)

    # Ensure brand exists somewhere in BODY
    if brand and brand not in joined:
        lines[-1] = (lines[-1].rstrip() + f" {brand}").strip()

    joined = "\n".join(lines)

    # Ensure product anchor exists somewhere in BODY
    if product_name and product_name not in joined:
        # Prefer adding to the 2nd line if exists, else add to the last line.
        if len(lines) >= 2:
            lines[1] = (lines[1].rstrip() + f" {product_name}").strip()
        else:
            lines[-1] = (lines[-1].rstrip() + f" {product_name}").strip()

    joined = "\n".join(lines)

    # Ensure at least one skin concern token is mentioned (first concern only)
    concerns = []
    for c in str(skin_concern or "").split(","):
        cc = c.strip()
        if cc:
            concerns.append(cc)

    if concerns:
        primary = concerns[0]
        if primary and primary not in joined:
            # Add to first line to keep the flow natural (single pass append).
            lines[0] = (lines[0].rstrip() + f" ({primary})").strip()

    return "\n".join(lines)


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
    # --- FIX: explicit product dataframe injection ---
    product_df = None
    try:
        if PRODUCT_CSV_PATH.exists():
            print(f"[controller] Loading product CSV: {PRODUCT_CSV_PATH}")
            product_df = pd.read_csv(PRODUCT_CSV_PATH)
            print(f"[controller] Product CSV loaded rows={len(product_df)}")
        else:
            print(f"[controller] WARN: product CSV not found: {PRODUCT_CSV_PATH}")
    except Exception as e:
        print(f"[controller] WARN: failed to load product CSV: {e}")
        product_df = None

    selector = ProductSelector(
        df=product_df,
        name_col="상품명",
        brand_col="brand",
    )
    # --- END FIX ---
    market = MarketContextTool(enabled=use_market_context)

    # 2) load rows
    rows = loader.load(persona_id, topk) or []
    # ------------------------------------------------------------------
    # Brand-level re-sampling (anti-collapse)
    # - rows returned by CRMLoader are often part-sliced; topk becomes "row topk".
    # - We convert to "brand topk" by keeping the best row per brand, then sampling.
    # ------------------------------------------------------------------
    BRAND_CAP = {
        # tune later; only prevents a single brand from dominating purely by score
        "프리메라": 0.32,
        "메이크온": 0.32,
    }
    SOFTMAX_TEMPERATURE = 1.7

    def _brand_key(v: Any) -> str:
        return str(v).strip().replace("\u200b", "").replace("\ufeff", "").replace(" ", "") if v is not None else ""

    def _get_score(r: Dict[str, Any]) -> float:
        # prefer explicit score fields if present
        s = r.get("score")
        if s is None:
            s = r.get("final_score")
        try:
            return float(s)
        except Exception:
            return 0.0

    def _cap_score(brand: str, score: float) -> float:
        b = _brand_key(brand)
        cap = BRAND_CAP.get(b)
        return float(min(score, cap)) if cap is not None else float(score)

    def _softmax_probs(vals: List[float], temperature: float) -> List[float]:
        if not vals:
            return []
        t = float(temperature) if float(temperature) > 0 else 1.0
        x = np.array([float(v) for v in vals], dtype=np.float64) / t
        x = x - np.max(x)
        ex = np.exp(x)
        s = float(np.sum(ex))
        if s <= 0.0 or not np.isfinite(s):
            return [1.0 / len(vals)] * len(vals)
        return [float(p) for p in (ex / s).tolist()]

    if isinstance(rows, list) and rows:
        # 1) group by brand, keep only the top-scoring row per brand
        brand_best: Dict[str, Dict[str, Any]] = {}
        brand_best_score: Dict[str, float] = {}
        for r in rows:
            if not isinstance(r, dict):
                continue
            b_raw = r.get("brand", "")
            b = _brand_key(b_raw)
            sc = _get_score(r)
            if (b not in brand_best_score) or (sc > brand_best_score[b]):
                brand_best[b] = r
                brand_best_score[b] = sc

        brands = list(brand_best.keys())
        if brands:
            # 2) cap + softmax sampling over brand representative scores
            capped_scores = [_cap_score(br, brand_best_score.get(br, 0.0)) for br in brands]
            probs = _softmax_probs(capped_scores, SOFTMAX_TEMPERATURE)

            k = int(topk) if isinstance(topk, int) and topk > 0 else 3
            k = min(k, len(brands))

            # sample without replacement
            chosen_idxs: List[int] = []
            available = list(range(len(brands)))
            p = np.array(probs, dtype=np.float64)

            for _ in range(k):
                if len(available) == 1:
                    chosen_idxs.append(available[0])
                    break
                p_rem = p[available]
                s_rem = float(np.sum(p_rem))
                if s_rem <= 0.0 or not np.isfinite(s_rem):
                    idx = int(np.random.choice(available))
                else:
                    p_rem = p_rem / s_rem
                    idx = int(np.random.choice(available, p=p_rem))
                chosen_idxs.append(idx)
                available.remove(idx)

            chosen_brands = [brands[i] for i in chosen_idxs]
            rows = [brand_best[b] for b in chosen_brands]

            if verbose:
                dbg = [(brand_best[b].get("brand"), _get_score(brand_best[b])) for b in chosen_brands]
                print(f"[controller] brand-resample -> {dbg}")
    # -------------------------------------------------
    # Persona-level brand rule filtering (post brand-sample)
    # -------------------------------------------------
    # -------------------------------------------------
    # Data integrity safety belt:
    # Drop brands that have ZERO products in product CSV
    # -------------------------------------------------
    if isinstance(rows, list) and rows and product_df is not None:
        # Build set of brands that actually exist in product_df
        try:
            valid_brands = set(
                str(b).strip()
                for b in product_df["brand"].dropna().unique().tolist()
            )
        except Exception:
            valid_brands = set()

        if valid_brands:
            rows = [
                r for r in rows
                if str(r.get("brand", "")).strip() in valid_brands
            ]
    rows = _apply_persona_brand_rules(persona_id, rows)

    if verbose:
        print("[controller] persona-brand-filter ->", [(r.get("brand"), r.get("score")) for r in rows])
    # ------------------------------------------------------------------
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

        # slot2 should treat routine/time cues as *optional hints* (not hard constraints)
        r["routine_keywords"] = routine_kw

        rp = _extract_routine_phrase(routine_kw)
        # keep backward compatibility, but narrator/planner should prefer slot2_hints
        r["routine_phrase"] = rp
        r["slot2_hints"] = [rp] if rp else []

    planner = ReActReasoningAgent(llm, tone_map)
    narrator = StrategyNarrator(
        llm=llm,
        tone_profile_map=tone_map,
        pad_pool=None,
    )

    results = []

    # 3) loop
    def _is_final_message(text: str) -> bool:
        if not isinstance(text, str):
            return False
        t = text.strip()
        return t.startswith("TITLE:") and "BODY:" in t

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
            # Compatibility: controller prefers selector.select_one(row) -> dict with "상품명"
            # Some local debug versions may expose select_product(row, topk) -> (name, score)
            if hasattr(selector, "select_one"):
                product = selector.select_one(row=row) or {}
                product_name = _s(product.get("상품명"))
            elif hasattr(selector, "select_product"):
                chosen_name, chosen_score = selector.select_product(row=row, topk=topk)
                product_name = _s(chosen_name)
                # Keep a dict-like product for downstream if needed
                product = {"상품명": product_name, "_score": float(chosen_score)}
            else:
                raise AttributeError("ProductSelector must expose select_one(row) or select_product(row, topk)")
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

        # -------------------------------------------------
        # TITLE 결정 로직 (rule-based, controller only)
        # -------------------------------------------------
        title_text = build_title_rule(
            brand=brand,
            product_name=product_name,
            skin_concern=row.get("skin_concern", ""),
            benefit=row.get("benefit", ""),
        )
        # brand_name_slot 결정: 제품 기준 노출 브랜드 분기
        product_anchor = row.get("상품명") or row.get("product_anchor", "")

        if product_anchor and "메이크온" in product_anchor:
            row["brand_name_slot"] = "메이크온"
        else:
            row["brand_name_slot"] = brand
        row["market_context"] = market.fetch(brand) if use_market_context else {}

        if verbose:
            print(f"[controller] row {i}/{len(rows)} plan")

        plan = planner.plan(row)
        # Inject rule-based TITLE into plan after planning, before narrator
        plan["title"] = title_text
        # ensure narration row is always defined
        narr_row = dict(row)
        # --- normalize outline to slot tags (reduce semantic over-specification) ---
        # We keep a stable 4-slot ordering to allow freer wording inside each slot.
        plan["message_outline"] = [
            "slot1_environment",
            "slot2_offer",
            "slot3_usage_flow",
            "slot4_soft_close",
        ]

        # -------------------------------------------------
        # NEW: controller must fulfill narrator contract by providing slot1_text~slot4_text.
        # Rule-based first (deterministic), avoid narrator-side invention.
        # -------------------------------------------------
        slot_texts = build_slot_texts_rule(
            row=row,
            plan=plan,
            product_name=product_name,
            brand_name_slot=row.get("brand_name_slot", brand),
            brand_rule=brand_rule,
        )
        slot_errs = validate_slot_texts(slot_texts)
        if slot_errs:
            results.append({
                "persona_id": row.get("persona_id"),
                "brand": brand,
                "message": "",
                "errors": ["invalid_or_insufficient_crm_slots"] + slot_errs,
                "plan": plan,
                "row": row,
                "brand_rule": brand_rule,
            })
            continue

        # inject slots into plan for StrategyNarrator
        plan.update(slot_texts)

        # --- controller contract enforcement (slot safety) ---
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
        plan["brand_must_include_raw"] = str(must_include)
        plan["brand_must_include"] = [w.strip() for w in str(must_include).split(",") if w.strip()]

        if verbose:
            print(f"[controller] row {i}/{len(rows)} generate")

        # --- narration row sanitization (marketing context) ---
        # narr_row is already defined above
        # Anti-aging / dry-skin persona guardrail
        skin_concern_raw = str(row.get("skin_concern", ""))
        if "주름" in skin_concern_raw or "탄력" in skin_concern_raw or "건성" in skin_concern_raw:
            narr_row["skin_concern"] = "주름,탄력,속건조"
            # remove acne/oil language from narration context
            for bad_kw in ["트러블", "피지", "유분", "산뜻"]:
                narr_row["skin_concern"] = narr_row["skin_concern"].replace(bad_kw, "")
            narr_row["message_tone_preference"] = "고급/집중케어"

        # [CONTROLLER GUARD] 이미 완성된 메시지가 narrator 입력으로 재유입되는 것을 차단
        if _is_already_rendered_message(narr_row.get("message")):
            narr_row["message"] = ""
        if _is_already_rendered_message(narr_row.get("raw_text")):
            narr_row["raw_text"] = ""

        # narrator skip condition respects title existence and slot completion
        if not title_text or any(k not in plan for k in ["slot1_text","slot2_text","slot3_text","slot4_text"]):
            continue
        msg = narrator.generate(row=narr_row, plan=plan, brand_rule=brand_rule)

        # [CONTROLLER GUARD] narrator 결과가 다시 중첩되지 않도록 보정
        if isinstance(msg, str) and msg.count("TITLE:") > 1:
            first = msg.find("TITLE:")
            second = msg.find("TITLE:", first + 6)
            if second != -1:
                msg = msg[:second].strip()

        # StrategyNarrator may return a structured dict.
        # Controller must enforce a clean (TITLE line, BODY line) contract here.
        if isinstance(msg, dict):
            _, body = _normalize_title_body_from_dict(msg)
        else:
            _, body = _parse_title_body(msg)

        title = f"TITLE: {title_text}"

        clean_body = body.replace("BODY:", "", 1).strip()
        MIN_BODY_LEN = 300

        # Hard block: too-short body should fail fast here.
        # Controller should not re-invoke narrator for expansion/fallback at this stage.
        if (not clean_body) or (len(clean_body) < MIN_BODY_LEN):
            results.append({
                "persona_id": row.get("persona_id"),
                "brand": brand,
                "message": "",
                "errors": ["body_too_short(hard_block)", f"body_len={len(clean_body)}"],
                "plan": plan,
                "row": row,
                "brand_rule": brand_rule,
            })
            continue

        # -------------------------------------------------
        # Slot-to-slot discourse glue (surface-level only)
        # - Do NOT rewrite content
        # - Deterministic prefix injection per slot line
        # -------------------------------------------------
        SLOT_GLUE = [
            "",                 # slot1: 그대로 시작
            "그래서 ",           # slot2
            "이후에는 ",         # slot3
            "이런 흐름이라면 ",  # slot4
        ]

        _lines = [ln.strip() for ln in clean_body.splitlines() if ln.strip()]
        _glued = []
        for idx, ln in enumerate(_lines):
            prefix = SLOT_GLUE[idx] if idx < len(SLOT_GLUE) else ""
            if prefix and ln.startswith(prefix.strip()):
                prefix = ""
            _glued.append(prefix + ln)
        clean_body = "\n".join(_glued)

        body = "BODY: " + clean_body

        # Controller must not rewrite body content.
        # Detect only and attach warnings for downstream inspection.
        literal_warnings = _detect_literal_warnings(
            clean_body,
            brand,
            product_name,
            row.get("skin_concern", ""),
        )
        # (1) body_len>350 literal warning
        if len(clean_body) > 350:
            literal_warnings.append("body_len>350")

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
            "warnings": literal_warnings,
            "plan": plan,
            "row": row,
            "brand_rule": brand_rule,
        })

    if verbose:
        print(f"[controller] DONE {time.time() - t0:.2f}s")

    return results