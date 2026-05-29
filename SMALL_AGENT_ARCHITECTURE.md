# ECOM Small Agent Architecture

This project is a separate testbed for making weaker/cheaper OpenRouter models
such as `openai/gpt-5.4-nano` and `openai/gpt-5.4-mini` complete BitGN ECOM
tasks reliably. It was copied from `bitgn-cli-agent-native-test` after the
Pangolin GPT 5.5 High setup reached `48/53` on `bitgn/ecom1-dev`.

## Problem Signal

Small models often do not fail because the task is impossible. They fail because
they lose the agent contract:

- loop reaches max iterations without `finish(...)`, `ws.answer(...)`, or
  `report_completion(...)`;
- final refs are guessed, absolute workspace paths, or missing required docs;
- Python code misuses raw tool response shapes (`KeyError`, dict slicing,
  unknown tool names, invalid paths);
- outcome labels drift between `OUTCOME_OK`, `OUTCOME_DENIED_SECURITY`, and
  `OUTCOME_NONE_UNSUPPORTED`;
- exact answer formats are lost after broad exploration.

The intent here is to remove protocol burden from the model while keeping a
single model-visible tool.

## Target Shape

```text
Task
  -> Pangolin prompt + compact ECOM rules
  -> small model calls one visible tool: execute_code
  -> execute_code exposes a safe helper facade
       -> read_json/list_dir/search_docs/search_proc
       -> resolve_catalog_product/count_catalog/scan_store_availability
       -> verify_refs/canonicalize_refs
       -> finish_ok/finish_denied/finish_unsupported
  -> runtime gates audit progress, refs, outcome, and finalization
  -> BitGN trial submission
```

The model should still decide the answer. The runner should own protocol,
canonical refs, API shape, and final submission hygiene.

## Design Principles

- Keep exactly one model-visible tool: `execute_code`.
- Prefer helpers inside `execute_code` over adding tools to the model schema.
- Make every new behavior toggleable by env var.
- Do not hardcode task ids, expected answers, or benchmark-specific repairs.
- Record raw artifacts under `codex-agent-native/runs/`; never commit runs.
- Preserve a GPT 5.5 comparison path so weak-model gates can be A/B tested.

## Candidate Toggles

```text
SMALL_AGENT_MODE=1
SMALL_AGENT_SAFE_HELPERS=1
SMALL_AGENT_REF_LEDGER=1
SMALL_AGENT_FINALIZE_GUARD=1
SMALL_AGENT_OUTCOME_BUILDERS=1
SMALL_AGENT_PREFLIGHT=0
```

Names are provisional. Prefer `NATIVE_...` names if wiring into existing runner
config conventions is cleaner.

## TODO

1. Add a safe helper facade inside the Python exec environment.
   - Normalize response shapes from BitGN tools.
   - Avoid direct dict slicing and common `KeyError` patterns.
   - Provide small helpers for docs, `/proc`, `/archive`, and `/uploads`.

2. Add a canonical evidence/ref ledger.
   - Track every successful read/list/search path.
   - Normalize workspace-local paths back to benchmark paths.
   - Block or warn on refs not observed through the VM.
   - Prefer missing optional refs over invalid refs.

3. Add finalization/progress watchdogs for small models.
   - Detect many consecutive tool calls with no new refs, no mutation, and no
     finalization.
   - Force a short repair/finalize step.
   - If scratchpad has a complete candidate, allow a guarded finalization path.

4. Add outcome builders.
   - `finish_ok(message, refs, answer=None)`
   - `finish_denied(message, refs)`
   - `finish_unsupported(message, refs)`
   - Validate allowed outcome strings and required fields before submission.

5. Add weak-model prompt profile.
   - Short, direct, and contract-focused.
   - Tell model to use helpers and always finish.
   - Keep broad exploration discouraged unless a helper fails.

6. Run staged evaluations.
   - Smoke: `t01`, `t17`, `t28`, `t43`, `t51`.
   - Full `ecom dev` on nano and mini through OpenRouter.
   - Compare solved tasks, score, wall time, summed task time, and cost.

## Baseline Numbers To Beat

From the source project on 2026-05-29, same Pangolin shape, `--no-leaderboard`,
`--all`, `-p 10`:

| Model | Provider | Passed | Score | Wall | Task-time sum | Cost |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `codex/gpt-5.5-high` | OmniRoute | 48/53 | 49.857 | 12:07 | 1:18:56 | n/a |
| `qwen/qwen3.6-27b` | OpenRouter | 18/53 | 18.000 | 12:38 | 1:48:01 | `$2.850` |
| `openai/gpt-5.4-nano` | OpenRouter | 9/53 | 9.000 | 9:17 | 1:09:01 | `$0.865` |
| `openai/gpt-5.4-mini` | OpenRouter | 7/53 | 7.000 | 9:12 | 1:09:57 | `$2.761` |

First useful target: make nano/mini submit valid answers more often. The largest
observed loss class was no valid final submission or invalid grounding refs, not
pure task reasoning failure.
