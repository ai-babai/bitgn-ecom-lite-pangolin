# Project Map

## This Project

```text
/srv/aika-os/bitgn/code/bitgn-ecom-lite-pangolin
```

Purpose: separate ECOM small-agent testbed for weak/cheap model gates, helper facades, ref ledgers, and finalization watchdogs.

Source baseline: `/srv/aika-os/bitgn/code/bitgn-cli-agent-native-test`

## BitGN Tree Around It

```text
/srv/aika-os/bitgn/
  AGENTS.md
  INDEX.md
  code/
    bitgn-ecom-lite-pangolin/         current Lite Pangolin ECOM project
    bitgn-cli-agent-native-test/      preserved native baseline source
    bitgn-pac1-env/                   mature PAC1/ECOM runner with Codex and Pangolin backbones
    bitgn-ecom1-env/                  ECOM1 workspace adapted from the main runner
    bitgn-ecom-localbench-env/        smaller/local ECOM benchmark workspace
    bitgn-ecom-run/                   clean-room ECOM Run architecture project
    bitgn-sample-agents/              upstream BitGN sample agents mirror
    operation-pangolin/               Pangolin reference/adaptation
  notes/
    pac1/
    ecom1/
    ecom-localbench/
    bitgn-ecom-run/
    RUNS.md
    ACTIVE_PROFILES.md
```

## How To Orient

- Start broad BitGN context from `/srv/aika-os/bitgn/AGENTS.md` and `/srv/aika-os/bitgn/INDEX.md`.
- Treat this repo as the place for small-agent architecture experiments, not the preserved baseline.
- Use `bitgn-pac1-env` for the mature production experiment stack.
- Use `bitgn-sample-agents` only as a reference for public BitGN SDK/sample flow.
- Keep run artifacts inside this repo's `codex-agent-native/runs/` and do not commit them.
