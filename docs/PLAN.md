# Plan: Claude Code Skill "loki-logs" (Python client for Grafana Loki)

**Date**: 2026-09-04
**Claude Code session**: `session_01SFjhS47swtM9dE4KysBbMf`
**Link**: https://claude.ai/code/session_01SFjhS47swtM9dE4KysBbMf

## Context

The LogPilot VS Code extension already knows how to talk to Loki (`src/loki/client.ts`, `parser.ts`), but that
logic is locked inside the extension host and unavailable to the agent. We need a separate **skill for Claude
Code** so Claude can fetch logs from Loki itself while debugging: run a LogQL query, see which labels/streams
exist, and narrow the search.

The skill is a self-contained Python CLI (stdlib-only, no pip dependencies) plus a `SKILL.md` that explains to
the agent which commands to call and how to read the output. The parsing semantics mirror the extension
(level/message/nanosecond timestamps) so both surfaces display logs the same way.

**Decisions agreed with the user:** a separate project at `D:\projects-claude\loki-logs`; configuration from
CLI flags, env vars, and `~/.config/.loki/loki.json`; commands `query`, `labels`, `label-values`, `series`;
no authentication (plain HTTP); repo ready to push to GitHub and install in one step.

## Repository structure (created from scratch)

Repo root = skill root. The docs allow a single `SKILL.md` at the plugin root — that way **the same layout**
serves both installation paths (plugin from GitHub and a symlink under `~/.claude/skills`).

```
D:\projects-claude\loki-logs\
├── .claude-plugin/
│   ├── plugin.json          # plugin manifest (name, version, description, author, license, repository)
│   └── marketplace.json     # single-plugin marketplace: source "./" — so it installs straight from the repo
├── SKILL.md                 # main artifact: instructions for the agent
├── scripts/loki.py          # the whole CLI in one file, stdlib only
├── references/logql.md      # LogQL cheat sheet — read by the agent as needed
├── tests/test_loki.py       # unittest, no network
├── .github/workflows/ci.yml # tests on ubuntu + windows
├── README.md                # install instructions + examples for humans
├── CHANGELOG.md
├── LICENSE                  # MIT
├── .gitignore
└── docs/PLAN.md             # this plan
```

### Meta-files for installing from GitHub

`.claude-plugin/plugin.json`:

```json
{
  "name": "loki-logs",
  "displayName": "Loki Logs",
  "version": "0.1.0",
  "description": "Query Grafana Loki logs from Claude Code via a stdlib-only Python client.",
  "author": { "name": "tiger-seo", "url": "https://github.com/tiger-seo" },
  "repository": "https://github.com/tiger-seo/loki-logs",
  "license": "MIT",
  "keywords": ["loki", "logs", "logql", "grafana", "observability"]
}
```

`.claude-plugin/marketplace.json` (the same repo also works as a marketplace):

```json
{
  "name": "tiger-seo-skills",
  "owner": { "name": "tiger-seo", "url": "https://github.com/tiger-seo" },
  "plugins": [
    { "name": "loki-logs", "source": "./",
      "description": "Query Grafana Loki logs — LogQL over a time range, label discovery, stream listing." }
  ]
}
```

The marketplace is **self-hosted, in this same repository**. No submission to Anthropic's official or
community catalog: registration happens with a single `claude` command that points straight at the GitHub repo.

Three installation methods, all documented in `README.md`:

1. **Via the Claude command (recommended, cross-platform)** — in a session:
   ```
   /plugin marketplace add tiger-seo/loki-logs
   /plugin install loki-logs@tiger-seo-skills
   ```
   or from the terminal (non-interactive): `claude plugin marketplace add tiger-seo/loki-logs`
   and `claude plugin install loki-logs@tiger-seo-skills` (`--scope user|project|local`).
   The skill becomes available as `/loki-logs:loki-logs`; after install you may need `/reload-plugins`.
