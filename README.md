# claude-skills

Personal collection of [Claude Code](https://claude.com/claude-code) skills/plugins, published as a
single self-hosted marketplace (`tiger-seo-skills`) so any of them installs in one step.

## Install a skill

```
/plugin marketplace add tiger-seo/claude-skills
/plugin install <skill-name>@tiger-seo-skills
```

or non-interactively:

```
claude plugin marketplace add tiger-seo/claude-skills
claude plugin install <skill-name>@tiger-seo-skills
```

See each skill's own README for skill-specific usage, configuration, and alternative install
methods (clone + symlink, project-local install).

## Skills

| Skill | Description |
|---|---|
| [`loki-logs`](loki-logs/) | Query Grafana Loki logs — LogQL over a time range, label discovery, stream listing. |

## Repository layout

Each skill lives in its own top-level folder and is a self-contained Claude Code plugin
(`<skill>/.claude-plugin/plugin.json`, `<skill>/SKILL.md`, its own tests/docs). The root
`.claude-plugin/marketplace.json` lists all of them, each pointing at its own subfolder via
`source`.

## License

MIT — see [LICENSE](LICENSE). Individual skills may note their own license in their `plugin.json`
if it ever differs.
