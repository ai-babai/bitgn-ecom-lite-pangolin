# codex-agent-native

Minimal one-session-per-task runner for BitGN.

Flow:

1. Start BitGN playground/trial.
2. Create task workspace.
3. Launch the selected CLI backbone (`codex exec` or `pi --print`) with the task instruction and minimal local rules.
4. Agent calls tools through `python runtime_tools.py <tool> ...`.
5. Agent calls `report_completion` exactly once.
6. Runner ends trial and stores artifacts.

No custom validators or task-specific repairs are active in this project.
