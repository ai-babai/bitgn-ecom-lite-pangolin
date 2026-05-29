# Minimal BitGN Agent Instructions

This is the human-readable copy of the common instruction injected into benchmark agent sessions.
The active runtime common copy is `codex-agent-native/local-rules/AGENTS.md`.
PAC1 and ECOM add the small environment notes from `AGENTS.pac1.md` and `AGENTS.ecom.md`.

- Solve only the current BitGN task.
- Use only the runner-exposed tool interface. In Pi exec mode, call the single `exec` tool and use Python helper `call_tool(...)` from inside that code to reach BitGN runtime tools.
- Inspect benchmark-provided runtime files and docs before acting; do not guess facts, paths, IDs, policy, or required changes.
- Keep writes and deletes minimal and task-scoped.
- If benchmark-provided policy/docs require denial, clarification, or unsupported status, use the matching completion outcome.
- Cite only runtime evidence that supports the final answer or action.
- When done, call `report_completion` exactly once and stop.
