# Lite Pangolin Architecture

This document describes the current Pangolin-loop runner for BitGN ECOM at a
high level. The implementation is intentionally small: the model gets one tool,
and the Python runtime keeps the benchmark contract stable.

[Русская версия](./ARCHITECTURE.ru.md)

## 1) Core idea

Lite Pangolin is a single-tool agent loop:

```text
BitGN task
  -> runner prompt
  -> model response
  -> execute_code(code)
  -> Python helpers inside task workspace
  -> BitGN VM tools through ToolGateway
  -> finish(...)/ws.answer(...)
  -> EndTrial / SubmitRun / GetRun
```

The model writes Python code, but it does not receive separate model-visible
tools for `read`, `search`, `write`, `checkout`, `discount`, or `payments`.
Those are available only inside the Python helper layer.

## 2) Why one visible tool

The single-tool surface keeps weaker models from drifting across many tool
schemas. It also makes protocol repair easier:

- every action enters through `execute_code`,
- all runtime calls are logged consistently,
- finalization can be guarded in one place,
- scratchpad compaction can happen between model turns.

The model still chooses the strategy and writes the task code. The runtime only
stabilizes mechanics: paths, refs, submission shape, and evidence tracking.

## 3) Runner responsibilities

`codex-agent-native/runner.py` handles orchestration:

- resolves task ids from `GetBenchmark` when `--all` is used,
- prepares normal or leaderboard runs through `StartRun`,
- starts each trial lazily when a worker begins the task,
- creates an isolated per-task workspace,
- injects local rules and benchmark-provided context,
- runs the Pangolin model loop with a configurable iteration cap,
- closes each task with `EndTrial`,
- closes the whole run with `SubmitRun(force=True)`,
- backfills scores with `GetRun` when the benchmark exposes them.

Lazy `StartTrial` matters for leaderboard/prod runs: queued local tasks do not
consume platform task time before the worker actually starts solving.

## 4) Tool boundary

`codex-agent-native/pi_exec_tool.py` provides the Python execution environment.
Inside `execute_code`, the model can use:

- `call_tool(tool, **kwargs)` for direct VM tool calls,
- `run(path, args=[], stdin='')` for executable VM helpers,
- `finish(message, outcome='OUTCOME_OK', refs=[], answer=None)` for final
  submission,
- `ws` helper methods for Pangolin-style read/write/answer flows,
- `scratchpad`, a persistent JSON-serializable task memory object.

`codex-agent-native/tool_gateway.py` translates these calls into BitGN ECOM/PAC
VM APIs and records every call into `tool_calls.jsonl`.

## 5) Scratchpad and compaction

The current default is scratchpad-v2:

- keep goal, current scope, concise evidence, answer/outcome, and exact refs;
- drop raw trees, large query results, full records, and duplicate bulky fields;
- return a compact view to the model on the next iteration;
- keep full raw history in local artifacts instead of replaying it into context.

This is a runtime memory mechanism, not an extra model-visible tool.

## 6) Finalization contract

A task is considered locally successful only after a real submission is written:

```text
finish(...) or ws.answer(...)
  -> report_completion
  -> submission.json
  -> EndTrial
  -> score.json / pending score marker
```

If the model reaches the iteration cap without `finish`, `ws.answer`, or
`report_completion`, the runner records an `agent_error`. Raising the cap from
20 to 36 helped DeepSeek V4 Flash reduce these finalization misses on ECOM dev,
but it also increased total task time and token use.

## 7) Run artifacts

Each task attempt stores enough information to reproduce and analyze behavior:

```text
events.jsonl                  stage timeline
tool_calls.jsonl              VM/runtime calls
submission.json               final answer payload
score.json                    score, detail, usage, steps
session/pangolin_events.jsonl model/tool loop events
session/pangolin_scratchpad.json
session/pangolin_state.json
session/pangolin_prompt.txt
```

The run root stores `run_manifest.jsonl`, which is used for summary tables,
wall-time estimates, and failure analysis.

## 8) Current operating profile

Production-quality Lite Pangolin runs use:

- GPT 5.5 High through OmniRoute for the strongest public runs,
- `-p 10` for GPT 5.5 full ECOM runs,
- `-p 5` and `NATIVE_PANGOLIN_MAX_ITERATIONS=36` for DeepSeek V4 Flash
  experiments,
- `NATIVE_PREFLIGHT_CONTEXT=0`, because preflight gave inconsistent speed gains
  and increased missed-reference failures,
- `PANGOLIN_SCRATCHPAD_MODE=v2` for compact memory.

## 9) What overfit means here

The `operation-overfit` result is a reference point, not the agent architecture.
It estimates what can be achieved by fitting rules/code toward known benchmark
patterns. Lite Pangolin is evaluated as a general task-solving loop that still
reads the environment and grounds each answer at runtime.
