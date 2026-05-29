# PAC1 Runtime Notes

- Read runtime-root `AGENTS.MD` and any process docs before changing files.
- Use PAC1 paths as runtime-relative paths without a leading `/` unless runtime docs show otherwise.
- Completion shape is `report_completion message=... outcome=... grounding_refs=...`.
- Use a valid outcome enum: `OUTCOME_OK`, `OUTCOME_DENIED_SECURITY`, `OUTCOME_NONE_CLARIFICATION`, `OUTCOME_NONE_UNSUPPORTED`, or `OUTCOME_ERR_INTERNAL`.
