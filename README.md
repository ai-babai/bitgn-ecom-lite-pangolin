# ecom-small-agent-test

Separate BitGN ECOM native-agent testbed for weak/small model experiments. This
project was copied from `bitgn-cli-agent-native-test` so nano/mini architecture
work can proceed without changing the preserved baseline project.

Start with [SMALL_AGENT_ARCHITECTURE.md](SMALL_AGENT_ARCHITECTURE.md) for the
current problem statement, proposed gates, and implementation TODO.

Minimal BitGN native agent experiment. Backbones are plain Codex CLI (`codex exec`) and Pi (`pi --print`): one CLI-agent session per task. Codex uses thin runtime-tool CLI wrappers; Pi defaults to one custom `exec` tool that runs Python and reaches BitGN tools through `call_tool(...)`.

The default goal here is to develop and measure small-agent reliability gates while keeping changes separate from the preserved baseline. Existing Codex/Pi paths remain available for comparison; the main new work should focus on generic Pangolin `execute_code` helpers, refs, and finalization behavior.

Start with:

- `USAGE.md` for commands.
- `PROJECT_MAP.md` for surrounding BitGN projects.
- `BENCHMARK_AGENT.md` for the minimal instruction injected into task sessions.
- `BITGN_SAMPLE_REFERENCE.md` for the public BitGN sample-agent baseline this project follows.

## Run

```bash
cd /srv/aika-os/bitgn/code/ecom-small-agent-test
CODEX_MODEL='codex/gpt-5.5-high' ./run-codex-native.sh --env ecom --no-leaderboard t01
PI_MODEL='omniroute/codex/gpt-5.5-high' ./run-pi-native.sh --env ecom --no-leaderboard t01
NATIVE_PANGOLIN_MODEL='codex/gpt-5.5-high' ./run-pangolin-native.sh --env ecom --no-leaderboard t01
```

Use `--all` for a full benchmark and `-p N` for task parallelism. Non-leaderboard mode is the default; pass `--leaderboard` only when intentionally submitting a BitGN run with `BITGN_API_KEY`.

The runner follows the current BitGN run lifecycle: it closes each task trial, then closes the prepared run with `SubmitRun(force=True)` and backfills scores from `GetRun` when the benchmark exposes them. Prod/sealed runs can legitimately return no score; those tasks are recorded with `feedback_status=unavailable` rather than treated as runner failures.

Pi runs default to `PI_TOOL_MODE=exec`, where the only enabled Pi tool is `exec`. Set `PI_TOOL_MODE=bash` only for the older shell-wrapper path.

Preflight context is disabled by default because the measured speed gain was inconsistent and it increased ECOM missed-reference failures. For experiments, enable it with `NATIVE_PREFLIGHT_CONTEXT=1`; the runner then reads a compact VM tree and, for ECOM, the SQLite schema via `/bin/sql`, writes `session/preflight_context.md`, and injects it into the prompt.

## Successful Pangolin Local-Model Preset

The current successful local/non-leaderboard Pangolin-loop preset is recorded in [configs/pangolin-local-success.env.example](configs/pangolin-local-success.env.example). It keeps the model-visible surface to exactly one tool, `execute_code`, with compact scratchpad-v2 and the `finish(...)`/`run(...)` Python helpers enabled.

Use this shape for local OpenAI-compatible model endpoints by replacing the base URL, model, and API key values:

```bash
set -a
source configs/pangolin-local-success.env.example
set +a
./run-pangolin-native.sh --env ecom --no-leaderboard --all -p 10
```

Known-good run shape from 2026-05-28 on `bitgn/ecom1-dev`: `pangolin_loop`, `PANGOLIN_SCRATCHPAD=1`, `PANGOLIN_SCRATCHPAD_MODE=v2`, `NATIVE_PREFLIGHT_CONTEXT=0`, `NATIVE_PANGOLIN_MAX_ITERATIONS=20`, `NATIVE_SESSION_TIMEOUT_SEC=1440`, and `-p 10`. After the BitGN run-level scoring update and the first OCR task appearing in the dev API, `local_run_pangolin-gpt55-omni-ecom-dev-all-20260528` resolved 51 tasks and scored `45.692/51` with `44/51` exact passes in `17:09` wall time and `1:35:45` summed task time. Main remaining failures were archive-fraud false positives, missing required update-doc refs, one OCR answer-format issue, and one OmniRoute 524 timeout on `t48`.

## Optional Pangolin Scratchpad

Enable with `PANGOLIN_SCRATCHPAD=1` or `NATIVE_PANGOLIN_SCRATCHPAD=1` on Pi `exec` runs:

```bash
PANGOLIN_SCRATCHPAD=1 PI_MODEL='omniroute/codex/gpt-5.5-high' ./run-pi-native.sh --env pac1 --no-leaderboard t01
```

