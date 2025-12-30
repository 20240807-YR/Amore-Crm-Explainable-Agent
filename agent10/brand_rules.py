import pandas as pd
from pathlib import Path

# [경로 설정] 현재 파일 위치(agent10)를 기준으로 data 폴더 자동 탐색
BASE_DIR = Path(__file__).resolve().parent        # agent10/
ROOT_DIR = BASE_DIR.parent                        # project root
DATA_DIR = ROOT_DIR / "data"                      # data/

RULES_CSV = DATA_DIR / "amore_brand_tone_rules.csv"

def load_brand_rules(csv_path=RULES_CSV) -> dict:
    """
    브랜드 톤 앤 매너 규칙 CSV 파일을 로드합니다.
    입력값 csv_path는 Path 객체일 수도 있고, 문자열(str)일 수도 있습니다.
    """
    
    # 입력값이 문자열(str)이면 Path 객체로 변환합니다.
    if isinstance(csv_path, str):
        csv_path = Path(csv_path)

    # 이제 csv_path는 무조건 Path 객체이므로 .exists()가 정상 작동합니다.
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
    df.columns = [c.strip() for c in df.columns]

    missing = [c for c in required if c not in df.columns]
    if missing:
        raise RuntimeError(f"[brand_rules] CSV에 필수 컬럼이 누락되었습니다: {missing}\n현재 컬럼: {list(df.columns)}")

    rules = {}
    for _, row in df.iterrows():
        brand = str(row["brand"]).strip()
        
        # 데이터프레임의 NaN(빈 값)을 빈 문자열("")로 변환하여 딕셔너리로 저장
        # (나중에 문자열 합칠 때 에러 방지)
        row_dict = row.fillna("").to_dict()
        
        rules.setdefault(brand, []).append(row_dict)

    return rules

# [추가된 부분] 이 함수가 없어서 NameError가 발생했습니다.
def build_brand_rule_block(rule_dict: dict) -> str:
    """
    LLM 프롬프트에 삽입할 브랜드 가이드라인 텍스트 블록을 생성합니다.
    Dict 형태의 규칙을 받아 포맷팅된 문자열로 반환합니다.
    """
    if not rule_dict:
        return ""

    lines = []
    lines.append(f"<BrandRule brand='{rule_dict.get('brand', 'Unknown')}'>")
    
    if rule_dict.get("viewpoint"):
        lines.append(f"- 시점(Viewpoint): {rule_dict['viewpoint']}")
    
    if rule_dict.get("opening"):
        lines.append(f"- 오프닝 가이드: {rule_dict['opening']}")
        
    if rule_dict.get("routine"):
        lines.append(f"- 루틴/전개 가이드: {rule_dict['routine']}")
        
    if rule_dict.get("closing"):
        lines.append(f"- 클로징 가이드: {rule_dict['closing']}")
        
    if rule_dict.get("style_note"):
        lines.append(f"- 스타일/톤 노트: {rule_dict['style_note']}")
        
    # 금지어 및 필수어
    banned = rule_dict.get("banned", "")
    if banned and str(banned).lower() != "nan":
        lines.append(f"- 절대 사용 금지(Banned): {banned}")
        
    must = rule_dict.get("must_include", "")
    if must and str(must).lower() != "nan":
        lines.append(f"- 필수 포함 키워드: {must}")
        
    avoid = rule_dict.get("avoid", "")
    if avoid and str(avoid).lower() != "nan":
        lines.append(f"- 지양할 표현(Avoid): {avoid}")

    lines.append("</BrandRule>")
    
    return "\n".join(lines)


if __name__ == "__main__":
    # 테스트 실행 코드 (sanity check)
    try:
        print("[brand_rules] Loading rules...")
        rules = load_brand_rules()
        print(f"[brand_rules] loaded brands: {list(rules.keys())}")
        
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