2. **Personal skill via clone + symlink** (for development; Claude Code follows the symlink):
   `git clone …` + `cmd /c mklink /J "%USERPROFILE%\.claude\skills\loki-logs" "D:\projects-claude\loki-logs"`
   (on macOS/Linux — `ln -s`). Invoked simply as `/loki-logs`.
3. **Project skill:** clone/submodule into `<repo>/.claude/skills/loki-logs`

## `SKILL.md` — contents

Frontmatter (`allowed-tools` with `${CLAUDE_SKILL_DIR}` — so the script runs without a permission prompt;
the same command line is duplicated in the body):

```yaml
---
name: loki-logs
description: Query logs from a Grafana Loki server — run LogQL queries over a time range, discover
  label names/values, and list streams. Use when the user asks about logs, errors, or traffic in
  a Loki-backed environment.
allowed-tools: Bash(python ${CLAUDE_SKILL_DIR}/scripts/loki.py *), Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/loki.py *), Bash(py ${CLAUDE_SKILL_DIR}/scripts/loki.py *)
---
```

Body (concise, action-oriented):

1. **When to activate** — questions about logs/errors in an environment, "what's in Loki", service diagnostics.
2. **Running it** — try `python3 ${CLAUDE_SKILL_DIR}/scripts/loki.py …` first (macOS, Linux, and most
   Windows setups), fall back to `python …` or `py …` if `python3` isn't on `PATH` (common on Windows);
   the `${CLAUDE_SKILL_DIR}` path works the same for plugin- and personal-install layouts.
3. **Configuration** — three URL sources, example `~/.config/.loki/loki.json`.
4. **Commands** — a table with copy-paste-ready examples:
   `python ${CLAUDE_SKILL_DIR}/scripts/loki.py query '{app="api"} |= "error"' --since 1h --limit 50`
5. **Workflow** — don't guess the selector: start with `labels` → `label-values app` → `query`;
   if empty — widen `--since` or loosen the selector.
6. **Context-budget rules** — start with `--limit 50`, use `--output ndjson` for analysis,
   don't dump thousands of lines into the response.
7. **Common errors** — connection refused (wrong URL / host unreachable), 400 (malformed LogQL →
   see `references/logql.md`), empty result (time window / nonexistent label).
8. Reference to `references/logql.md` (selectors, `|=`/`!=`/`|~` filters, `| json`, `| logfmt`,
   label filters) — read only when a non-trivial query needs to be built.

## `scripts/loki.py` — CLI design

Python 3.9+, stdlib only: `argparse`, `json`, `urllib.request`, `datetime`, `os`, `pathlib`.
8s timeout with a single automatic retry after 2s — matching `FETCH_TIMEOUT_MS`/`RETRY_DELAY_MS` in the
LogPilot extension's `src/loki/client.ts`. Retry triggers only on network-level failures (connection
refused, timeout, DNS error) — an HTTP 5xx response from Loki is returned as-is (exit code `4`, no retry).

`--since` is mutually exclusive with `--start`/`--end`: passing both is an argument error (exit code `2`).
`--start`/`--end` must be given together (either both or neither); with neither, `--since` (default `1h`)
applies.

### Configuration resolution (in descending priority)

1. `--url` / `--endpoint <name>`
2. `LOKI_URL` / `LOKI_ENDPOINT`
3. `~/.config/.loki/loki.json`:
   ```json
   { "default": "prod",
     "endpoints": { "prod": { "url": "http://loki.lan:3100" } } }
   ```
4. otherwise — an error with a hint on how to set the URL (all three ways, one line)

### Commands

| Command | Endpoint | Key flags |
|---|---|---|
| `query <logql>` | `GET /loki/api/v1/query_range` | `--since 1h` (default), `--start`, `--end`, `--limit 100`, `--direction backward` |
| `labels` | `GET /loki/api/v1/labels` | `--since`, `--query <selector>` |
| `label-values <name>` | `GET /loki/api/v1/label/{name}/values` | `--since`, `--query <selector>` |
| `series <selector>…` | `GET /loki/api/v1/series` (`match[]`) | `--since`, `--start`, `--end` |