This does not add another model-visible tool. Pi still receives only `exec`; inside executed Python, `scratchpad` is a persistent JSON dict and JSON-serializable globals persist across later `exec` calls for the same task. The initial prompt includes the current scratchpad, and every `exec` result returns the updated scratchpad so the model sees it again on the next iteration. Artifacts are written only when enabled:

- `session/pangolin_scratchpad.json`
- `session/pangolin_state.json`
- `session/pangolin_tracking.json`

The executed Python environment also exposes a Pangolin-style `ws` helper. `ws.read/write/delete/move/...` wrap the same VM calls as `call_tool(...)`, and final submission must go through `ws.answer(scratchpad, verify)` when scratchpad is enabled. That mirrors the original Pangolin pattern: the agent writes answer/outcome/refs into scratchpad, defines `verify(sp)`, and `ws.answer` blocks submission if verification fails, required fields are missing, the outcome is unknown, or direct `report_completion` is attempted. The helper tracks read/write/delete paths across `exec` calls and warns when read paths are missing from final refs or a blocked outcome mutated files.

Set `PANGOLIN_SCRATCHPAD_MODE=v2` for the compact profile. v2 keeps decisions, scope, concise evidence, outcome/message, and exact refs, but drops raw trees, large query results, full tool outputs, and duplicate bulky fields before the scratchpad is returned to the model. It also writes `session/pangolin_scratchpad_profile.jsonl` with raw/view byte sizes and dropped keys for profiling.

In v2, returned `exec` output is capped at 40k characters by default because the main token growth came from large Python result/stdout payloads being replayed to the model, not from the scratchpad JSON file itself. Override with `NATIVE_EXEC_OUTPUT_LIMIT` or `NATIVE_EXEC_TOOL_TEXT_LIMIT` for experiments.

The module is copied from the ECOM1 Pangolin loop pattern in `/srv/aika-os/bitgn/code/bitgn-ecom1-env/codex-agent-native/agent_backends/pangolin_loop.py`: compact JSON scratchpad, persistent serializable Python state, and prompt guidance to keep refs/evidence scoped while excluding runner artifacts from `grounding_refs`.

Comparison with the author PAC1 sample in `/srv/aika-os/bitgn/code/bitgn-pac1-env/sample-agents/pac1-py/agent.py`:

| Aspect | ECOM1/Pi `exec` scratchpad here | Author PAC1 sample |
| --- | --- | --- |
| Memory form | Explicit `scratchpad` JSON dict plus persisted JSON-serializable Python globals; current scratchpad is shown in the prompt and returned after every `exec` | Implicit chat `log` only |
| Per-step state | Agent may update durable fields such as `goal`, `target_scope`, `mutation_plan`, evidence, refs, outcome, message | `NextStep.current_state` and `plan_remaining_steps_brief` are generated each turn and appended to the transcript |
| Artifact | `session/pangolin_scratchpad.json` and `session/pangolin_state.json` | No separate scratchpad artifact |
| Toggle | Off by default; enabled by env var | Always part of the sample loop shape through transcript state |
| Tool surface | Still exactly one Pi tool, `exec` | Structured runtime tools selected by the model schema |
| Grounding rule | Scratchpad/session files are runner artifacts and must not be cited | Completion cites benchmark workspace refs through `grounding_refs` |

## Full Dev Run Matrix

Default per-task session timeout is `1440` seconds. All commands below are non-leaderboard runs.

| Target | Provider | Model | Command |
| --- | --- | --- | --- |
| PAC1 dev | OmniRoute | `omniroute/codex/gpt-5.5-high` | `BITGN_API_KEY='' BITGN_API_KEY_FILE=/tmp/bitgn-no-key PI_MODEL='omniroute/codex/gpt-5.5-high' LOCAL_RUN_ID='pi-gpt55-omni-pac1-dev-full-YYYYMMDD' ./run-pi-native.sh --env pac1 --no-leaderboard --all -p 10` |
| ECOM dev | OmniRoute | `omniroute/codex/gpt-5.5-high` | `PI_MODEL='omniroute/codex/gpt-5.5-high' LOCAL_RUN_ID='pi-gpt55-omni-ecom-dev-full-YYYYMMDD' ./run-pi-native.sh --env ecom --no-leaderboard --all -p 10` |
| PAC1 dev | OpenRouter | `openrouter/qwen/qwen3.6-27b` | `BITGN_API_KEY='' BITGN_API_KEY_FILE=/tmp/bitgn-no-key PI_MODEL='openrouter/qwen/qwen3.6-27b' LOCAL_RUN_ID='pi-qwen36-27b-pac1-dev-full-YYYYMMDD' ./run-pi-native.sh --env pac1 --no-leaderboard --all -p 10` |
| ECOM dev | OpenRouter | `openrouter/qwen/qwen3.6-27b` | `PI_MODEL='openrouter/qwen/qwen3.6-27b' LOCAL_RUN_ID='pi-qwen36-27b-ecom-dev-full-YYYYMMDD' ./run-pi-native.sh --env ecom --no-leaderboard --all -p 10` |

