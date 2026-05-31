# Lite Pangolin Loop для BitGN ECOM

Компактный BitGN ECOM runner вокруг Pangolin-style цикла: один видимый модели
инструмент, Python-исполнение внутри task VM, persistent scratchpad, строгая
гигиена финального submit и полные артефакты прогонов для анализа.

[English version](./README.md) | Русская версия

## ECOM leaderboard

- Страница челленджа: https://bitgn.com/challenge/ECOM
- Lite Pangolin занял **10 место на accuracy leaderboard** в окне соревнования.
- Overfit-run ниже не является результатом универсального агента. Это полезный
  ориентир: сколько можно получить, переобучившись под известные правила и
  паттерны benchmark.

| Track | Run | Benchmark | Score | Time | Комментарий |
| --- | --- | --- | ---: | ---: | --- |
| Lite Pangolin | `[@skifmax]-[lite-pangolin]-[gpt55]-[kotiki-enotiki]-[x002]` | `bitgn/ecom1-prod` | `73.7 / 100` | `2:02:10` | Лучший публичный Lite Pangolin run, OpenAI GPT 5.5 High через OmniRoute. |
| Lite Pangolin | `[@skifmax]-[lite-pangolin]-[gpt55]-[kotiki-enotiki]-[x001]` | `bitgn/ecom1-prod` | `73.3 / 100` | `2:13:59` | Более ранний GPT 5.5 High prod run. |
| Lite Pangolin | `[@skifmax]-[lite-pangolin]-[deepseek-v4-flash]-[kotiki-enotiki]-[x001]` | `bitgn/ecom1-prod` | `50.1 / 100` | `3:55:51` | DeepSeek V4 Flash через OpenRouter. |
| Operation Overfit | `[@skifmax]-[operation-overfit]-[only-code]-[distil-from-llm-runs]-[x005]` | `bitgn/ecom1-prod` | `23.9 / 100` | `2:23` | Только rules-overfit ориентир, не универсальный reasoning agent. |

## Быстрые ссылки

- Архитектура: [`ARCHITECTURE.ru.md`](./ARCHITECTURE.ru.md)
- English architecture: [`ARCHITECTURE.md`](./ARCHITECTURE.md)
- Runbook: [`USAGE.md`](./USAGE.md)
- Детали native runner: [`codex-agent-native/README.ru.md`](./codex-agent-native/README.ru.md)
- Карта проекта: [`PROJECT_MAP.md`](./PROJECT_MAP.md)
- Минимальная task-инструкция: [`BENCHMARK_AGENT.md`](./BENCHMARK_AGENT.md)
- Локальные правила: [`codex-agent-native/local-rules/AGENTS.md`](./codex-agent-native/local-rules/AGENTS.md)
- Заметки по small-model агенту: [`SMALL_AGENT_ARCHITECTURE.md`](./SMALL_AGENT_ARCHITECTURE.md)

## Как это работает, кратко

Рабочая форма намеренно маленькая:

```text
task instruction
  -> local ECOM rules
  -> Pangolin loop
  -> один видимый инструмент: execute_code
  -> Python helper layer вызывает BitGN VM tools
  -> finish(...)/ws.answer(...) отправляет ответ
```

Модель отвечает за рассуждение. Runtime берет на себя контрактную механику:
tool dispatch, observed refs, compact scratchpad, finalization checks, task
artifacts и backfill score после закрытия run.

## Основные компоненты

- `run-pangolin-native.sh`: основной wrapper для Pangolin runs на ECOM/PAC/sandbox.
- `codex-agent-native/runner.py`: orchestration задач, lazy `StartTrial`, model
  loop, scoring и manifest.
- `codex-agent-native/pi_exec_tool.py`: Python execution environment, доступный
  модели как один инструмент.
- `codex-agent-native/tool_gateway.py`: тонкий adapter к BitGN VM API.
- `codex-agent-native/scratchpad.py`: compact scratchpad profile между итерациями.
- `codex-agent-native/local-rules/`: локальные benchmark-инструкции для task sessions.

