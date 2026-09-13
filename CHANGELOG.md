# Changelog

## 0.1.0 — Unreleased

- Initial release: `scripts/loki.py` CLI with `query`, `labels`, `label-values`, and `series`
  commands against the Grafana Loki HTTP API, stdlib-only.
- `SKILL.md` for Claude Code, plus a `references/logql.md` cheat sheet.
- Self-hosted plugin marketplace (`.claude-plugin/`) for one-command install from GitHub.
- `tests/test_loki.py` unit tests and a GitHub Actions CI workflow.
- Best-effort `evals/loki-query-last-hour` case for `claude plugin eval`.