## Latest Pi Dev Results

Non-leaderboard Pi runs from 2026-05-26. `Errors` are runtime-level failures, mostly per-task session timeouts or missing `submission.json` when the agent finished without an explicit `report_completion`.

| Model | Provider | Benchmark | Run | Tasks | Passed | Scored failed | Errors | Score sum |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| `omniroute/codex/gpt-5.5-high` | OmniRoute | `bitgn/pac1-dev` | `local_run_pi-gpt55-omni-pac1-dev-full-20260526` | 43 | 22 | 15 | 6 | 22.0 |
| `omniroute/codex/gpt-5.5-high` | OmniRoute | `bitgn/ecom1-dev` | `local_run_pi-gpt55-omni-ecom-dev-full-20260526` | 47 | 20 | 16 | 11 | 20.0 |
| `openrouter/qwen/qwen3.6-27b` | OpenRouter | `bitgn/pac1-dev` | `local_run_pi-qwen36-27b-pac1-dev-full-20260526` | 43 | 13 | 8 | 22 | 13.0 |
| `openrouter/qwen/qwen3.6-27b` | OpenRouter | `bitgn/ecom1-dev` | `local_run_pi-qwen36-27b-ecom-dev-full-20260526` | 48 | 6 | 13 | 29 | 6.6 |

Summary: Pi starts and reaches both environments with both providers. GPT 5.5 is substantially more stable, but still hit 720s timeouts before the default was raised to 1440s. Qwen 3.6 27B often fails the Pi-native completion protocol even when it performs work, so its main issue here is missing explicit completion rather than provider connectivity.

## Latest Pi Exec Tool Dev Results

Non-leaderboard full dev runs from 2026-05-27 for the `Pi loop agent + exec Python tool` path. These runs used only `omniroute/codex/gpt-5.5-high` through OmniRoute. Raw Pi session events show only one custom tool name, `exec`, was called.

| Model | Provider | Benchmark | Run | Tasks | Passed | Scored failed | Errors | Score sum | Tool calls |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `omniroute/codex/gpt-5.5-high` | OmniRoute | `bitgn/pac1-dev` | `local_run_pi-exec-gpt55-omni-pac1-dev-full-20260527` | 43 | 24 | 19 | 0 | 24.0 | 285 |
| `omniroute/codex/gpt-5.5-high` | OmniRoute | `bitgn/ecom1-dev` | `local_run_pi-exec-gpt55-omni-ecom-dev-full-20260527` | 48 | 31 | 17 | 0 | 32.655 | 358 |

Comparison to the prior GPT 5.5 Pi bash-wrapper dev runs: PAC1 dev improved from 22 to 24 passed tasks and removed 6 runtime errors. ECOM dev improved from 20 to 31 passed tasks and removed 11 runtime errors; the current ECOM dev task set resolved as 48 tasks.

Non-leaderboard verification: no `leaderboard_run_id` values and no leaderboard submission markers in either run artifact directory.

## Latest Pi Exec Scratchpad-v1 Results

Non-leaderboard full runs from 2026-05-27 for `Pi agent + exec + scratchpad-v1`, using `omniroute/codex/gpt-5.5-high` through OmniRoute, `PANGOLIN_SCRATCHPAD=1`, and `-p 10`. The Pi model-visible tool surface still contained only `exec`; scratchpad-v1 was injected through the prompt and returned in each `exec` result.

| Model | Provider | Benchmark | Run | Tasks | Passed | Scored failed | Errors | Score sum | Agent calls | Runtime calls |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `omniroute/codex/gpt-5.5-high` | OmniRoute | `bitgn/pac1-dev` | `local_run_pi-exec-scratchpad-v1-gpt55-pac1-dev-full-20260527` | 43 | 26 | 17 | 0 | 26.0 | 538 `exec` | 1,548 |
| `omniroute/codex/gpt-5.5-high` | OmniRoute | `bitgn/pac1-prod` | `local_run_pi-exec-scratchpad-v1-gpt55-pac1-prod-full-20260527` | 104 | 72 | 32 | 0 | 72.0 | 1,742 `exec` | 2,743 |
| `omniroute/codex/gpt-5.5-high` | OmniRoute | `bitgn/ecom1-dev` | `local_run_pi-exec-scratchpad-v1-gpt55-ecom-dev-full-20260527` | 50 | 35 | 15 | 0 | 36.535 | 848 `exec` | 7,536 |