## Рекомендуемые запуски

### ECOM dev, GPT 5.5 High через OmniRoute

```bash
cd /srv/aika-os/bitgn/code/bitgn-ecom-lite-pangolin

NATIVE_PANGOLIN_MODEL='codex/gpt-5.5-high' \
LOCAL_RUN_ID='lite-pangolin-gpt55-ecom-dev-YYYYMMDD' \
./run-pangolin-native.sh --env ecom --no-leaderboard --all -p 10
```

### ECOM prod leaderboard, GPT 5.5 High через OmniRoute

```bash
NATIVE_PANGOLIN_MODEL='codex/gpt-5.5-high' \
BITGN_RUN_NAME='[@skifmax]-[lite-pangolin]-[gpt55]-[kotiki-enotiki]-[xNNN]' \
LOCAL_RUN_ID='skifmax-lite-pangolin-gpt55-kotiki-enotiki-xNNN-ecom-prod-YYYYMMDD' \
BENCHMARK_ID='bitgn/ecom1-prod' AGENT_ENV='ecom' \
./run-pangolin-native.sh --env ecom --leaderboard --all -p 10
```

### ECOM dev, DeepSeek V4 Flash через OpenRouter

```bash
NATIVE_PANGOLIN_API_KEY="$(tr -d '\r\n' < "$HOME/.codex/openrouter-api-key")" \
NATIVE_PANGOLIN_BASE_URL='https://openrouter.ai/api/v1' \
NATIVE_PANGOLIN_MODEL='deepseek/deepseek-v4-flash' \
NATIVE_PANGOLIN_REASONING_ENABLED='0' \
NATIVE_PANGOLIN_MAX_ITERATIONS='36' \
LOCAL_RUN_ID='deepseek-v4-flash-ecom-dev-YYYYMMDD-iter36' \
./run-pangolin-native.sh --env ecom --no-leaderboard --all -p 5
```

## Текущие defaults

| Setting | Default | Зачем |
| --- | --- | --- |
| `AGENT_BACKBONE` | `pangolin_loop` в `run-pangolin-native.sh` | Single-tool execute-code loop. |
| `PANGOLIN_SCRATCHPAD` | `1` | Компактная память задачи между итерациями. |
| `PANGOLIN_SCRATCHPAD_MODE` | `v2` | Не тащит большие raw outputs обратно в модель. |
| `NATIVE_PREFLIGHT_CONTEXT` | `0` | Выключен: ускорение спорное, refs регрессировали. |
| `NATIVE_EXEC_FINISH_HELPER` | `1` | Дает `finish(...)` внутри Python. |
| `NATIVE_EXEC_RUN_HELPER` | `1` | Дает удобный helper `run(...)`. |
| `NATIVE_SESSION_TIMEOUT_SEC` | `1440` | Timeout на задачу. |
| `NATIVE_PANGOLIN_MAX_ITERATIONS` | `20` | Для слабых моделей, например DeepSeek V4 Flash, можно поднять до `36`. |

## Артефакты

Run artifacts остаются локальными и игнорируются git:

```text
codex-agent-native/runs/<local_run_id>/
  run_manifest.jsonl
  tNN/attempt_<timestamp>_<id>/
    events.jsonl
    tool_calls.jsonl
    submission.json
    score.json
    session/pangolin_events.jsonl
    session/pangolin_scratchpad.json
```

По ним сравниваются wall time, summed task time, score details, token usage,
failed refs и agent-level errors.

## Позиция по дизайну

- Оставлять модели ровно один видимый инструмент: `execute_code`.
- Предпочитать generic runtime gates и helper APIs вместо task-specific validators.
- Держать preflight, scratchpad и weak-model guards включаемыми флагами.
- Считать overfit-эксперименты ориентирами, а не production-shape агента.
- Полные traces хранить локально; `codex-agent-native/runs/` не коммитить.

## Контакты

- Maksim Popkov
- Telegram: `@skifmax`
- Email: `contact.popkov@yandex.com`
- Сайты: https://mipopkov.com, https://mipopkov.ru
