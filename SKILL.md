---
name: loki-logs
description: Query logs from a Grafana Loki server — run LogQL queries over a time range, discover
  label names/values, and list streams. Use when the user asks about logs, errors, or traffic in
  a Loki-backed environment.
allowed-tools: Bash(python ${CLAUDE_SKILL_DIR}/scripts/loki.py *), Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/loki.py *), Bash(py ${CLAUDE_SKILL_DIR}/scripts/loki.py *)
---

# Loki Logs

Query a Grafana Loki server directly from the command line: run LogQL queries over a time range,
discover which labels and label values exist, and list streams — without leaving the session.

## When to use this skill

The user asks about logs, errors, or traffic in an environment backed by Grafana Loki: "what's
failing in prod", "show me errors from the last hour", "what services are logging right now",
diagnosing an incident, or exploring what log streams/labels exist before writing a query.

## Running the script

```
python3 ${CLAUDE_SKILL_DIR}/scripts/loki.py <command> [options]
```

Try `python3` first (macOS, Linux, most Windows setups). If it's not on `PATH`, fall back to
`python` or `py` — same script, same arguments.

## Configuration

The Loki base URL is resolved in this order:

1. `--url http://host:3100` (or `--endpoint <name>` to pick a named endpoint from the config file)
2. `LOKI_URL` (or `LOKI_ENDPOINT`) environment variable
3. `~/.config/.loki/loki.json`:
   ```json
   { "default": "prod",
     "endpoints": { "prod": { "url": "http://loki.lan:3100" } } }
   ```

If none of these resolve, the script exits with code `2` and prints a hint listing all three ways
to set the URL — don't guess a URL yourself, just run the command and read the hint.

## Commands

| Command | Purpose | Example |
|---|---|---|
| `query` | Run a LogQL query over a time range | `python3 ${CLAUDE_SKILL_DIR}/scripts/loki.py query '{app="api"} \|= "error"' --since 1h --limit 50` |
| `labels` | List label names | `python3 ${CLAUDE_SKILL_DIR}/scripts/loki.py labels --since 1h` |
| `label-values` | List values for one label | `python3 ${CLAUDE_SKILL_DIR}/scripts/loki.py label-values app --since 1h` |
| `series` | List streams matching a selector | `python3 ${CLAUDE_SKILL_DIR}/scripts/loki.py series '{app=~".+"}' --since 1h` |

Time range: `--since 30m|2h|7d` (default `1h`), or `--start`/`--end` together (ISO-8601, `-2h`,
`now`, or unix s/ms/ns). `--since` and `--start`/`--end` are mutually exclusive.

## Workflow

Don't guess a LogQL selector. Narrow down first:

1. `labels` — see what label names exist.
2. `label-values <name>` — see what values a label like `app` or `env` takes.
3. `query '{label="value"} |= "text"'` — run the actual query, narrowed by label and filter.

If a query returns nothing, widen `--since` or loosen the selector before assuming there are no
matching logs.

## Context-budget rules

- Start with a small `--limit` (e.g. `--limit 50`); raise it only if you need more.
- Use `--output ndjson` when you need to grep/filter through results yourself.
- Use `--fields level,message` (or similar) to project down to just the JSON fields you need.
- Never dump thousands of raw log lines into your response — summarize what matters.

## Common errors

- **Connection refused / timeout (exit `3`)** — wrong URL or the Loki host is unreachable. Check
  the resolved URL and ask the user to confirm it.
- **HTTP 400 (exit `4`)** — malformed LogQL. Loki's error message is printed to stderr; see
  `references/logql.md` for query syntax before retrying.
- **Empty result (exit `0`, no lines)** — the time window is too narrow or the label/selector
  doesn't match anything. Widen `--since` or re-check with `labels`/`label-values`.

For anything beyond a simple selector — filters (`|=`, `!=`, `|~`), `| json`, `| logfmt`, label
filters on parsed fields — read `references/logql.md`.