Compared with the prior Pi `exec` no-scratchpad runs, scratchpad-v1 improved PAC1 dev from 24 to 26 passed and PAC1 prod from 69 to 72 passed. ECOM dev improved from 31 to 35 passed, but the task set resolved as 50 tasks here versus 48 in the earlier run, and token usage grew sharply on catalogue/fraud tasks because scratchpad content is visible on each model iteration.

## Scratchpad Profiling and Compact v2

Profiling date: 2026-05-27. The full scratchpad-v1 runs show a small quality gain, but with much higher elapsed work. The scratchpad files are not large by themselves: PAC1 dev median 490B/max 1,686B, PAC1 prod median 609B/max 4,779B, ECOM dev median 570B/max 5,141B. The costly part was that the scratchpad/result payload is shown again on every model turn, and some ECOM Python scans returned very large JSON/text outputs into the chat transcript.

Detailed note: [notes/scratchpad-profiling-20260527.md](notes/scratchpad-profiling-20260527.md).

Full-run effect of scratchpad-v1 versus Pi `exec` without scratchpad:

| Benchmark | Baseline passed | Scratchpad-v1 passed | Passed delta | Baseline task-time | Scratchpad-v1 task-time | Task-time delta | Baseline avg prompt | Scratchpad-v1 avg prompt |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `bitgn/pac1-dev` | 24/43 | 26/43 | +2 | 1:11:44 | 2:28:02 | +106% | 52k | 53k |
| `bitgn/pac1-prod` | 69/104 | 72/104 | +3 | 3:37:03 | 6:16:12 | +73% | 69k | 74k |
| `bitgn/ecom1-dev` | 31/48 | 35/50 | +4 | 2:55:31 | 5:41:32 | +95% | 185k | 281k |

Field assessment from scratchpad-v1 artifacts:

| Keep | Why |
| --- | --- |
| `goal`, `target_scope`, `must_not_touch`, `mutation_plan` | Useful compact planning state for multi-step edits and destructive-action avoidance. |
| `identity_chain`, `key_evidence`, `evidence` | Useful when concise; should contain summaries and identifiers, not raw query rows. |
| `refs`, `final_candidate_refs` | Necessary for final `grounding_refs`; exact paths should be preserved. |
| `outcome`, `message`, `answer` | Helps final completion stay stable across the last iteration. |
| `validation_status`, `pre_submit_checks`, `remaining_risks` | Useful for final self-checks and stopping decisions. |

Fields that should be dropped or compacted in v2: `system_tree`, `cast_tree`, `inbox_tree`, `docs`, `inbox_file`, `inventory_query_result`, `availability_left_join`, `raw`, `raw_result`, `results`, and `search_results`. These duplicate recoverable workspace/tool data or replay large scans into the prompt.

Compact v2 profile on heavy ECOM task families, compared directionally against scratchpad-v1 for the same task IDs. ECOM trial seeds are not byte-identical across local runs, so this is a profiling signal rather than a strict A/B quality claim.

| Mode | Run | Tasks | Passed | Score sum | Task-time | Avg prompt | Prompt sum | LLM calls |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| scratchpad-v1 selected IDs | `local_run_pi-exec-scratchpad-v1-gpt55-ecom-dev-full-20260527` (`t15,t38,t49,t50`) | 4 | 2 | 2.323 | 29:20 | 622k | 2.49M | 54 |
| scratchpad-v2 + 40k output cap | `local_run_pi-exec-scratchpad-v2cap-gpt55-ecom-dev-profile-20260527` | 4 | 3 | 3.365 | 17:10 | 276k | 1.10M | 58 |
| scratchpad-v2 + 20k output cap | `local_run_pi-exec-scratchpad-v2cap20-gpt55-ecom-dev-profile-20260527` | 4 | 2 | 2.311 | 32:13 | 179k | 0.72M | 51 |

Result: v2 with the 40k cap cut prompt volume by about 56% and task-time by about 42% on these selected ECOM task IDs while improving the sample score. The more aggressive 20k cap cut tokens further, but lost one pass and ran slower on this sample, so it is not the default. Current recommendation: keep scratchpad optional, use `PANGOLIN_SCRATCHPAD_MODE=v2` for future scratchpad runs, and keep the default output cap at 40k unless a task-specific profiling run justifies lowering it.

## Codex 5.3 Medium Pi Scratchpad-v2 Dev Results

Non-leaderboard full dev runs from 2026-05-27 for `Pi agent + exec + scratchpad-v2`, using Codex 5.3 Medium through OmniRoute: `PI_MODEL='omniroute/codex/gpt-5.3-codex'`, `PANGOLIN_SCRATCHPAD=1`, `PANGOLIN_SCRATCHPAD_MODE=v2`, and `-p 10`. The Pi model-visible tool surface remained one custom tool, `exec`. For PAC1 dev, the runner now uses normal `StartRun`/`StartTrial` non-leaderboard trials because the old playground sandbox path is no longer supported by the benchmark API.

