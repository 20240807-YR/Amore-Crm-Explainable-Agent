import os
import sys
import time
from pathlib import Path

START = time.time()

PROJECT_ROOT_ABS = Path(__file__).resolve().parents[1]
AGENT_DIR_ABS = PROJECT_ROOT_ABS / "agent10"
DATA_DIR_ABS = PROJECT_ROOT_ABS / "data"

print(f"[{time.time()-START:6.2f}s] BOOT")
print("PROJECT_ROOT:", PROJECT_ROOT_ABS)
print("AGENT_DIR    :", AGENT_DIR_ABS)
print("DATA_DIR     :", DATA_DIR_ABS, "exists=", DATA_DIR_ABS.exists())
print("OPENAI_OFFLINE:", os.getenv("OPENAI_OFFLINE", "0"))

if str(AGENT_DIR_ABS) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR_ABS))
if str(PROJECT_ROOT_ABS) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT_ABS))
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