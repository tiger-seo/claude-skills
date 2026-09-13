# LogQL cheat sheet

A LogQL query starts with a **stream selector**, optionally followed by one or more **filters** and
**pipeline stages**.

## Stream selector

Selects streams by label match, same syntax as PromQL:

```
{app="api"}                  # exact match
{app="api", env="prod"}      # multiple labels, AND-ed
{app=~"api.*"}               # regex match
{app!="api"}                 # negative match
{app!~"api.*"}               # negative regex match
{app=~".+"}                  # matches every stream that has an `app` label
```

Use `labels` and `label-values <name>` first to discover what's actually available — don't guess
label names or values.

## Line filters

Applied after the selector, filter on the raw log line:

```
{app="api"} |= "error"       # line contains "error"
{app="api"} != "healthcheck" # line does not contain "healthcheck"
{app="api"} |~ "err(or)?"    # line matches regex
{app="api"} !~ "debug"       # line does not match regex
```

Filters can be chained: `{app="api"} |= "error" != "timeout"`.

## Parsing pipeline stages

Parse structured log lines into fields you can filter or format on:

```
{app="api"} | json                       # parse the line as JSON
{app="api"} | json level, msg="message"  # extract only these fields (with renaming)
{app="api"} | logfmt                     # parse key=value logfmt lines
```

## Label filters (after parsing)

Once fields are parsed, filter on them like labels:

```
{app="api"} | json | level="error"
{app="api"} | json | status_code >= 500
{app="api"} | logfmt | duration > 1s
```

## Putting it together

```
{app="api", env="prod"} |= "error" | json | level="error"
```

Selector narrows to streams → line filter narrows to lines containing "error" → `json` parses the
line → label filter keeps only lines where the parsed `level` field is `"error"`.

## Common mistakes

- Missing braces: `app="api"` → must be `{app="api"}`.
- Comparing an unparsed field: `{app="api"} | status_code >= 500` without a preceding `| json` or
  `| logfmt` — there's nothing to filter on yet.
- Loki returns HTTP 400 for a syntactically invalid query; the error text in stderr usually names
  the exact problem (unexpected token, unterminated string, etc).
