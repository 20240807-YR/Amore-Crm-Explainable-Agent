import pandas as pd
from pathlib import Path
import re
import unicodedata

# [경로 설정] 현재 파일 위치(agent10)를 기준으로 data 폴더 자동 탐색
BASE_DIR = Path(__file__).resolve().parent        # agent10/
ROOT_DIR = BASE_DIR.parent                        # project root
DATA_DIR = ROOT_DIR / "data"                      # data/

RULES_CSV = DATA_DIR / "amore_brand_tone_rules.csv"

# -------------------------------------------------
# 핵심: brand 문자열 정규화 (CSV/row 양쪽에서 "완전히 동일"하게 맞추기)
# - strip()만으로 안 잡히는 유니코드 공백/제로폭/nbps 등 제거
# - CSV에서 BOM/제어문자 섞여도 키 매칭이 깨지지 않게
# -------------------------------------------------
_ZERO_WIDTH = [
    "\u200b",  # zero width space
    "\u200c",  # zwnj
    "\u200d",  # zwj
    "\ufeff",  # BOM
]

def normalize_brand(v) -> str:
    if v is None:
        return ""
    s = str(v)
    # 유니코드 정규화
    s = unicodedata.normalize("NFKC", s)
    # 제로폭 문자 제거
    for z in _ZERO_WIDTH:
        s = s.replace(z, "")
    # 양끝 공백 제거 + 내부 다중 공백 정리(브랜드명은 보통 공백이 없지만, 혹시 모를 케이스 방어)
    s = s.strip()
    s = re.sub(r"\s+", " ", s)
    return s

def load_brand_rules(csv_path=RULES_CSV) -> dict:
    """
    브랜드 톤 앤 매너 규칙 CSV 파일을 로드합니다.
    입력값 csv_path는 Path 객체일 수도 있고, 문자열(str)일 수도 있습니다.
    """

    # 입력값이 문자열(str)이면 Path 객체로 변환합니다.
    if isinstance(csv_path, str):
        csv_path = Path(csv_path)

    if not csv_path.exists():
        raise FileNotFoundError(f"[brand_rules] CSV 파일을 찾을 수 없습니다: {csv_path}")

    # CSV 로드
    df = pd.read_csv(csv_path)

    # 필수 컬럼 체크
    required = [
        "brand",
        "opening",
        "product_link",
        "routine",
        "closing",
        "banned",
        "viewpoint",
        "must_include",
        "avoid",
        "style_note",
    ]

    # 혹시 모를 컬럼명 공백 제거
    df.columns = [str(c).strip() for c in df.columns]

    missing = [c for c in required if c not in df.columns]
    if missing:
        raise RuntimeError(
            f"[brand_rules] CSV에 필수 컬럼이 누락되었습니다: {missing}\n현재 컬럼: {list(df.columns)}"
        )

    rules = {}
    for _, row in df.iterrows():
        # ✅ brand key 정규화
        brand_key = normalize_brand(row.get("brand", ""))

        # 데이터프레임의 NaN(빈 값)을 빈 문자열("")로 변환하여 딕셔너리로 저장
        row_dict = row.fillna("").to_dict()

        # ✅ row_dict 내부 brand도 정규화해서 통일
        row_dict["brand"] = brand_key

        # brand가 비어있으면 스킵(의도치 않은 빈 행 방어)
        if not brand_key:
            continue

        # 기존 구조 유지: brand -> [rule_rows...]
        rules.setdefault(brand_key, []).append(row_dict)

    return rules

def build_brand_rule_block(rule_dict: dict) -> str:
    """
    LLM 프롬프트에 삽입할 브랜드 가이드라인 텍스트 블록을 생성합니다.
    Dict 형태의 규칙을 받아 포맷팅된 문자열로 반환합니다.
    """

    if not rule_dict:
        return ""

    # ✅ controller가 brand별로 list를 넘기는 경우가 실제로 자주 생김
    #    (load_brand_rules가 brand -> list 구조이므로)
    #    여기서 안전하게 첫 규칙을 선택하도록 보정
    if isinstance(rule_dict, list):
        if not rule_dict:
            return ""
        rule_dict = rule_dict[0]

    # brand 값도 정규화(혹시 외부에서 들어온 dict가 정규화 안 됐을 때)
    brand = normalize_brand(rule_dict.get("brand", "Unknown"))

    lines = []
    lines.append(f"<BrandRule brand='{brand}'>")

    viewpoint = str(rule_dict.get("viewpoint", "")).strip()
    opening = str(rule_dict.get("opening", "")).strip()
    routine = str(rule_dict.get("routine", "")).strip()
    closing = str(rule_dict.get("closing", "")).strip()
    style_note = str(rule_dict.get("style_note", "")).strip()

    if viewpoint:
        lines.append(f"- 시점(Viewpoint): {viewpoint}")
    if opening:
        lines.append(f"- 오프닝 가이드: {opening}")
    if routine:
        lines.append(f"- 루틴/전개 가이드: {routine}")
    if closing:
        lines.append(f"- 클로징 가이드: {closing}")
    if style_note:
        lines.append(f"- 스타일/톤 노트: {style_note}")

    # 금지어 및 필수어
    banned = str(rule_dict.get("banned", "")).strip()
    if banned and banned.lower() != "nan":
        lines.append(f"- 절대 사용 금지(Banned): {banned}")

    must = str(rule_dict.get("must_include", "")).strip()
    if must and must.lower() != "nan":
        lines.append(f"- 필수 포함 키워드: {must}")

    avoid = str(rule_dict.get("avoid", "")).strip()
    if avoid and avoid.lower() != "nan":
        lines.append(f"- 지양할 표현(Avoid): {avoid}")

    lines.append("</BrandRule>")

    return "\n".join(lines)


if __name__ == "__main__":
    # 테스트 실행 코드 (sanity check)
    try:
        print("[brand_rules] Loading rules...")
        rules = load_brand_rules()
        print(f"[brand_rules] loaded brands: {list(rules.keys())}")

        # ✅ 젠티스트 키가 실제로 존재하는지 바로 확인
        k = normalize_brand("젠티스트")
        print(f"[brand_rules] has '젠티스트'? -> {k in rules}")

        if rules:
            first_brand = list(rules.keys())[0]
            first_rule = rules[first_brand][0]
            print(f"\n[brand_rules] Sample dictionary for '{first_brand}':")
            print(first_rule)

            print(f"\n[brand_rules] Generated prompt block for '{first_brand}':")
            print("-" * 40)
            print(build_brand_rule_block(first_rule))
            print("-" * 40)

    except Exception as e:
        print(f"[Error] {e}")