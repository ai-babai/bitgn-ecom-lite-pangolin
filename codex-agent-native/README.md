# codex-agent-native

Native BitGN task runner used by the Lite Pangolin setup.

English | [Русская версия](./README.ru.md)

## Role in the repo

This module runs one isolated benchmark task attempt at a time and stores all
artifacts needed to debug it later. The strongest path today is `pangolin_loop`,
where the model sees one tool, `execute_code`, and performs VM work through
Python helpers.

## Main flow

1. Resolve benchmark tasks and prepare a run.
2. Start a trial lazily when a worker begins that task.
3. Create an isolated attempt workspace.
4. Snapshot local rules and benchmark context.
5. Run the selected backbone: Pangolin, Codex CLI, or Pi.
6. Submit through `finish(...)`, `ws.answer(...)`, or `report_completion`.
7. End the trial, write `score.json`, and append `run_manifest.jsonl`.
8. Submit the run and backfill run-level scores when available.

## Important files

- `runner.py`: orchestration, parallelism, trial lifecycle, scoring, manifests.
- `pi_exec_tool.py`: Python execution environment used by Pangolin/Pi `exec`.
- `tool_gateway.py`: BitGN VM API adapter for ECOM, PAC, and sandbox tools.
- `scratchpad.py`: compact scratchpad profiles and compaction helpers.
- `local-rules/`: local task instructions copied into every attempt.

## Artifact layout

```text
runs/<local_run_id>/
  run_manifest.jsonl
  tNN/attempt_<timestamp>_<id>/
    events.jsonl
    tool_calls.jsonl
    submission.json
    score.json
    session/
      pangolin_events.jsonl
      pangolin_prompt.txt
      pangolin_scratchpad.json
      pangolin_state.json
```

`runs/` is intentionally ignored by git.
