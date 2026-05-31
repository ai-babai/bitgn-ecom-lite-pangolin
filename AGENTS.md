# AGENTS.md - bitgn-ecom-lite-pangolin

Purpose: BitGN ECOM small-agent native testbed.

This repo is a copy of the native-agent baseline made for experiments with
weaker/cheaper models such as `openai/gpt-5.4-nano` and
`openai/gpt-5.4-mini`. The goal is to make those models pass the agent
contract reliably without contaminating the preserved baseline project.

## Rules

- Main experiment path is Pangolin loop with exactly one model-visible tool: `execute_code`. Codex CLI and Pi wrappers remain copied for comparison.
- Prefer generic weak-model gates and helpers over task-specific validators, hardcoded answers, or benchmark-specific shortcuts.
- Keep ECOM task policy general. Put architecture and implementation ideas in `SMALL_AGENT_ARCHITECTURE.md`, not in long benchmark prompts.
- Weak-model changes should be toggleable by env vars so GPT 5.5 behavior can still be compared against the copied baseline.
- Run artifacts stay under `codex-agent-native/runs/` and must not be committed.
- Default Codex model target is `codex/gpt-5.5-high`, overrideable with `CODEX_MODEL`; default Pi model target is `omniroute/codex/gpt-5.5-high`, overrideable with `PI_MODEL`.

## Orientation

- Project map: `PROJECT_MAP.md`
- Usage/runbook: `USAGE.md`
- Small-agent architecture/TODO: `SMALL_AGENT_ARCHITECTURE.md`
- BitGN sample reference: `BITGN_SAMPLE_REFERENCE.md`
- Root BitGN workspace: `/srv/aika-os/bitgn`
- Preserved source baseline: `/srv/aika-os/bitgn/code/bitgn-cli-agent-native-test`
- Mature runner stack: `/srv/aika-os/bitgn/code/bitgn-pac1-env`

## Entry Points

- Runner wrappers: `./run-codex-native.sh`, `./run-pi-native.sh`
- Native code: `codex-agent-native/`
- Minimal instructions: `codex-agent-native/local-rules/AGENTS.md`

## Common Smoke

```bash
./run-codex-native.sh --env ecom --no-leaderboard t01
BITGN_API_KEY='' BITGN_API_KEY_FILE=/tmp/bitgn-no-key ./run-codex-native.sh --env pac1 t01
./run-pi-native.sh --env ecom --no-leaderboard t01
BITGN_API_KEY='' BITGN_API_KEY_FILE=/tmp/bitgn-no-key ./run-pi-native.sh --env pac1 --no-leaderboard t01
```