| Model | Provider | Benchmark | Run | Tasks | Passed | Failed | Errors | Score sum | Wall time | Task-time sum | Avg task | Avg prompt | LLM calls | Agent calls | Runtime calls |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `omniroute/codex/gpt-5.3-codex` | OmniRoute | `bitgn/ecom1-dev` | `local_run_pi-exec-scratchpad-v2-gpt53-medium-ecom-dev-full-20260527` | 50 | 17 | 33 | 0 | 17.785 | 27:46 | 3:53:16 | 280s | 187k | 557 | 461 `exec` | 15,498 |
| `omniroute/codex/gpt-5.3-codex` | OmniRoute | `bitgn/pac1-dev` | `local_run_pi-exec-scratchpad-v2-gpt53-medium-pac1-dev-full-20260527b` | 43 | 28 | 15 | 0 | 28.0 | 21:57 | 2:34:45 | 216s | 50k | 344 | 271 `exec` | 1,787 |

Summary: Codex 5.3 Medium is connected through OmniRoute and completes both dev environments with Pi `exec` plus scratchpad-v2. PAC1 dev landed at 28/43, above the earlier GPT 5.5 scratchpad-v1 PAC1 dev result of 26/43, but this is not a strict fixed-task A/B. ECOM dev landed at 17/50, materially below the GPT 5.5 scratchpad-v1 result of 35/50, while still completing all tasks without runner errors. Non-leaderboard verification found no `LEADERBOARD_SUBMIT` markers and no non-empty `leaderboard_run_id` values in the run artifacts.

## Latest Pi PAC1 Prod Result

Non-leaderboard full PAC1 prod runs with Pi backbone and GPT 5.5 through OmniRoute. The runs used the 1440s per-task timeout and `-p 10` parallelism.

| Mode | Model | Provider | Benchmark | Run | Tasks | Passed | Scored failed | Errors | Score sum | Tool calls |
| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Pi bash-wrapper | `omniroute/codex/gpt-5.5-high` | OmniRoute | `bitgn/pac1-prod` | `local_run_pi-gpt55-omni-pac1-prod-full-20260526` | 104 | 66 | 38 | 0 | 66.0 | n/a |
| Pi `exec` Python tool | `omniroute/codex/gpt-5.5-high` | OmniRoute | `bitgn/pac1-prod` | `local_run_pi-exec-gpt55-omni-pac1-prod-full-20260527` | 104 | 69 | 35 | 0 | 69.0 | 864 |

Latest window: `2026-05-27T07:07:44Z` to `2026-05-27T07:29:56Z`. Non-leaderboard verification: no `leaderboard_run_id` values and no leaderboard submission markers in the run artifacts. The Pi custom-tool surface contained only `exec` in the latest run.

## GPT 5.5 Runtime Comparison

Non-leaderboard GPT 5.5 runs, measured from local run artifacts. Wall time is elapsed local time from the first task start to the last task event. Task-time sum is the sum of each task's own elapsed time, so it shows total serial work independent of `-p 10` parallelism. Agent calls count the outer agent tool surface: Codex CLI `command_execution`, Pi `bash`, or Pi `exec`. Runtime tool calls count benchmark runtime-tool calls recorded in `tool_calls.jsonl`.

