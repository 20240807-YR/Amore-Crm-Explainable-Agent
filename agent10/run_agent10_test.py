# agent10/run_agent10_test.py
import os
import sys
import time
import threading
from pathlib import Path

START = time.time()


def ts() -> str:
    return f"{time.time() - START:7.2f}s"


def log(msg: str):
    print(f"[{ts()}] {msg}", flush=True)


# -------------------------------------------------
# 0. 진행 표시(스피너) - 어디서 멈췄는지 체감용
# -------------------------------------------------
_stop_spinner = False


def _spinner(label: str = "RUNNING"):
    frames = ["|", "/", "-", "\\"]
    i = 0
    while not _stop_spinner:
        print(f"\r[{ts()}] {label} {frames[i % len(frames)]}", end="", flush=True)
        i += 1
        time.sleep(0.15)
    print("\r", end="", flush=True)


# -------------------------------------------------
# 1. 경로 고정 (실행 위치 무관)
# -------------------------------------------------
PROJECT_ROOT_ABS = Path(__file__).resolve().parent.parent
AGENT_DIR_ABS = PROJECT_ROOT_ABS / "agent10"
DATA_DIR_ABS = PROJECT_ROOT_ABS / "data"

# -------------------------------------------------
# 1-1. ✅ Ollama 강제 차단 (run에서 확실히 끊어버림)
#   - openai_client.py가 Ollama를 참조하더라도,
#     여기서 환경변수로 localhost 경로를 제거해 "실수로" 타는 걸 막음
# -------------------------------------------------
os.environ["OLLAMA_BASE_URL"] = ""  # 빈 값으로 강제 무력화
os.environ["DISABLE_OLLAMA"] = "1"  # (openai_client.py에서 이 값을 참고하면 더 안전)

print("=" * 70)
print(f"[BOOT] {ts()}")
print("PROJECT_ROOT :", PROJECT_ROOT_ABS)
print("AGENT_DIR    :", AGENT_DIR_ABS)
print("DATA_DIR     :", DATA_DIR_ABS, "exists=", DATA_DIR_ABS.exists())
print("OPENAI_OFFLINE:", os.getenv("OPENAI_OFFLINE", "0"))
print("OPENAI_API_KEY exists:", bool(os.getenv("OPENAI_API_KEY")))
print("OLLAMA_BASE_URL:", repr(os.getenv("OLLAMA_BASE_URL", "")))
print("DISABLE_OLLAMA:", os.getenv("DISABLE_OLLAMA", "0"))
print("=" * 70, flush=True)

# -------------------------------------------------
# 2. import 경로 강제 삽입
# -------------------------------------------------
for p in [AGENT_DIR_ABS, PROJECT_ROOT_ABS]:
    p_str = str(p)
    if p_str not in sys.path:
        sys.path.insert(0, p_str)

# -------------------------------------------------
# 3. Controller 실행 (진행이 보이도록 래핑)
# -------------------------------------------------
log("import controller.main ...")
from controller import main  # noqa: E402

log("controller.main ready")

spinner_thread = threading.Thread(
    target=_spinner,
    args=("CONTROLLER(main) RUNNING",),
    daemon=True,
)
spinner_thread.start()

results = None
err = None

try:
    log("CALL main(persona_id=persona_1, topk=3, use_market_context=False, verbose=True)")
    results = main(
        persona_id="persona_1",
        topk=3,
        use_market_context=False,
        verbose=True,
    )
    log("RETURN from controller.main")
except Exception as e:
    err = e
finally:
    _stop_spinner = True
    spinner_thread.join(timeout=1.0)

if err:
    log(f"ERROR raised from controller.main: {repr(err)}")
    raise err

# -------------------------------------------------
# 4. 결과 요약
# -------------------------------------------------
print("\n" + "=" * 70)
print(f"[DONE] {ts()} | rows={len(results)}")
print("=" * 70, flush=True)

# -------------------------------------------------
# 5. 결과 없음 처리
# -------------------------------------------------
if not results:
    print("[WARN] 결과 없음", flush=True)
    sys.exit(0)

# -------------------------------------------------
# 6. 샘플 1건 출력
# -------------------------------------------------
sample = results[0]

print("\n" + "=" * 70)
print("[MESSAGE OUTPUT]")
print("=" * 70)
print(sample.get("message", ""), flush=True)

# -------------------------------------------------
# 7. Plan 출력
# -------------------------------------------------
print("\n" + "=" * 70)
print("[PLAN (ReAct Reasoning)]")
print("=" * 70)

plan = sample.get("plan", {}) or {}
for k, v in plan.items():
    print(f"- {k}: {v}", flush=True)

# -------------------------------------------------
# 8. Verifier 입력 스냅샷
#    - controller 구조상 plan["persona_fields"]가 실제 기준
# -------------------------------------------------
print("\n" + "=" * 70)
print("[VERIFIER INPUT SNAPSHOT]")
print("=" * 70)

row = plan.get("persona_fields", {})
if not isinstance(row, dict):
    row = {}

for k in ["lifestyle", "skin_concern", "상품명"]:
    print(f"- {k}: {row.get(k)}", flush=True)

# -------------------------------------------------
# 9. Verifier 결과
# -------------------------------------------------
print("\n" + "=" * 70)
print("[VERIFIER ERRORS]")
print("=" * 70)

errs = sample.get("errors", [])
if errs:
    for e in errs:
        print("•", e, flush=True)
else:
    print("No errors ✔", flush=True)

# -------------------------------------------------
# 10. 전체 Row별 오류 요약
# -------------------------------------------------
print("\n" + "=" * 70)
print("[ERROR SUMMARY - ALL ROWS]")
print("=" * 70)

for i, r in enumerate(results, 1):
    print(f"[row {i}] errors={r.get('errors')}", flush=True)