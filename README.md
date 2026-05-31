# Lite Pangolin Loop for BitGN ECOM

Compact BitGN ECOM runner built around a Pangolin-style loop: one model-visible
tool, Python execution inside the task VM, persistent scratchpad, strict final
submission hygiene, and full run artifacts for analysis.

English | [Русская версия](./README.ru.md)

## ECOM Leaderboard

- Challenge page: https://bitgn.com/challenge/ECOM
- Lite Pangolin reached **10th place on the accuracy leaderboard** during the
  competition window.
- The overfit run below is not a general agent result. It is a useful reference
  for what a rules-overfit approach can extract when it is trained toward known
  benchmark patterns.

| Track | Run | Benchmark | Score | Time | Note |
| --- | --- | --- | ---: | ---: | --- |
| Lite Pangolin | `[@skifmax]-[lite-pangolin]-[gpt55]-[kotiki-enotiki]-[x002]` | `bitgn/ecom1-prod` | `73.7 / 100` | `2:02:10` | Best public Lite Pangolin run, OpenAI GPT 5.5 High via OmniRoute. |
| Lite Pangolin | `[@skifmax]-[lite-pangolin]-[gpt55]-[kotiki-enotiki]-[x001]` | `bitgn/ecom1-prod` | `73.3 / 100` | `2:13:59` | Earlier GPT 5.5 High prod run. |
| Lite Pangolin | `[@skifmax]-[lite-pangolin]-[deepseek-v4-flash]-[kotiki-enotiki]-[x001]` | `bitgn/ecom1-prod` | `50.1 / 100` | `3:55:51` | DeepSeek V4 Flash through OpenRouter. |
| Operation Overfit | `[@skifmax]-[operation-overfit]-[only-code]-[distil-from-llm-runs]-[x005]` | `bitgn/ecom1-prod` | `23.9 / 100` | `2:23` | Rules-overfit reference only, not a general reasoning agent. |

## Quick links

- Architecture: [`ARCHITECTURE.md`](./ARCHITECTURE.md)
- Russian architecture: [`ARCHITECTURE.ru.md`](./ARCHITECTURE.ru.md)
- Usage/runbook: [`USAGE.md`](./USAGE.md)
- Native runner details: [`codex-agent-native/README.md`](./codex-agent-native/README.md)
- Project map: [`PROJECT_MAP.md`](./PROJECT_MAP.md)
- Minimal task instruction: [`BENCHMARK_AGENT.md`](./BENCHMARK_AGENT.md)
- Local rules: [`codex-agent-native/local-rules/AGENTS.md`](./codex-agent-native/local-rules/AGENTS.md)
- Small-model design notes: [`SMALL_AGENT_ARCHITECTURE.md`](./SMALL_AGENT_ARCHITECTURE.md)

## How it works, briefly

The useful shape is intentionally small:

```text
task instruction
  -> local ECOM rules
  -> Pangolin loop
  -> one visible tool: execute_code
  -> Python helper layer calls BitGN VM tools
  -> finish(...)/ws.answer(...) submits the answer
```

The model does the reasoning. The runtime owns the boring contract details:
tool dispatch, observed refs, scratchpad compaction, finalization checks, task
artifacts, and run-level scoring backfill.

## Main components

- `run-pangolin-native.sh`: main wrapper for Pangolin runs on ECOM/PAC/sandbox.
- `codex-agent-native/runner.py`: task orchestration, lazy `StartTrial`, model
  loop, scoring, and manifest writing.
- `codex-agent-native/pi_exec_tool.py`: Python execution environment exposed as
  the single model-visible tool.
- `codex-agent-native/tool_gateway.py`: thin BitGN VM API adapter.
- `codex-agent-native/scratchpad.py`: compact scratchpad profile used between
  model iterations.
- `codex-agent-native/local-rules/`: local benchmark instructions injected into
  task sessions.

## Recommended runs

### ECOM dev, GPT 5.5 High via OmniRoute