| Benchmark | Mode | Run | Tasks | Passed | Failed | Errors | Score sum | Wall time | Task-time sum | Avg task | Agent calls | Runtime tool calls |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `bitgn/pac1-dev` | Codex CLI native | `local_run_codex-gpt55-nonleader-pac1-20260526-full` | 43 | 25 | 18 | 0 | 25.0 | 19:45 | 2:50:29 | 238s | 1,134 `command_execution` | 1,196 |
| `bitgn/pac1-dev` | Pi bash-wrapper | `local_run_pi-gpt55-omni-pac1-dev-full-20260526` | 43 | 22 | 15 | 6 | 22.0 | 32:51 | 5:05:55 | 427s | 456 `bash` | 1,089 |
| `bitgn/pac1-dev` | Pi `exec` Python tool | `local_run_pi-exec-gpt55-omni-pac1-dev-full-20260527` | 43 | 24 | 19 | 0 | 24.0 | 9:30 | 1:12:10 | 101s | 285 `exec` | 1,434 |
| `bitgn/pac1-dev` | Pi `exec` + scratchpad-v1 | `local_run_pi-exec-scratchpad-v1-gpt55-pac1-dev-full-20260527` | 43 | 26 | 17 | 0 | 26.0 | 19:43 | 2:28:02 | 207s | 538 `exec` | 1,548 |
| `bitgn/ecom1-dev` | Codex CLI native | `local_run_codex-gpt55-nonleader-ecom-20260526-full` | 46 | 33 | 13 | 0 | 34.116 | 25:29 | 3:53:59 | 305s | 1,163 `command_execution` | 1,271 |
| `bitgn/ecom1-dev` | Pi bash-wrapper | `local_run_pi-gpt55-omni-ecom-dev-full-20260526` | 47 | 20 | 16 | 11 | 20.0 | 44:41 | 6:27:41 | 495s | 553 `bash` | 1,146 |
| `bitgn/ecom1-dev` | Pi `exec` Python tool | `local_run_pi-exec-gpt55-omni-ecom-dev-full-20260527` | 48 | 31 | 17 | 0 | 32.655 | 21:57 | 2:55:42 | 220s | 358 `exec` | 9,838 |
| `bitgn/ecom1-dev` | Pi `exec` + scratchpad-v1 | `local_run_pi-exec-scratchpad-v1-gpt55-ecom-dev-full-20260527` | 50 | 35 | 15 | 0 | 36.535 | 40:16 | 5:41:32 | 410s | 848 `exec` | 7,536 |
| `bitgn/ecom1-dev` | Pi `exec` + scratchpad-v2 + preflight | `local_run_pi-exec-scratchpad-v2-preflight-gpt55-ecom-dev-full-20260528` | 50 | 40 | 10 | 0 | 41.360 | 37:40 | 5:18:03 | 382s | 1,577 `exec` | 1,577 |
| `bitgn/ecom1-dev` | Pangolin loop + `execute_code` + scratchpad-v2 | `local_run_pangolin-gpt55-omni-ecom-dev-all-20260528` | 51 | 44 | 6 | 1 | 45.692 | 17:09 | 1:35:45 | 113s | 354 `execute_code` | 7,754 |
| `bitgn/pac1-prod` | Codex CLI native | `local_run_codex-gpt55-nonleader-pac1-prod-20260527-full` | 104 | 73 | 30 | 1 | 73.0 | 1:24:28 | 13:46:03 | 477s | 2,749 `command_execution` | 3,002 |
| `bitgn/pac1-prod` | Pi bash-wrapper | `local_run_pi-gpt55-omni-pac1-prod-full-20260526` | 104 | 66 | 38 | 0 | 66.0 | 56:21 | 8:26:49 | 292s | 1,216 `bash` | 2,678 |
| `bitgn/pac1-prod` | Pi `exec` Python tool | `local_run_pi-exec-gpt55-omni-pac1-prod-full-20260527` | 104 | 69 | 35 | 0 | 69.0 | 22:46 | 3:38:15 | 126s | 864 `exec` | 2,680 |
| `bitgn/pac1-prod` | Pi `exec` + scratchpad-v1 | `local_run_pi-exec-scratchpad-v1-gpt55-pac1-prod-full-20260527` | 104 | 72 | 32 | 0 | 72.0 | 41:33 | 6:16:12 | 217s | 1,742 `exec` | 2,743 |
| `bitgn/pac1-prod` | Codex CLI native repeat | `local_run_codex-gpt55-nonleader-pac1-prod-20260527-ab2` | 104 | 67 | 37 | 0 | 67.0 | 59:54 | 9:37:45 | 333s | 2,990 `command_execution` | 3,075 |
| `bitgn/pac1-prod` | Pi `exec` Python tool repeat | `local_run_pi-exec-gpt55-omni-pac1-prod-20260527-ab2` | 104 | 64 | 40 | 0 | 64.0 | 27:37 | 4:13:39 | 146s | 1,724 `exec` | 2,732 |

Reading: Pi `exec` materially reduces elapsed time and summed task time against the old Pi bash-wrapper path while removing runtime errors in these GPT 5.5 runs. On ECOM dev, the `exec` path used many more internal runtime-tool calls because archive-fraud tasks performed large Python-side scans, but still finished faster end to end.

Preflight run note: the 2026-05-28 ECOM dev preflight run used `PANGOLIN_SCRATCHPAD=1`, `PANGOLIN_SCRATCHPAD_MODE=v2`, `PI_TOOL_MODE=exec`, `NATIVE_PREFLIGHT_CONTEXT=1`, and `-p 10`. Compared with the previous best scratchpad-v2 ECOM dev run (`local_run_pi-exec-scratchpad-v2-wsanswer-gpt55-ecom-dev-agents-instr4-full-20260528`, 46/50, score 47.856, wall 36:31, task-time 5:06:45), this was a quality regression: 40/50, score 41.360, wall +1:09, task-time +11:18. It did reduce total tokens from 13.01M to 9.35M and runtime tool time from 5:42 to 2:07, but missing required update-doc refs caused several new failures (`t10`, `t12`, `t41`, `t42`, `t49`). Caveat: ECOM dev local task prompts are regenerated; only 4/50 task instructions were byte-identical between these two runs, so this is a run-level signal rather than a strict paired A/B.