Time: `--since 30m|2h|7d`; `--start`/`--end` accept ISO-8601 (`2026-09-04T10:00:00Z`), relative (`-2h`),
`now`, or unix s/ms/ns. Internally converted to nanosecond strings (Python ints have arbitrary precision,
so there's no BigInt-style issue like in JS).

### Output (to save the agent's context budget)

- `--output text` (default): `2026-09-04T12:00:01.123Z  ERROR  {app=api}  message`, long lines
  truncated via `--max-line-chars 400`
- `--output ndjson` — one JSON object per line (easy to grep)
- `--output json` — array of objects
- `--output raw` — raw log lines only
- `--fields a,b,c` — keep only the selected JSON fields (analogous to `webview/copy/fieldProjector.ts`)
- `--no-parse-json` — don't parse the line as JSON (analogous to `parseJson=false` in profiles)
- Summary (`N entries / M streams`) — on **stderr**, so it doesn't pollute stdout data

### Parsing (mirrors `src/loki/parser.ts`)

`parse_response()` — a pure function: flattens `data.result[].values[]` into a list of records
`{ts_ns, ts_iso, labels, raw, fields, level, message}`; level from `fields.level → severity → lvl → labels.level`;
message from `fields.message → msg`; sorted newest first; a malformed timestamp causes the record to be skipped.

### Exit codes

`0` success (including an empty response) · `2` argument/config error · `3` network/timeout ·
`4` Loki returned non-200 (Loki's error text goes to stderr, since that's where a meaningful 400 for
malformed LogQL belongs)

## Tests and CI

`tests/test_loki.py` using `unittest` (no network — a fake fetch is injected into the functions):
URL construction for all 4 commands, time parsing (ISO/relative/unix/ns), response flattening and sorting,
level/message extraction, output formatters, config priority (flag > env > file).

`.github/workflows/ci.yml`: matrix of `ubuntu-latest` + `windows-latest`, Python 3.9 and 3.13,
`python -m unittest discover -s tests -v`, plus a step verifying that `plugin.json` and `marketplace.json`
are valid JSON with the expected fields.

## Verification

1. `cd D:\projects-claude\loki-logs && python -m unittest discover -s tests -v` — all tests green.
2. Live smoke test against a server from the extension's defaults:
   - `python scripts/loki.py --url http://loki.lan:3100 labels`
   - `python scripts/loki.py --url http://loki.lan:3100 label-values app`
   - `python scripts/loki.py --url http://loki.lan:3100 query '{app=~".+"}' --since 1h --limit 5`
   - the same query with `--output ndjson` and with `--fields level,message`
3. Negative cases: nonexistent host → exit 3 with a human-readable error; `query '{'` → exit 4 with Loki's text.
4. Create `~/.config/.loki/loki.json`, run `python scripts/loki.py labels` without `--url` — works.
5. Local skill: junction at `~/.claude/skills/loki-logs`, in a new session ask "show me errors from Loki
   over the last hour" — the skill is picked up, `/skills` shows it, the script runs without a permission prompt.
6. Local marketplace check before pushing: `/plugin marketplace add D:/projects-claude/loki-logs`
   (adding from a local path) → `/plugin install loki-logs@tiger-seo-skills`.
7. After pushing to GitHub: in a clean session, `/plugin marketplace add tiger-seo/loki-logs` →
   `/plugin install loki-logs@tiger-seo-skills` → `/loki-logs:loki-logs` is available and works.

## Out of scope (deliberately)

Live-tail via WebSocket (needs an external dependency), authentication (bearer/basic/X-Scope-OrgID —
added as a single header when needed), `index/stats`, `volume`, `patterns`, reading profiles from
`.vscode/logpilot-profiles.json`.

Publishing to Anthropic's official (`claude-plugins-official`) or community (`claude-plugins-community`)
catalog is **not done** — the marketplace is self-hosted in this same repo, and that's enough for a
one-command install.