```bash
cd /srv/aika-os/bitgn/code/bitgn-ecom-lite-pangolin

NATIVE_PANGOLIN_MODEL='codex/gpt-5.5-high' \
LOCAL_RUN_ID='lite-pangolin-gpt55-ecom-dev-YYYYMMDD' \
./run-pangolin-native.sh --env ecom --no-leaderboard --all -p 10
```

### ECOM prod leaderboard, GPT 5.5 High via OmniRoute

```bash
NATIVE_PANGOLIN_MODEL='codex/gpt-5.5-high' \
BITGN_RUN_NAME='[@skifmax]-[lite-pangolin]-[gpt55]-[kotiki-enotiki]-[xNNN]' \
LOCAL_RUN_ID='skifmax-lite-pangolin-gpt55-kotiki-enotiki-xNNN-ecom-prod-YYYYMMDD' \
BENCHMARK_ID='bitgn/ecom1-prod' AGENT_ENV='ecom' \
./run-pangolin-native.sh --env ecom --leaderboard --all -p 10
```

### ECOM dev, DeepSeek V4 Flash via OpenRouter

```bash
NATIVE_PANGOLIN_API_KEY="$(tr -d '\r\n' < "$HOME/.codex/openrouter-api-key")" \
NATIVE_PANGOLIN_BASE_URL='https://openrouter.ai/api/v1' \
NATIVE_PANGOLIN_MODEL='deepseek/deepseek-v4-flash' \
NATIVE_PANGOLIN_REASONING_ENABLED='0' \
NATIVE_PANGOLIN_MAX_ITERATIONS='36' \
LOCAL_RUN_ID='deepseek-v4-flash-ecom-dev-YYYYMMDD-iter36' \
./run-pangolin-native.sh --env ecom --no-leaderboard --all -p 5
```

## Current defaults

| Setting | Default | Why it matters |
| --- | --- | --- |
| `AGENT_BACKBONE` | `pangolin_loop` in `run-pangolin-native.sh` | Uses the single-tool execute-code loop. |
| `PANGOLIN_SCRATCHPAD` | `1` | Keeps compact task memory across iterations. |
| `PANGOLIN_SCRATCHPAD_MODE` | `v2` | Avoids replaying large raw outputs into the model. |
| `NATIVE_PREFLIGHT_CONTEXT` | `0` | Disabled because speed gains were inconsistent and refs regressed. |
| `NATIVE_EXEC_FINISH_HELPER` | `1` | Exposes `finish(...)` inside Python. |
| `NATIVE_EXEC_RUN_HELPER` | `1` | Exposes `run(...)` convenience helper. |
| `NATIVE_SESSION_TIMEOUT_SEC` | `1440` | Per-task timeout. |
| `NATIVE_PANGOLIN_MAX_ITERATIONS` | `20` | Override to `36` for weaker models such as DeepSeek V4 Flash. |

## Artifacts

Run artifacts are intentionally local and ignored by git:

```text
codex-agent-native/runs/<local_run_id>/
  run_manifest.jsonl
  tNN/attempt_<timestamp>_<id>/
    events.jsonl
    tool_calls.jsonl
    submission.json
    score.json
    session/pangolin_events.jsonl
    session/pangolin_scratchpad.json
```

Use these artifacts to compare wall time, summed task time, score details,
token usage, failed refs, and agent-level errors.

## Design stance

- Keep the model-visible surface to exactly one tool: `execute_code`.
- Prefer generic runtime gates and helper APIs over task-specific validators.
- Keep preflight, scratchpad, and weak-model guards toggleable.
- Treat overfit experiments as references, not as the production agent shape.
- Preserve full traces locally; do not commit `codex-agent-native/runs/`.

## Contact

- Maksim Popkov
- Telegram: `@skifmax`
- Email: `contact.popkov@yandex.com`
- Sites: https://mipopkov.com, https://mipopkov.ru
