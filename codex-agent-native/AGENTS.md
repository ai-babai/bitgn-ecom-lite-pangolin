# AGENTS.md - codex-agent-native

This directory contains the copied native runner for ECOM small-agent experiments. Keep the model-visible surface simple.

- Backbones: Codex CLI, Pi native wrappers, and Pangolin loop for the weak-model path.
- Keep exactly one model-visible Pangolin tool: `execute_code`.
- Generic helper facades, ref ledgers, and finalization gates are allowed when toggleable.
- Avoid workbook, analytics, rule evolution, task-specific validators, and hardcoded answers.
- `tool_gateway.py` should stay a thin BitGN VM facade; put small-agent safety helpers around it, not inside benchmark-specific shortcuts.
- `local-rules/AGENTS.md` is the only stable instruction file. Keep it general and compact.
- Do not commit `runs/`, `.venv/`, or generated caches.
