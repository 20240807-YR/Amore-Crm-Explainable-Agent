# agent10/run_agent10_test.py
import os
import sys
import time
from pathlib import Path

START = time.time()

# -------------------------------------------------
# 1. 경로 고정 (실행 위치 무관)
# -------------------------------------------------
PROJECT_ROOT_ABS = Path(__file__).resolve().parent.parent
AGENT_DIR_ABS = PROJECT_ROOT_ABS / "agent10"
DATA_DIR_ABS = PROJECT_ROOT_ABS / "data"

print("=" * 70)
print(f"[BOOT] {time.time() - START:6.2f}s")
print("PROJECT_ROOT :", PROJECT_ROOT_ABS)
print("AGENT_DIR    :", AGENT_DIR_ABS)
print("DATA_DIR     :", DATA_DIR_ABS, "exists=", DATA_DIR_ABS.exists())
print("OPENAI_OFFLINE:", os.getenv("OPENAI_OFFLINE", "0"))
print("=" * 70)

# -------------------------------------------------
# 2. import 경로 강제 삽입
# -------------------------------------------------
for p in [AGENT_DIR_ABS, PROJECT_ROOT_ABS]:
    p_str = str(p)
    if p_str not in sys.path:
        sys.path.insert(0, p_str)

# -------------------------------------------------
# 3. Controller 실행
# -------------------------------------------------
from controller import main

results = main(
    persona_id="persona_1",
    topk=3,
    use_market_context=False,
    verbose=True,
)

print("\n" + "=" * 70)
print(f"[DONE] {time.time() - START:6.2f}s | rows={len(results)}")
print("=" * 70)

# -------------------------------------------------
# 4. 결과 없음 처리
# -------------------------------------------------
if not results:
    print("[WARN] 결과 없음")
    sys.exit(0)

# -------------------------------------------------
# 5. 샘플 1건 출력
# -------------------------------------------------
sample = results[0]

print("\n" + "=" * 70)
print("[MESSAGE OUTPUT]")
print("=" * 70)
print(sample.get("message", ""))

# -------------------------------------------------
# 6. Plan 출력
# -------------------------------------------------
print("\n" + "=" * 70)
print("[PLAN (ReAct Reasoning)]")
print("=" * 70)

plan = sample.get("plan", {}) or {}
for k, v in plan.items():
    print(f"- {k}: {v}")

# -------------------------------------------------
# 7. Verifier 입력 스냅샷
#    - controller 구조상 plan["persona_fields"]가 실제 기준
# -------------------------------------------------
print("\n" + "=" * 70)
print("[VERIFIER INPUT SNAPSHOT]")
print("=" * 70)

row = plan.get("persona_fields", {})
if not isinstance(row, dict):
    row = {}

for k in ["lifestyle", "skin_concern", "상품명"]:
    print(f"- {k}: {row.get(k)}")

# -------------------------------------------------
# 8. Verifier 결과
# -------------------------------------------------
print("\n" + "=" * 70)
print("[VERIFIER ERRORS]")
print("=" * 70)

errs = sample.get("errors", [])
if errs:
    for e in errs:
        print("•", e)
else:
    print("No errors ✔")

# -------------------------------------------------
# 9. 전체 Row별 오류 요약
# -------------------------------------------------
print("\n" + "=" * 70)
print("[ERROR SUMMARY - ALL ROWS]")
print("=" * 70)

for i, r in enumerate(results, 1):
    print(f"[row {i}] errors={r.get('errors')}")