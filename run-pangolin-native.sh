#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$SCRIPT_DIR/codex-agent-native"
source "$SCRIPT_DIR/scripts/load-omniroute-key.sh"
RUNLOG_HOME_DEFAULT="${RUNLOG_HOME:-$HOME/runlog-registry}"

MODEL="${NATIVE_PANGOLIN_MODEL:-${CODEX_MODEL:-codex/gpt-5.5-high}}"
TIMEOUT_SEC="${NATIVE_SESSION_TIMEOUT_SEC:-1440}"
BITGN_API_KEY_FILE="${BITGN_API_KEY_FILE:-$HOME/.bitgn/bitgn-api-key}"
OMNIROUTE_API_KEY_FILE="${BITGN_OMNIROUTE_KEY_FILE:-$HOME/.codex/omniroute-api-key}"
OPENROUTER_API_KEY_FILE="${OPENROUTER_API_KEY_FILE:-$HOME/.codex/openrouter-api-key}"
ENV_ID="sandbox"
PARALLELISM=""
ALL_TASKS=0
FAIL_FAST=0
LEADERBOARD="${NATIVE_LEADERBOARD:-0}"

ARGS=("$@")
TASKS=()
i=0
while [[ $i -lt ${#ARGS[@]} ]]; do
  arg="${ARGS[$i]}"
  case "$arg" in
    --env=pac1) ENV_ID="pac1" ;;
    --env=pac1-prod) ENV_ID="pac1-prod" ;;
    --env=ecom) ENV_ID="ecom" ;;
    --env=sandbox) ENV_ID="sandbox" ;;
    --env)
      if [[ $((i+1)) -lt ${#ARGS[@]} ]]; then
        ENV_ID="${ARGS[$((i+1))]}"
        i=$((i+1))
      fi
      ;;
    --parallelism=*) PARALLELISM="${arg#*=}" ;;
    --parallelism|-p)
      if [[ $((i+1)) -lt ${#ARGS[@]} ]]; then
        PARALLELISM="${ARGS[$((i+1))]}"
        i=$((i+1))
      fi
      ;;
    --all) ALL_TASKS=1 ;;
    --fail-fast) FAIL_FAST=1 ;;
    --leaderboard) LEADERBOARD=1 ;;
    --no-leaderboard) LEADERBOARD=0 ;;
    --*) ;;
    *) TASKS+=("$arg") ;;
  esac
  i=$((i+1))
done

if [[ $ALL_TASKS -eq 1 && ${#TASKS[@]} -gt 0 ]]; then
  echo "ERROR: --all cannot be combined with explicit task ids" >&2
  exit 1
fi

if [[ $ALL_TASKS -eq 0 && ${#TASKS[@]} -eq 0 ]]; then
  echo "Usage: ./run-pangolin-native.sh [--env sandbox|pac1|pac1-prod|ecom] [--all] [--fail-fast] [--leaderboard|--no-leaderboard] [-p|--parallelism N] <task-id> [task-id2 ...]" >&2
  exit 1
fi

if ! bitgn_prepare_codex_auth; then
  exit 1
fi

if [[ -z "${OMNIROUTE_API_KEY:-}" && -f "$OMNIROUTE_API_KEY_FILE" ]]; then
  OMNIROUTE_API_KEY="$(tr -d '\r\n' < "$OMNIROUTE_API_KEY_FILE")"
  export OMNIROUTE_API_KEY
fi

if [[ -z "${OPENROUTER_API_KEY:-}" && -f "$OPENROUTER_API_KEY_FILE" ]]; then
  OPENROUTER_API_KEY="$(tr -d '\r\n' < "$OPENROUTER_API_KEY_FILE")"
  export OPENROUTER_API_KEY
fi

if [[ -z "${BITGN_API_KEY:-}" && -f "$BITGN_API_KEY_FILE" ]]; then
  BITGN_API_KEY="$(tr -d '\r\n' < "$BITGN_API_KEY_FILE")"
fi

if [[ "$ENV_ID" == "pac1-prod" ]]; then
  export BENCHMARK_ID="${BENCHMARK_ID:-bitgn/pac1-prod}"
  export AGENT_ENV="pac1"
elif [[ "$ENV_ID" == "pac1" ]]; then
  export BENCHMARK_ID="${BENCHMARK_ID:-bitgn/pac1-dev}"
  export AGENT_ENV="pac1"
elif [[ "$ENV_ID" == "ecom" ]]; then
  export BENCHMARK_ID="${BENCHMARK_ID:-bitgn/ecom1-dev}"
  export AGENT_ENV="ecom"
else
  export BENCHMARK_ID="${BENCHMARK_ID:-bitgn/sandbox}"
  export AGENT_ENV="sandbox"
fi

cd "$APP_DIR"

if [[ $ALL_TASKS -eq 1 ]]; then
  if all_tasks_raw="$(BENCHMARK_ID="$BENCHMARK_ID" BENCHMARK_HOST="${BENCHMARK_HOST:-https://api.bitgn.com}" uv run python - <<'PY'
import os
from bitgn.harness_connect import HarnessServiceClientSync
from bitgn.harness_pb2 import GetBenchmarkRequest

client = HarnessServiceClientSync(os.environ.get("BENCHMARK_HOST") or "https://api.bitgn.com")
benchmark = client.get_benchmark(GetBenchmarkRequest(benchmark_id=os.environ["BENCHMARK_ID"]))
print(" ".join(str(task.task_id) for task in benchmark.tasks))
PY
)"; then
    read -r -a TASKS <<<"$all_tasks_raw"
    if [[ ${#TASKS[@]} -eq 0 ]]; then
      echo "ERROR: --all resolved zero tasks for benchmark '$BENCHMARK_ID'" >&2
      exit 1
    fi
    echo "[TASKS] Resolved ${#TASKS[@]} tasks from $BENCHMARK_ID"
  else
    echo "ERROR: --all failed to resolve tasks for benchmark '$BENCHMARK_ID'" >&2
    exit 1
  fi
fi

RUN_ARGS=("${TASKS[@]}")
if [[ -n "$PARALLELISM" ]]; then
  RUN_ARGS+=("--parallelism" "$PARALLELISM")
fi
if [[ $FAIL_FAST -eq 1 ]]; then
  RUN_ARGS+=("--fail-fast")
fi

RUNLOG_HOME="$RUNLOG_HOME_DEFAULT" \
AGENT_BACKBONE="pangolin_loop" \
NATIVE_PANGOLIN_MODEL="$MODEL" \
NATIVE_SESSION_TIMEOUT_SEC="$TIMEOUT_SEC" \
NATIVE_LEADERBOARD="$LEADERBOARD" \
PANGOLIN_SCRATCHPAD="${PANGOLIN_SCRATCHPAD:-1}" \
PANGOLIN_SCRATCHPAD_MODE="${PANGOLIN_SCRATCHPAD_MODE:-v2}" \
NATIVE_EXEC_FINISH_HELPER="${NATIVE_EXEC_FINISH_HELPER:-1}" \
NATIVE_EXEC_RUN_HELPER="${NATIVE_EXEC_RUN_HELPER:-1}" \
BITGN_API_KEY="${BITGN_API_KEY:-}" \
BITGN_RUN_NAME="${BITGN_RUN_NAME:-}" \
OMNIROUTE_API_KEY="${OMNIROUTE_API_KEY:-}" \
OPENROUTER_API_KEY="${OPENROUTER_API_KEY:-}" \
uv run python runner.py "${RUN_ARGS[@]}"
