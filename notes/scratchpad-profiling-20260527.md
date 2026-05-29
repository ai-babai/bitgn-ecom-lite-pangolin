# Scratchpad profiling - 2026-05-27

Scope: Pi loop agent + one `exec` Python tool on GPT 5.5 high, non-leaderboard. The goal was to check whether the optional Pangolin-style scratchpad was too heavy, decide which fields are worth keeping, and test compacting without changing the backbone architecture.

## Full-run scratchpad-v1 effect

| Benchmark | No-scratchpad passed | Scratchpad-v1 passed | Delta | No-scratchpad task-time | Scratchpad-v1 task-time | Task-time delta | Avg prompt delta |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `bitgn/pac1-dev` | 24/43 | 26/43 | +2 | 1:11:44 | 2:28:02 | +106% | 52k -> 53k |
| `bitgn/pac1-prod` | 69/104 | 72/104 | +3 | 3:37:03 | 6:16:12 | +73% | 69k -> 74k |
| `bitgn/ecom1-dev` | 31/48 | 35/50 | +4 | 2:55:31 | 5:41:32 | +95% | 185k -> 281k |

The quality gain is real but modest. Runtime cost is large, especially on ECOM.

## What was heavy

Final scratchpad JSON files were small:

| Run | Median final scratchpad | Max final scratchpad |
| --- | ---: | ---: |
| PAC1 dev scratchpad-v1 | 490B | 1,686B |
| PAC1 prod scratchpad-v1 | 609B | 4,779B |
| ECOM dev scratchpad-v1 | 570B | 5,141B |

The expensive part was not the JSON file alone. The model sees scratchpad/result data again on every turn, and ECOM tasks sometimes returned huge scan outputs into `exec` result/stdout. In scratchpad-v1 ECOM, raw Pi event files hit 18.3MB on `t40`, 13.2MB on `t38`, 12.7MB on `t39`, and 8.0MB on `t15`.

## Field decision

Keep compact versions of these fields: `goal`, `target_scope`, `must_not_touch`, `mutation_plan`, `identity_chain`, `key_evidence`, `evidence`, `refs`, `final_candidate_refs`, `outcome`, `message`, `answer`, `validation_status`, `pre_submit_checks`, and `remaining_risks`.

Drop or compact these fields: `system_tree`, `cast_tree`, `inbox_tree`, `docs`, `inbox_file`, `inventory_query_result`, `availability_left_join`, `raw`, `raw_result`, `results`, and `search_results`.

Reasoning: the kept fields carry decisions, exact references, and final-answer state. The dropped fields duplicate recoverable workspace/tool data or replay large scan payloads into the next prompt.

## Compact v2 experiment

Implemented `PANGOLIN_SCRATCHPAD_MODE=v2`: compact scratchpad before saving/returning, profile raw/view sizes, and cap returned `exec` output. The default v2 cap is 40k characters; it remains overrideable with `NATIVE_EXEC_OUTPUT_LIMIT` or `NATIVE_EXEC_TOOL_TEXT_LIMIT`.

Directional ECOM profile on selected heavy task IDs:

| Mode | Run | Tasks | Passed | Score sum | Task-time | Avg prompt | Prompt sum | LLM calls |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| scratchpad-v1 selected IDs | `local_run_pi-exec-scratchpad-v1-gpt55-ecom-dev-full-20260527` (`t15,t38,t49,t50`) | 4 | 2 | 2.323 | 29:20 | 622k | 2.49M | 54 |
| scratchpad-v2 + 40k cap | `local_run_pi-exec-scratchpad-v2cap-gpt55-ecom-dev-profile-20260527` | 4 | 3 | 3.365 | 17:10 | 276k | 1.10M | 58 |
| scratchpad-v2 + 20k cap | `local_run_pi-exec-scratchpad-v2cap20-gpt55-ecom-dev-profile-20260527` | 4 | 2 | 2.311 | 32:13 | 179k | 0.72M | 51 |

The 40k v2 profile reduced prompt volume about 56% and task-time about 42% versus scratchpad-v1 on the selected task IDs, with better sample score. The 20k cap reduced tokens further but lost a pass and ran slower on this sample, so it was rejected as the default.

## Recommendation

Use scratchpad only when explicitly testing Pangolin memory. Prefer `PANGOLIN_SCRATCHPAD_MODE=v2` for future scratchpad runs. Keep the default v2 output cap at 40k to preserve quality, and lower it only in targeted experiments.
