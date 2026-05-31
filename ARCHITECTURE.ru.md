# Архитектура Lite Pangolin

Документ описывает текущий Pangolin-loop runner для BitGN ECOM на верхнем
уровне. Реализация намеренно компактная: модель видит один инструмент, а Python
runtime удерживает стабильный benchmark contract.

[English version](./ARCHITECTURE.md)

## 1) Базовая идея

Lite Pangolin — это single-tool agent loop:

```text
BitGN task
  -> runner prompt
  -> model response
  -> execute_code(code)
  -> Python helpers внутри task workspace
  -> BitGN VM tools через ToolGateway
  -> finish(...)/ws.answer(...)
  -> EndTrial / SubmitRun / GetRun
```

Модель пишет Python-код, но не получает отдельные model-visible tools для
`read`, `search`, `write`, `checkout`, `discount` или `payments`. Они доступны
только внутри Python helper layer.

## 2) Почему один видимый инструмент

Один tool surface снижает риск того, что слабые модели начнут путаться в
нескольких schemas. Это также упрощает runtime repair:

- каждое действие входит через `execute_code`,
- все runtime calls логируются одинаково,
- finalization guard находится в одном месте,
- scratchpad можно компактить между model turns.

Модель по-прежнему выбирает стратегию и пишет код решения. Runtime стабилизирует
механику: paths, refs, submission shape и evidence tracking.

## 3) Ответственность runner

`codex-agent-native/runner.py` отвечает за orchestration:

- резолвит task ids через `GetBenchmark`, когда используется `--all`,
- готовит normal или leaderboard runs через `StartRun`,
- стартует каждый trial лениво, только когда worker начинает задачу,
- создает изолированный workspace на задачу,
- инжектит local rules и benchmark-provided context,
- запускает Pangolin model loop с настраиваемым iteration cap,
- закрывает каждую задачу через `EndTrial`,
- закрывает весь run через `SubmitRun(force=True)`,
- backfill scores через `GetRun`, если benchmark их раскрывает.

Lazy `StartTrial` важен для leaderboard/prod runs: задачи, которые стоят в
локальной очереди, не тратят platform task time до фактического старта worker.

## 4) Tool boundary

`codex-agent-native/pi_exec_tool.py` дает Python execution environment. Внутри
`execute_code` модель может использовать:

- `call_tool(tool, **kwargs)` для прямых VM tool calls,
- `run(path, args=[], stdin='')` для executable VM helpers,
- `finish(message, outcome='OUTCOME_OK', refs=[], answer=None)` для финального
  submit,
- `ws` helper methods для Pangolin-style read/write/answer flow,
- `scratchpad`, persistent JSON-serializable task memory.

`codex-agent-native/tool_gateway.py` переводит эти вызовы в BitGN ECOM/PAC VM
API и записывает каждый вызов в `tool_calls.jsonl`.

## 5) Scratchpad и compaction

Текущий default — scratchpad-v2:

- сохранять goal, current scope, concise evidence, answer/outcome и exact refs;
- выбрасывать raw trees, большие query results, полные records и дублирующие
  bulky fields;
- возвращать модели компактный view на следующей итерации;
- полную raw history хранить в локальных artifacts, а не проигрывать обратно в
  context.

Это runtime memory mechanism, а не дополнительный model-visible tool.

## 6) Finalization contract

Задача считается локально успешной только после реального submission:

```text
finish(...) или ws.answer(...)
  -> report_completion
  -> submission.json
  -> EndTrial
  -> score.json / pending score marker
```

Если модель дошла до iteration cap без `finish`, `ws.answer` или
`report_completion`, runner пишет `agent_error`. Увеличение cap с 20 до 36
помогло DeepSeek V4 Flash на ECOM dev уменьшить такие finalization misses, но
увеличило task time и token usage.

## 7) Run artifacts

Каждая task attempt сохраняет достаточно данных для анализа поведения:

```text
events.jsonl                  timeline стадий
tool_calls.jsonl              VM/runtime calls
submission.json               final answer payload
score.json                    score, detail, usage, steps
session/pangolin_events.jsonl model/tool loop events
session/pangolin_scratchpad.json
session/pangolin_state.json
session/pangolin_prompt.txt
```

В корне run лежит `run_manifest.jsonl`; по нему собираются summary tables,
wall-time estimates и failure analysis.

## 8) Текущий operating profile

Production-quality Lite Pangolin runs используют:

- GPT 5.5 High через OmniRoute для лучших публичных результатов,
- `-p 10` для полных GPT 5.5 ECOM runs,
- `-p 5` и `NATIVE_PANGOLIN_MAX_ITERATIONS=36` для DeepSeek V4 Flash
  экспериментов,
- `NATIVE_PREFLIGHT_CONTEXT=0`, потому что preflight давал спорный speed gain и
  увеличивал missed-reference failures,
- `PANGOLIN_SCRATCHPAD_MODE=v2` для компактной памяти.

## 9) Что здесь значит overfit

`operation-overfit` — это reference point, а не архитектура агента. Он показывает,
что можно получить, подгоняя rules/code под известные benchmark patterns. Lite
Pangolin оценивается как общий task-solving loop, который читает окружение и
grounding refs в runtime.