Latest Pangolin run note: the 2026-05-28 ECOM dev run used the current BitGN run-level scoring lifecycle (`EndTrial`, then `SubmitRun(force=True)` and `GetRun` score backfill). It resolved 51 tasks from the API, including the first OCR task (`t51`). The run stayed well under one hour at `-p 10` (`17:09` wall), while serial task-time was `1:35:45`. Failed/partial tasks were `t38`, `t39`, and `t40` archive fraud partials, `t42` and `t49` missing required update-doc refs, `t51` OCR answer formatting (`0.6` partial), plus `t48` runner/API error from an OmniRoute Cloudflare 524 timeout after 17 iterations.

Latest full Pangolin ECOM dev comparison from 2026-05-29, after the benchmark resolved 53 tasks. These runs used `pangolin_loop`, one model-visible tool (`execute_code`), scratchpad-v2, `NATIVE_PREFLIGHT_CONTEXT=0`, `NATIVE_PANGOLIN_MAX_ITERATIONS=20`, `NATIVE_SESSION_TIMEOUT_SEC=1440`, `--no-leaderboard`, `--all`, and `-p 10`. Scores are from the BitGN run-level `SubmitRun`/`GetRun` backfill; provider/API failures such as OpenRouter `401` or OmniRoute/OpenRouter transport errors are separate from BitGN scoring.

| Model | Provider | Run | Tasks | Passed | Failed | Score sum | Wall time | Task-time sum | LLM calls | Tokens | Steps |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `codex/gpt-5.5-high` | OmniRoute | `local_run_pangolin-gpt55-guards-ecom-dev-full-20260529` | 53 | 47 | 6 | 48.872 | 12:55 | 1:23:17 | 345 | 4,799,451 | 7,932 |
| `codex/gpt-5.5-high` | OmniRoute | `local_run_evo10-final-gpt55-ecom-dev-full-20260529` | 53 | 48 | 5 | 49.857 | 12:07 | 1:18:56 | 336 | 4,432,637 | 8,699 |
| `qwen/qwen3.6-27b` | OpenRouter | `local_run_pangolin-qwen36-27b-guards-ecom-dev-full-20260529b` | 53 | 18 | 35 | 18.000 | 12:38 | 1:48:01 | 752 | 8,614,963 | 754 |
| `openai/gpt-5.4-nano` | OpenRouter | `local_run_pangolin-gpt54-nano-openrouter-ecom-dev-full-20260529` | 53 | 9 | 44 | 9.000 | 9:17 | 1:09:01 | 775 | 8,541,985 | 4,683 |
| `openai/gpt-5.4-mini` | OpenRouter | `local_run_pangolin-gpt54-mini-openrouter-ecom-dev-full-20260529` | 53 | 7 | 46 | 7.000 | 9:12 | 1:09:57 | 807 | 8,214,430 | 630 |

The latest GPT 5.5 prompt-only evolution run improved to `49.857/53` with `48/53` exact passes. Remaining failed or partial tasks were `t38`, `t39`, and `t40` archive-fraud false positives, `t45` invalid catalogue reference, and `t48` archive amount mismatch. Qwen completed a valid OpenRouter run only after forcing `NATIVE_PANGOLIN_API_KEY` to the OpenRouter key; the first attempt used the wrong key priority and got `401 Missing Authentication header`. In the valid run, Qwen passed 18 tasks, received zero score on 18 submitted tasks, and 17 tasks hit the iteration limit without a final scored submission. Common Qwen failure classes were missing exact answer tokens such as `<YES>`, wrong security/outcome choices, missing required refs, and many short low-progress cycles until `max_iterations`. GPT 5.4 Nano also required forcing `NATIVE_PANGOLIN_API_KEY` to the OpenRouter key. It passed 9 tasks, had 17 scored zero submissions, and 27 runner-level failures where the Pangolin loop ended without `finish`/`ws.answer`/`report_completion` or timed out inside the Python exec tool.

