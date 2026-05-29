# GPT 5.5 Codex vs Pi exec PAC1 prod A/B - 2026-05-27

Purpose: compare the unchanged cold-baseline backbones on `bitgn/pac1-prod` using GPT 5.5, without leaderboard submission and without changing code, instructions, prompts, tools, or architectures during the experiment.

Commands:

```bash
BITGN_API_KEY='' BITGN_API_KEY_FILE=/tmp/bitgn-no-key \
CODEX_MODEL='codex/gpt-5.5-high' \
LOCAL_RUN_ID='codex-gpt55-nonleader-pac1-prod-20260527-ab2' \
./run-codex-native.sh --env pac1-prod --no-leaderboard --all -p 10

BITGN_API_KEY='' BITGN_API_KEY_FILE=/tmp/bitgn-no-key \
PI_MODEL='omniroute/codex/gpt-5.5-high' \
LOCAL_RUN_ID='pi-exec-gpt55-omni-pac1-prod-20260527-ab2' \
./run-pi-native.sh --env pac1-prod --no-leaderboard --all -p 10
```

## Aggregate Results

| Run | Backbone | Tasks | Passed | Failed | Errors | Score | Wall time | Task-time sum | Avg task | Agent calls | Runtime calls |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `local_run_codex-gpt55-nonleader-pac1-prod-20260527-ab2` | Codex CLI native | 104 | 67 | 37 | 0 | 67.0 | 59:54 | 9:37:45 | 333s | 2,990 `command_execution` | 3,075 |
| `local_run_pi-exec-gpt55-omni-pac1-prod-20260527-ab2` | Pi `exec` Python tool | 104 | 64 | 40 | 0 | 64.0 | 27:37 | 4:13:39 | 146s | 1,724 `exec` | 2,732 |

Both runs were non-leaderboard: every manifest row had `leaderboard_run_id: null`.

## Repeat Context

| Backbone | Earlier run | Earlier passed | Repeat run | Repeat passed | Delta |
| --- | --- | ---: | --- | ---: | ---: |
| Codex CLI native | `local_run_codex-gpt55-nonleader-pac1-prod-20260527-full` | 73 | `local_run_codex-gpt55-nonleader-pac1-prod-20260527-ab2` | 67 | -6 |
| Pi `exec` Python tool | `local_run_pi-exec-gpt55-omni-pac1-prod-full-20260527` | 69 | `local_run_pi-exec-gpt55-omni-pac1-prod-20260527-ab2` | 64 | -5 |

Codex is ahead by 4 tasks in the earlier pair and by 3 tasks in the repeat pair. That suggests a small aggregate edge for Codex on this benchmark, but the run-to-run spread is similar to the observed edge.

## Pairing Caveat

`pac1-prod` task IDs are not stable fixed prompts across local runs. In the current paired run, all 104 task IDs overlapped, but only 8 had byte-identical `instruction.txt` values between Codex and Pi. On those 8 exact-instruction tasks:

| Subset | Tasks | Codex passed | Pi passed | Both pass | Both fail | Codex-only wins | Pi-only wins |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| Current exact-instruction overlap | 8 | 3 | 3 | 2 | 4 | `t089` | `t032` |

So the current strict A/B slice is tied. The aggregate comparison is still useful operationally, but it is not a clean per-task paired statistical test.

Repeat stability on exact same instructions within each backbone was also small-sample:

| Backbone repeat | Same instructions | First pass | Repeat pass | Both pass | Both fail | First-only | Repeat-only |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| Codex old -> `ab2` | 16 | 7 | 8 | 6 | 7 | `t016` | `t019`, `t052` |
| Pi old -> `ab2` | 7 | 4 | 4 | 4 | 3 | none | none |

## Failure Shape

Failure categories are based on each failed attempt's `score.json` details.

| Category | Codex failures | Pi failures | Reading |
| --- | ---: | ---: | --- |
| Security outcome mismatch | 11 | 11 | Similar rate; both often acted when evaluator expected denial. |
| Clarification or unsupported outcome mismatch | 7 | 3 | Codex more often gave an actionable answer when evaluator expected clarification/unsupported. |
| Wrong direct answer | 3 | 4 | Similar. |
| Invalid YAML/frontmatter syntax | 1 | 6 | Pi had more malformed outbound/frontmatter writes. |
| Frontmatter field mismatch | 5 | 5 | Similar. |
| Body mismatch after structured write | 4 | 9 | Pi more often introduced a byte-level body-preservation mismatch while adding frontmatter. |
| Missing grounding/reference | 0 | 2 | Pi missed required grounding refs in two OCR/migration tasks. |
| Other outbox filename/timestamp mismatch | 6 | 0 | Codex used runtime-current outbox filenames in several email tasks where evaluator expected task-visible timestamps. |

## Interpretation

The honest reading is: Codex CLI native is probably a little better on aggregate pass count here, but this experiment does not prove a large stable quality gap. The two full pairs show Codex at `73 -> 67` and Pi exec at `69 -> 64`; the difference is only 3-4 tasks while each backbone moved by 5-6 tasks between repeats.

What is clearer is the speed/tooling tradeoff. Pi `exec` is much faster: `27:37` wall time and `4:13:39` task-time sum versus Codex `59:54` wall time and `9:37:45` task-time sum on the repeat. Pi batches work inside one Python tool and uses fewer outer agent turns. Codex used 2,990 outer command executions versus Pi's 1,724 `exec` calls, with similar internal runtime-tool volume. That extra Codex loop time likely gives more chances to inspect and correct, but it is expensive.

Prompt and architecture differences visible in artifacts:

- Both paths embed the same local rules and the same benchmark-provided workspace rules.
- Codex is instructed to call runtime tools via `python runtime_tools.py <tool> key=value ...` and runs through `codex exec`.
- Pi is instructed that the only agent tool is `exec`; Python code inside that tool reaches BitGN tools through `call_tool(...)`.
- Pi is launched with `--no-session --no-context-files --no-skills --no-prompt-templates --no-themes --no-builtin-tools --tools exec`.

There is no Pangolin memory in this repo. The project rules explicitly exclude Pangolin, scratchpad, workbook, analytics, rule evolution, and validators; Pi is also launched with `--no-session`.

Likely causes of the remaining Codex edge:

- More native agent micro-iterations and shell-level inspection before completion.
- Better byte-preservation behavior on structured markdown edits; Pi `exec` had more body mismatch and YAML syntax failures.
- Codex may have stronger built-in command-use habits, but the artifacts do not expose any hidden internal representation, so that remains an inference rather than something proven.

Likely causes of Pi's speed advantage:

- One Python `exec` can batch many runtime tool calls.
- Less outer-loop overhead and fewer agent/tool round trips.
- No built-in tools, context-file loading, sessions, skills, prompt templates, or themes.

Conclusion: keep Codex CLI native as the slightly stronger cold quality baseline, and keep Pi `exec` as the much faster minimal-tool baseline. A stronger statistical claim would need a benchmark mode with fixed task instances or repeated runs over exported identical task snapshots.
