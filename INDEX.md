# INDEX - bitgn-ecom-lite-pangolin

Separate BitGN ECOM native-agent testbed for weak/small model experiments.

## Shape

- `AGENTS.md` - project rules for maintainers and future agents.
- `README.md` - short project overview.
- `USAGE.md` - run commands and environment defaults.
- `PROJECT_MAP.md` - where this repo sits in the BitGN workspace.
- `SMALL_AGENT_ARCHITECTURE.md` - weak-model problem signal, target shape, and TODO.
- `BENCHMARK_AGENT.md` - human-readable copy of the minimal benchmark agent instruction.
- `BITGN_SAMPLE_REFERENCE.md` - local reference to BitGN public sample agents.
- `run-codex-native.sh` - thin Codex CLI benchmark wrapper.
- `run-pi-native.sh` - thin Pi / p-agent benchmark wrapper.
- `scripts/load-omniroute-key.sh` - local OmniRoute key loader.
- `codex-agent-native/runner.py` - task orchestration and CLI-agent session launch.
- `codex-agent-native/runtime_tools.py` - command-line bridge used by the agent.
- `codex-agent-native/tool_gateway.py` - direct BitGN VM tool facade.
- `codex-agent-native/local-rules/AGENTS.md` - minimal common task instructions.
- `codex-agent-native/local-rules/AGENTS.pac1.md` / `AGENTS.ecom.md` - small environment-specific runtime notes.

## Supported Envs

- `--env sandbox` -> `bitgn/sandbox`
- `--env pac1` -> `bitgn/pac1-dev`
- `--env pac1-prod` -> `bitgn/pac1-prod`
- `--env ecom` -> `bitgn/ecom1-dev`

This project intentionally keeps one model-visible tool for Pangolin-style weak-model experiments. Generic helper facades, ref ledgers, and finalization gates belong here; task-specific hardcoded validators do not.
