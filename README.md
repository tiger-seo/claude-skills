# loki-logs

A Claude Code skill/plugin that queries [Grafana Loki](https://grafana.com/oss/loki/) logs from
the command line — a self-contained, stdlib-only Python CLI plus a `SKILL.md` that teaches Claude
how to use it.

## Install

**Option 1 — plugin, via Claude Code (recommended):**

```
/plugin marketplace add tiger-seo/loki-logs
/plugin install loki-logs@tiger-seo-skills
```

or non-interactively:

```
claude plugin marketplace add tiger-seo/loki-logs
claude plugin install loki-logs@tiger-seo-skills
```

Add `--scope user|project|local` to control where it's installed. After installing, you may need
to run `/reload-plugins`. The skill is invoked as `/loki-logs:loki-logs`.

**Option 2 — personal skill via clone + symlink** (for development):

```
git clone https://github.com/tiger-seo/loki-logs.git
```

Windows:
```
cmd /c mklink /J "%USERPROFILE%\.claude\skills\loki-logs" "D:\path\to\loki-logs"
```

macOS/Linux:
```
ln -s /path/to/loki-logs ~/.claude/skills/loki-logs
```

Invoked simply as `/loki-logs`.

**Option 3 — project skill:** clone or submodule this repo into `<your-repo>/.claude/skills/loki-logs`.

## Configuration

The Loki base URL is resolved in this order:

1. `--url http://host:3100` or `--endpoint <name>`
2. `LOKI_URL` or `LOKI_ENDPOINT` environment variable
3. `~/.config/.loki/loki.json`:
   ```json
   { "default": "prod",
     "endpoints": { "prod": { "url": "http://loki.lan:3100" } } }
   ```

## Usage

```
python3 scripts/loki.py query '{app="api"} |= "error"' --since 1h --limit 50
python3 scripts/loki.py labels
python3 scripts/loki.py label-values app
python3 scripts/loki.py series '{app=~".+"}'
```

Output formats: `--output text|ndjson|json|raw`, plus `--fields level,message` to project down to
specific JSON fields and `--no-parse-json` to skip JSON parsing of log lines. See
[`SKILL.md`](SKILL.md) for the full command reference and [`references/logql.md`](references/logql.md)
for LogQL query syntax.

## Development

Run the unit tests (no network required):

```
python -m unittest discover -s tests -v
```

Run the best-effort `claude plugin eval` suite for `SKILL.md` (requires an `ANTHROPIC_API_KEY` and
calls the real API — see [`evals/README.md`](evals/README.md)):

```
claude plugin eval . --case "*" --allow-tools Bash
```

## License

MIT — see [LICENSE](LICENSE).
