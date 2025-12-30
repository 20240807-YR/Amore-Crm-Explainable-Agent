import os
import time
import sys
from pathlib import Path

# [경로 설정] 현재 파일 위치를 기준으로 프로젝트 루트와 data 폴더를 찾습니다.
CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"
RULES_PATH = DATA_DIR / "amore_brand_tone_rules.csv"

# 모듈 경로 추가 (안전 장치)
if str(CURRENT_DIR) not in sys.path:
    sys.path.append(str(CURRENT_DIR))

# [Import]
from crm_loader import CRMLoader
from product_selector import ProductSelector
from react_reasoning_agent import ReActReasoningAgent
from strategy_narrator import StrategyNarrator
from openai_client import OpenAIChatCompletionClient
from verifier import MessageVerifier, verify_brand_rules 
from tone_profiles import ToneProfiles
from market_context_tool import MarketContextTool
from brand_rules import load_brand_rules

def main(persona_id, topk=3, use_market_context=False, verbose=True):
    t0 = time.time()
    if verbose:
        print("[controller] START")
        print("[controller] OPENAI_OFFLINE:", os.getenv("OPENAI_OFFLINE", "0"))
        print(f"[controller] DATA_DIR: {DATA_DIR}")

    # 브랜드 룰 로드
    brand_rules = load_brand_rules(RULES_PATH)

    llm = OpenAIChatCompletionClient()
    
    # 클래스 초기화 (경로는 내부에서 자동 처리되거나 기본값 사용)
    loader = CRMLoader()
    tones = ToneProfiles(DATA_DIR) 
    verifier = MessageVerifier()
    selector = ProductSelector() 
    market = MarketContextTool(enabled=use_market_context)

    # 데이터 로드
    rows = loader.load(persona_id, topk)
    tone_map = tones.load_tone_profile_map()

    planner = ReActReasoningAgent(llm, tone_map)
    narrator = StrategyNarrator(llm, tone_profile_map=tone_map)

    results = []

    for i, row in enumerate(rows, 1):
        if verbose:
            print(f"[controller] row {i}/{len(rows)} select product")

        brand = str(row.get("brand", "")).strip()
        
        # [수정된 부분] 브랜드 규칙 체크 및 기본값 설정
        if brand in brand_rules:
            brand_rule = brand_rules[brand][0]
        else:
            # 규칙이 없는 브랜드(예: 젠티스트)가 나와도 에러 없이 진행
            if verbose:
                print(f"[Warning] '{brand}' 브랜드 규칙이 없습니다. 기본(Default) 규칙을 적용합니다.")
            
            brand_rule = {
                "brand": brand,
                "viewpoint": "뷰티 카운셀러",
                "opening": "안녕하세요.",
                "closing": "",
                "routine": "",
                "style_note": "친절하고 전문적인 톤",
                "banned": "",       # 금지어 없음
                "must_include": "", # 필수어 없음
                "avoid": ""         # 지양어 없음
            }

        # 상품 선정
        product = selector.select_one(row=row)
        row.update(product)

        row["market_context"] = (
            market.fetch(brand) if use_market_context else {}
        )

        if verbose:
            print(f"[controller] row {i}/{len(rows)} plan")
        
        # 전략 수립
        plan = planner.plan(row)
        if not plan or not plan.get("message_outline"):
            print(f"[Error] Plan generation failed for {brand}. Skipping...")
            continue

        if verbose:
            print(f"[controller] row {i}/{len(rows)} generate")
            
        # 메시지 생성
        msg = narrator.generate(
            row=row,
            plan=plan,
            brand_rule=brand_rule,
            repair_errors=None,
        )

        # 메시지 분리 (Title / Body) 안전하게 처리
        try:
            if "\n" in msg:
                title, body = msg.split("\n", 1)
            else:
                title = "NO TITLE"
                body = msg
        except ValueError:
            title = "제목 없음"
            body = msg

        # 검증
        errs = verifier.validate(row, title, body)
        
        clean_body = body.replace("BODY:", "", 1).strip()
        errs.extend(
            verify_brand_rules(clean_body, brand_rule)
        )

        # 에러 발생 시 재시도 (Self-Correction)
        if errs and not getattr(llm, "offline", False):
            for retry_cnt in range(2):
                if verbose:
                    print(f"[controller] retry {retry_cnt+1} due to errors: {errs}")
                    
                msg = narrator.generate(
                    row=row,
                    plan=plan,
                    brand_rule=brand_rule,
                    repair_errors=errs,
                )
                
                try:
                    if "\n" in msg:
                        title, body = msg.split("\n", 1)
                    else:
                        title = "NO TITLE"
                        body = msg
                except ValueError:
                    title = "제목 없음"
                    body = msg

                errs = verifier.validate(row, title, body)
                clean_body = body.replace("BODY:", "", 1).strip()
                errs.extend(verify_brand_rules(clean_body, brand_rule))
                
                if not errs:
                    break

        results.append(
            {
                "persona_id": row.get("persona_id"),
                "brand": brand,
                "score": row.get("score"),
                "message": msg,
                "plan": plan,
                "errors": errs,
            }
        )

    if verbose:
        print(f"[controller] DONE {time.time()-t0:.2f}s")

    return results

if __name__ == "__main__":
    # 테스트용 실행 코드
    print("Controller test run...")
    try:
        # 실제 실행 시 persona_id 등은 상황에 맞게 변경 필요
        res = main(persona_id="persona_1", topk=1, verbose=True)
        for r in res:
            print("="*50)
            print(f"Brand: {r['brand']}")
            print(f"Message Result:\n{r['message']}")
            print("="*50)
    except Exception as e:
        print("Error during test:", e)
        import traceback
        traceback.print_exc()