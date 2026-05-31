# codex-agent-native

Native BitGN task runner для Lite Pangolin setup.

[English version](./README.md) | Русская версия

## Роль в репозитории

Модуль запускает изолированные benchmark task attempts и сохраняет все
артефакты, нужные для последующего анализа. Самый сильный текущий путь —
`pangolin_loop`: модель видит один инструмент `execute_code`, а работу с VM
делает через Python helpers.

## Основной flow

1. Резолв benchmark tasks и подготовка run.
2. Lazy start trial, когда worker реально начинает задачу.
3. Создание изолированного attempt workspace.
4. Snapshot local rules и benchmark context.
5. Запуск выбранного backbone: Pangolin, Codex CLI или Pi.
6. Submit через `finish(...)`, `ws.answer(...)` или `report_completion`.
7. `EndTrial`, запись `score.json`, append в `run_manifest.jsonl`.
8. `SubmitRun` и backfill run-level scores, если benchmark их раскрывает.

## Важные файлы

- `runner.py`: orchestration, parallelism, trial lifecycle, scoring, manifests.
- `pi_exec_tool.py`: Python execution environment для Pangolin/Pi `exec`.
- `tool_gateway.py`: BitGN VM API adapter для ECOM, PAC и sandbox tools.
- `scratchpad.py`: compact scratchpad profiles и compaction helpers.
- `local-rules/`: local task instructions, копируемые в каждую попытку.

## Layout артефактов

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

`runs/` намеренно игнорируется git.
