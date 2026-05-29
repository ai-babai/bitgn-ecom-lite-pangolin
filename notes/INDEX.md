# Notes - ecom-small-agent-test

Local notes for cold native baseline experiments. Keep run summaries short and link to artifacts under `codex-agent-native/runs/`.

## Pangolin GPT 5.5 ECOM dev run-level scoring update - 2026-05-28

Full non-leaderboard run for `pangolin_loop + execute_code + scratchpad-v2`, using `codex/gpt-5.5-high` through OmniRoute and `-p 10`, after the BitGN harness moved scoring to run close.

| Benchmark | Run | Tasks | Passed | Scored failed | Errors | Score sum | Wall time | Task-time sum | Avg task | Agent calls | Runtime calls |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `bitgn/ecom1-dev` | `local_run_pangolin-gpt55-omni-ecom-dev-all-20260528` | 51 | 44 | 6 | 1 | 45.692 | 17:09 | 1:35:45 | 113s | 354 `execute_code` | 7,754 |

Reading: the run fits comfortably under an hour in parallel mode. Serial summed task time is about 1h36m. Remaining misses were archive-fraud partials (`t38`, `t39`, `t40`), missing required update docs (`t42`, `t49`), one OCR formatting partial (`t51`), and one OmniRoute 524 timeout on archive TSV fraud (`t48`). The run lifecycle closed every task with `EndTrial`, then closed the prepared run with `SubmitRun(force=True)` and backfilled task scores from `GetRun`.

## Scratchpad profiling - 2026-05-27

Profiling note: [scratchpad-profiling-20260527.md](scratchpad-profiling-20260527.md). Short result: scratchpad-v1 improved quality by +2 PAC1 dev, +3 PAC1 prod, and +4 ECOM dev passes, but roughly doubled task-time on dev runs. Compact v2 with a 40k `exec` output cap cut prompt volume by about 56% and task-time by about 42% on selected heavy ECOM task IDs while preserving the sample quality signal. The more aggressive 20k cap was rejected as default because it lost a pass and ran slower in the sample.

## Codex 5.3 Medium Pi scratchpad-v2 dev runs - 2026-05-27

Full non-leaderboard dev runs for `Pi agent + exec + scratchpad-v2`, using `omniroute/codex/gpt-5.3-codex` through OmniRoute, `PANGOLIN_SCRATCHPAD=1`, `PANGOLIN_SCRATCHPAD_MODE=v2`, and `-p 10`.

| Benchmark | Run | Tasks | Passed | Failed | Errors | Score sum | Wall time | Task-time sum | Agent calls | Runtime calls |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `bitgn/ecom1-dev` | `local_run_pi-exec-scratchpad-v2-gpt53-medium-ecom-dev-full-20260527` | 50 | 17 | 33 | 0 | 17.785 | 27:46 | 3:53:16 | 461 `exec` | 15,498 |
| `bitgn/pac1-dev` | `local_run_pi-exec-scratchpad-v2-gpt53-medium-pac1-dev-full-20260527b` | 43 | 28 | 15 | 0 | 28.0 | 21:57 | 2:34:45 | 271 `exec` | 1,787 |

Verification: no leaderboard submission markers or non-empty `leaderboard_run_id` values were found in these run artifact directories. PAC1 dev used normal non-leaderboard `StartRun`/`StartTrial` preparation because the older playground sandbox mode is no longer accepted by the BitGN API.

## Pi exec Python tool dev runs - 2026-05-27

Full non-leaderboard dev runs for `Pi loop agent + exec Python tool`, using only `omniroute/codex/gpt-5.5-high`. The Pi custom-tool surface was verified from raw session events: only one tool name, `exec`, appeared in both runs.

| Benchmark | Mode | Run | Tasks | Passed | Scored failed | Errors | Score sum | Tool calls | Delta vs prior Pi bash-wrapper GPT 5.5 |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `bitgn/pac1-dev` | prior Pi bash-wrapper | `local_run_pi-gpt55-omni-pac1-dev-full-20260526` | 43 | 22 | 15 | 6 | 22.0 | n/a | baseline |
| `bitgn/pac1-dev` | Pi `exec` Python tool | `local_run_pi-exec-gpt55-omni-pac1-dev-full-20260527` | 43 | 24 | 19 | 0 | 24.0 | 285 | +2 passed, -6 errors |
| `bitgn/ecom1-dev` | prior Pi bash-wrapper | `local_run_pi-gpt55-omni-ecom-dev-full-20260526` | 47 | 20 | 16 | 11 | 20.0 | n/a | baseline |
| `bitgn/ecom1-dev` | Pi `exec` Python tool | `local_run_pi-exec-gpt55-omni-ecom-dev-full-20260527` | 48 | 31 | 17 | 0 | 32.655 | 358 | +11 passed, -11 errors; task count resolved as 48 |

Verification:

- Model: `omniroute/codex/gpt-5.5-high` through OmniRoute.
- Leaderboard: `leaderboard_run_id` count was `0` for both runs; no leaderboard submission markers were found in artifacts.
- Tool surface: raw Pi events contained only `toolName=exec` (`285` calls on PAC1 dev, `358` calls on ECOM dev).
- Artifact paths: `codex-agent-native/runs/local_run_pi-exec-gpt55-omni-pac1-dev-full-20260527/` and `codex-agent-native/runs/local_run_pi-exec-gpt55-omni-ecom-dev-full-20260527/`.

Detailed ECOM task breakdown: [ecom1-dev-pi-exec-task-breakdown-20260527.md](ecom1-dev-pi-exec-task-breakdown-20260527.md).

## GPT 5.5 Codex vs Pi exec PAC1 prod A/B - 2026-05-27

Fresh unchanged non-leaderboard repeat runs on `bitgn/pac1-prod`, both with `-p 10` and GPT 5.5 only.

| Backbone | Run | Tasks | Passed | Failed | Errors | Wall time | Task-time sum | Agent calls | Runtime calls |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Codex CLI native | `local_run_codex-gpt55-nonleader-pac1-prod-20260527-ab2` | 104 | 67 | 37 | 0 | 59:54 | 9:37:45 | 2,990 | 3,075 |
| Pi `exec` Python tool | `local_run_pi-exec-gpt55-omni-pac1-prod-20260527-ab2` | 104 | 64 | 40 | 0 | 27:37 | 4:13:39 | 1,724 | 2,732 |

Short reading: Codex had a small aggregate pass-count edge; Pi was much faster. Only 8 task IDs had byte-identical instructions across the two current runs, and that strict paired slice was tied at 3 passed each.

Detailed note: [gpt55-codex-vs-pi-exec-ab-pac1-prod-20260527.md](gpt55-codex-vs-pi-exec-ab-pac1-prod-20260527.md).

## Pi exec Python tool PAC1 prod run - 2026-05-27

Full non-leaderboard PAC1 prod run for `Pi loop agent + exec Python tool`, using `omniroute/codex/gpt-5.5-high`.

| Benchmark | Run | Tasks | Passed | Scored failed | Errors | Score sum | Tool calls |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `bitgn/pac1-prod` | `local_run_pi-exec-gpt55-omni-pac1-prod-full-20260527` | 104 | 69 | 35 | 0 | 69.0 | 864 |

Verification:

- Leaderboard: `leaderboard_run_id` count was `0`; no leaderboard submission markers were found in artifacts.
- Tool surface: raw Pi events contained only `toolName=exec`.
- Window: `2026-05-27T07:07:44Z` to `2026-05-27T07:29:56Z`.
- Artifact path: `codex-agent-native/runs/local_run_pi-exec-gpt55-omni-pac1-prod-full-20260527/`.
