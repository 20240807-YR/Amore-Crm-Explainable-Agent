import os, sys, time
from pathlib import Path

START = time.time()

# [수정된 부분] -------------------------------------------------------
# 현재 파일(run_agent10_test.py)의 위치를 기준으로 프로젝트 루트를 찾습니다.
# .resolve() : 절대 경로로 변환
# .parent    : agent10 폴더
# .parent.parent : Amore-Crm-Explainable-Agent 폴더 (프로젝트 루트)
PROJECT_ROOT_ABS = Path(__file__).resolve().parent.parent
# ---------------------------------------------------------------------

AGENT_DIR_ABS = PROJECT_ROOT_ABS / "agent10"
DATA_DIR_ABS = PROJECT_ROOT_ABS / "data"

if str(AGENT_DIR_ABS) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR_ABS))
if str(PROJECT_ROOT_ABS) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT_ABS))

print(f"[{time.time()-START:6.2f}s] BOOT")
print("PROJECT_ROOT:", PROJECT_ROOT_ABS)
print("AGENT_DIR    :", AGENT_DIR_ABS)
# 아래 exists가 True로 나오는지 확인하세요
print("DATA_DIR     :", DATA_DIR_ABS, "exists=", DATA_DIR_ABS.exists()) 
print("OPENAI_OFFLINE:", os.getenv("OPENAI_OFFLINE", "0"))

from controller import main

res = main(
    persona_id="persona_1",
    topk=3,
    use_market_context=False,
    verbose=True,
)

print(f"[{time.time()-START:6.2f}s] DONE rows={len(res)}")
if res:
    print(res[0]["message"])