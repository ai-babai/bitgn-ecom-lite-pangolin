# Minimal BitGN Agent Instructions

- Solve only the current BitGN task.
- Use only the runner-exposed tool interface. In Pi exec mode, call the single `exec` tool and use Python helper `call_tool(...)` from inside that code to reach BitGN runtime tools.
- In Pi exec mode, assign exploratory output to `result = ...` or `print(...)`; discarded `call_tool(...)` return values may be invisible on the next turn.
- If `finish(...)` is available, use it for final submission after evidence is verified; after a successful finish/report call, stop.
- Never end with normal assistant text after exploration. Every task must end by calling `finish(...)`, `ws.answer(...)`, or `report_completion`.
- If you write that you will search, read, list, count, or verify, make the `exec` tool call in that same response; do not stop after a plan.
- Inspect benchmark-provided runtime files and docs before acting; do not guess facts, paths, IDs, policy, or required changes.
- Keep writes and deletes minimal and task-scoped.
- If benchmark-provided policy/docs require denial, clarification, or unsupported status, use the matching completion outcome.
- Cite only runtime evidence that supports the final answer or action.
- When done, call `report_completion` exactly once and stop.
