# Evals

`claude plugin eval` runs a prompt against this plugin in an isolated session and grades the
transcript. Each case is a directory under `evals/` with a `prompt.md` (the task, plus frontmatter
like `max_turns` and `allowed_tools`) and one or more `graders/*.md` files (e.g. `type: llm` with a
`weight` and a markdown body describing what a passing response looks like).

Run the suite:

```
claude plugin eval . --case "*" --allow-tools Bash
```

This calls the real Claude API (needs `ANTHROPIC_API_KEY`) and, for `loki-query-last-hour`, expects
a Loki server at `http://localhost:3100` — without one, the case still passes as long as the agent
runs `scripts/loki.py` correctly and surfaces the connection failure instead of inventing log
output (see `graders/criteria.md`).

## Cases

- `loki-query-last-hour` — checks that "show me error-level logs from Loki in the last hour"
  results in the agent invoking `scripts/loki.py query` with an error-filtered LogQL selector and
  `--since 1h` (or equivalent), rather than guessing or fabricating output.
