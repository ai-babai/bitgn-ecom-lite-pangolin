# BitGN Sample Reference

The local mirror of BitGN public examples is here:

```text
/srv/aika-os/bitgn/code/bitgn-sample-agents
```

Relevant examples:

- Sandbox: `bitgn-sample-agents/sandbox-py/`
- PAC1: `bitgn-sample-agents/pac1-py/`
- ECOM1: `bitgn-sample-agents/ecom-py/`

The sample agents use a small loop with runtime tools and a short prompt. The useful baseline pattern is:

- be a pragmatic task assistant for the current benchmark runtime;
- keep edits small and targeted;
- use runtime tools for evidence and actions;
- finish with a completion/report action when done or blocked;
- rely on benchmark-provided runtime policy/docs for task-specific rules.

This project intentionally keeps only that minimal pattern and avoids importing the richer logic from our mature PAC1/ECOM stack.
