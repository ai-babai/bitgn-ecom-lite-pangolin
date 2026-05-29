# Usage

This project is the ECOM small-agent testbed copied from the native baseline. It keeps the existing wrappers, but the primary experiments are weak/small model Pangolin runs that try to improve contract adherence without changing the preserved baseline repo.

The successful experimental Pangolin-loop preset for local/non-leaderboard model endpoints is stored at `configs/pangolin-local-success.env.example`. It uses one model-visible tool, `execute_code`, scratchpad-v2, helper finalization, preflight off, 20 loop iterations, 1440s per-task timeout, and `-p 10` for full ECOM runs.

## Location

```text
/srv/aika-os/bitgn/code/ecom-small-agent-test
```

## Run Commands

ECOM dev smoke:

```bash
./run-codex-native.sh --env ecom --no-leaderboard t01
```

PAC1 dev smoke:

```bash
BITGN_API_KEY='' BITGN_API_KEY_FILE=/tmp/bitgn-no-key ./run-codex-native.sh --env pac1 t01
```

Pi / p-agent smoke:

```bash
PI_MODEL='omniroute/codex/gpt-5.5-high' ./run-pi-native.sh --env ecom --no-leaderboard t01
BITGN_API_KEY='' BITGN_API_KEY_FILE=/tmp/bitgn-no-key PI_MODEL='omniroute/codex/gpt-5.5-high' ./run-pi-native.sh --env pac1 --no-leaderboard t01
PI_MODEL='openrouter/qwen/qwen3.6-27b' ./run-pi-native.sh --env ecom --no-leaderboard t01 t02 -p 2
```

Full ECOM dev run without leaderboard:

```bash
./run-codex-native.sh --env ecom --no-leaderboard --all -p 10
```

Full PAC1 prod run without leaderboard:

```bash
BITGN_API_KEY='' BITGN_API_KEY_FILE=/tmp/bitgn-no-key ./run-codex-native.sh --env pac1-prod --all -p 10
```

## Defaults

- Default model: `codex/gpt-5.5-high`.
- Override model with `CODEX_MODEL`.
- Pi default model: `omniroute/codex/gpt-5.5-high`.
- Override Pi model with `PI_MODEL`; OmniRoute models require `OMNIROUTE_API_KEY` or `BITGN_OMNIROUTE_KEY_FILE`, while OpenRouter models require `OPENROUTER_API_KEY` or `OPENROUTER_API_KEY_FILE`.
- Pi default tool mode: `PI_TOOL_MODE=exec`, which exposes exactly one Pi tool named `exec`; Python code inside that tool can call BitGN runtime tools with `call_tool(...)`.
- Optional Pi `exec` scratchpad: set `PANGOLIN_SCRATCHPAD=1` or `NATIVE_PANGOLIN_SCRATCHPAD=1`; default is off.
- Preflight context is off by default after ECOM regressions. Enable only for experiments with `NATIVE_PREFLIGHT_CONTEXT=1`; it reads the VM tree and, for ECOM, SQLite schema before the agent starts and injects a compact navigation block into the prompt.
- Default session timeout: `1440` seconds through `run-codex-native.sh` and `run-pi-native.sh`.
- Artifacts are written under `codex-agent-native/runs/` and are gitignored.
- Runs are non-leaderboard by default, even when a BitGN API key is available.
- Leaderboard submission happens only with `--leaderboard` or `NATIVE_LEADERBOARD=1`.
- ECOM/PAC dev and prod runs need a BitGN API key for `StartRun`/`StartTrial`; non-leaderboard runs still close their prepared run with `SubmitRun(force=True)` so the harness releases scores when available.
- Current BitGN harness scoring is run-level: each task is closed with `EndTrial`, then the wrapper closes the prepared run with `SubmitRun(force=True)` and backfills task scores from `GetRun`. If a prod or sealed run has no score, artifacts use `feedback_status=unavailable` instead of failing the local run.

## What The Agent Sees

The agent receives:

- the task instruction from BitGN;
- the minimal local instruction from `codex-agent-native/local-rules/AGENTS.md`;
- a small environment note from `AGENTS.pac1.md` or `AGENTS.ecom.md` when applicable;
- runtime tool access through `python runtime_tools.py ...` for Codex, or through Pi's single `exec` Python tool plus `call_tool(...)`;
- optional preflight navigation from `session/preflight_context.md`, including the environment tree and ECOM DB schema only when `NATIVE_PREFLIGHT_CONTEXT=1`;
- benchmark-provided runtime files, including `AGENTS.MD` when the VM exposes it.

By default, it does not receive our previous workbook, scratchpad, analytics, Pangolin loop, rule registry, or custom validators.

When `PANGOLIN_SCRATCHPAD=1` is set on Pi `exec`, the model still receives only the single `exec` tool. Python code inside that tool gets a persistent `scratchpad` JSON dict plus persisted JSON-serializable globals for the same task. The initial prompt includes the current scratchpad, and every `exec` result returns the updated scratchpad so it is visible on the next model iteration. The files are `session/pangolin_scratchpad.json`, `session/pangolin_state.json`, and `session/pangolin_tracking.json` under that task's run workspace.

With scratchpad enabled, finalization follows the original Pangolin shape: set `scratchpad['answer']`, `scratchpad['outcome']`, and `scratchpad['refs']`, define `verify(sp)`, then call `ws.answer(scratchpad, verify)` from inside Python. Direct `report_completion` is blocked in this mode; `ws.answer` runs verification and submits only after the scratchpad passes the local checks.
