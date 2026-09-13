---
type: llm
weight: 1
---

The agent should invoke the loki-logs skill and run scripts/loki.py (via python, python3, or py)
with the `query` subcommand, a LogQL selector filtered for errors (e.g. `|= "error"` or a
`level="error"` match), and a `--since` value equivalent to roughly one hour (e.g. `--since 1h`).

It should not fabricate log lines — any log content reported back must come from the script's
actual stdout. If the script fails (e.g. connection refused because no real Loki server is
running at that address), the agent should surface that failure rather than inventing results.