GPT 5.4 Nano OpenRouter cost estimate for this run: `$0.865`. This uses all `api_call` events, including failed tasks: 8,325,730 prompt tokens, 216,255 completion tokens, and 5,946,880 cached prompt tokens. OpenRouter model pricing on 2026-05-29 was prompt `$0.20/M`, cached input `$0.02/M`, completion `$1.25/M`; formula: `(8,325,730 - 5,946,880) * 0.20/M + 5,946,880 * 0.02/M + 216,255 * 1.25/M`. Without the cache discount, the same token volume would be about `$1.935`. Source: [OpenRouter GPT-5.4 Nano](https://openrouter.ai/openai/gpt-5.4-nano).

GPT 5.4 Mini OpenRouter cost estimate for this run: `$2.761`. This uses all `api_call` events, including failed tasks: 8,113,430 prompt tokens, 101,000 completion tokens, and 5,598,208 cached prompt tokens. OpenRouter model pricing on 2026-05-29 was prompt `$0.75/M`, cached input `$0.075/M`, completion `$4.50/M`; formula: `(8,113,430 - 5,598,208) * 0.75/M + 5,598,208 * 0.075/M + 101,000 * 4.50/M`. Source: [OpenRouter GPT-5.4 Mini](https://openrouter.ai/openai/gpt-5.4-mini).

Cost/time comparison for the latest full ECOM dev runs, using task finish timestamps from `run_manifest.jsonl` and all Pangolin `api_call` usage events:

| Model | Provider | Passed | Score sum | Wall time | Task-time sum | Estimated model cost |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `codex/gpt-5.5-high` | OmniRoute | 48/53 | 49.857 | 12:07 | 1:18:56 | n/a: local OmniRoute config records cost as 0 |
| `qwen/qwen3.6-27b` | OpenRouter | 18/53 | 18.000 | 12:38 | 1:48:01 | `$2.850` |
| `openai/gpt-5.4-nano` | OpenRouter | 9/53 | 9.000 | 9:17 | 1:09:01 | `$0.865` |
| `openai/gpt-5.4-mini` | OpenRouter | 7/53 | 7.000 | 9:12 | 1:09:57 | `$2.761` |

## GPT 5.5 Honest A/B - PAC1 Prod

Experiment date: 2026-05-27. Goal: compare unchanged Codex CLI native and Pi `exec` Python-tool backbones on `bitgn/pac1-prod`, using GPT 5.5 only, `--no-leaderboard`, `--all`, and `-p 10`. No instructions, code, tool surface, or architecture were changed for these runs.

Detailed notes: [notes/gpt55-codex-vs-pi-exec-ab-pac1-prod-20260527.md](notes/gpt55-codex-vs-pi-exec-ab-pac1-prod-20260527.md).

| Backbone | Run | Tasks | Passed | Failed | Errors | Wall time | Task-time sum | Avg task | Agent calls | Runtime calls |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Codex CLI native | `local_run_codex-gpt55-nonleader-pac1-prod-20260527-ab2` | 104 | 67 | 37 | 0 | 59:54 | 9:37:45 | 333s | 2,990 `command_execution` | 3,075 |
| Pi `exec` Python tool | `local_run_pi-exec-gpt55-omni-pac1-prod-20260527-ab2` | 104 | 64 | 40 | 0 | 27:37 | 4:13:39 | 146s | 1,724 `exec` | 2,732 |

Repeat context: the earlier same-day PAC1 prod pair was Codex `73/104` and Pi `69/104`; this repeat was Codex `67/104` and Pi `64/104`. Codex is ahead by 3-4 aggregate tasks in both pairs, but each backbone also moved by 5-6 tasks between repeats.

Important caveat: `pac1-prod` task IDs are not fixed identical prompts across local runs. In the current pair, all 104 task IDs overlapped, but only 8 had byte-identical `instruction.txt` values between Codex and Pi. On those 8 exact-instruction tasks, both passed 3; Codex-only passed `t089`, and Pi-only passed `t032`. So the aggregate result suggests a small Codex edge, but the strict paired slice is tied and too small for a strong statistical claim.

Failure shape from `score.json`: both had 11 security-outcome misses. Pi had more structured-write failures (`6` invalid YAML/frontmatter syntax and `9` body mismatches) than Codex (`1` invalid YAML/frontmatter syntax and `4` body mismatches). Codex had `6` outbox filename/timestamp mismatches where it used runtime-current timestamps. This points to Codex being somewhat stronger at byte-preserving markdown edits, while Pi is much faster because it batches work through one Python `exec` call.

Prompt/loop difference: both receive the same local rules and benchmark VM policy. Codex is told to call runtime tools through `python runtime_tools.py <tool> ...` under `codex exec`. Pi is told the only agent tool is `exec`, and Python inside it calls BitGN tools through `call_tool(...)`; Pi is launched with `--no-session`, no context files, no builtin tools, and only `--tools exec`. These historical comparison runs used the cold baseline with no scratchpad enabled; workbook, analytics, rule evolution, validators, and Pangolin loop remain excluded.

Conclusion: Codex CLI native remains the slightly stronger cold quality baseline on these PAC1 prod runs. Pi `exec` remains the much faster minimal-tool baseline. A clean stability claim needs fixed task snapshots or a benchmark mode that reuses identical task instances across backbones.
