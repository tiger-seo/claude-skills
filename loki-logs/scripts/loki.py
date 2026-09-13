#!/usr/bin/env python3
"""Query a Grafana Loki server from the command line — stdlib only, no dependencies."""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_TIMEOUT = 8.0
RETRY_DELAY = 2.0
DEFAULT_SINCE = "1h"
DEFAULT_LIMIT = 100
DEFAULT_MAX_LINE_CHARS = 400
CONFIG_PATH = Path.home() / ".config" / ".loki" / "loki.json"

DURATION_RE = re.compile(r"^(\d+)(ms|s|m|h|d|w)$")
LEVEL_FIELDS = ("level", "severity", "lvl")
MESSAGE_FIELDS = ("message", "msg")

UNIT_NS = {
    "ms": 1_000_000,
    "s": 1_000_000_000,
    "m": 60_000_000_000,
    "h": 3_600_000_000_000,
    "d": 86_400_000_000_000,
    "w": 604_800_000_000_000,
}


class LokiError(Exception):
    """Base error carrying the process exit code it should produce."""

    def __init__(self, message, exit_code):
        super().__init__(message)
        self.exit_code = exit_code


class ConfigError(LokiError):
    def __init__(self, message):
        super().__init__(message, 2)


class NetworkError(LokiError):
    def __init__(self, message):
        super().__init__(message, 3)


class ApiError(LokiError):
    def __init__(self, message, status=None):
        super().__init__(message, 4)
        self.status = status


# ---------------------------------------------------------------------------
# Configuration resolution
# ---------------------------------------------------------------------------

def load_config_file(path):
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"failed to read config file {path}: {exc}")


def _lookup_endpoint(cfg, name, config_path):
    if not cfg or name not in cfg.get("endpoints", {}):
        raise ConfigError(f"endpoint {name!r} not found in {config_path}")
    return cfg["endpoints"][name]["url"].rstrip("/")


def resolve_url(args, env=None, config=None, config_path=CONFIG_PATH):
    env = os.environ if env is None else env

    if getattr(args, "url", None):
        return args.url.rstrip("/")

    if getattr(args, "endpoint", None):
        cfg = config if config is not None else load_config_file(config_path)
        return _lookup_endpoint(cfg, args.endpoint, config_path)

    if env.get("LOKI_URL"):
        return env["LOKI_URL"].rstrip("/")

    if env.get("LOKI_ENDPOINT"):
        cfg = config if config is not None else load_config_file(config_path)
        return _lookup_endpoint(cfg, env["LOKI_ENDPOINT"], config_path)

    cfg = config if config is not None else load_config_file(config_path)
    default_name = (cfg or {}).get("default")
    if default_name:
        return _lookup_endpoint(cfg, default_name, config_path)

    raise ConfigError(
        "no Loki URL configured. Set one via --url http://host:3100, "
        "the LOKI_URL environment variable, or ~/.config/.loki/loki.json"
    )


# ---------------------------------------------------------------------------
# Time parsing
# ---------------------------------------------------------------------------

def now_ns():
    return time.time_ns()


def parse_duration_ns(text):
    match = DURATION_RE.match(text)
    if not match:
        raise ConfigError(f"invalid duration {text!r}; expected e.g. 30m, 2h, 7d")
    value, unit = match.groups()
    return int(value) * UNIT_NS[unit]


def parse_timestamp_ns(text, reference_ns):
    if text == "now":
        return reference_ns

    if text.startswith("-"):
        return reference_ns - parse_duration_ns(text[1:])

    if text.isdigit():
        n = int(text)
        if n < 10**11:
            return n * UNIT_NS["s"]
        if n < 10**14:
            return n * UNIT_NS["ms"]
        return n

    try:
        iso = text.replace("Z", "+00:00")
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1_000_000_000)
    except ValueError:
        raise ConfigError(
            f"invalid timestamp {text!r}; expected ISO-8601, -2h, now, or unix s/ms/ns"
        )


def resolve_time_range(args, reference_ns=None):
    reference_ns = now_ns() if reference_ns is None else reference_ns
    since = getattr(args, "since", None)
    start = getattr(args, "start", None)
    end = getattr(args, "end", None)

    if since and (start or end):
        raise ConfigError("--since cannot be combined with --start/--end")
    if bool(start) != bool(end):
        raise ConfigError("--start and --end must be given together")

    if start and end:
        return parse_timestamp_ns(start, reference_ns), parse_timestamp_ns(end, reference_ns)

    end_ns = reference_ns
    start_ns = end_ns - parse_duration_ns(since or DEFAULT_SINCE)
    return start_ns, end_ns


def ns_to_iso(ts_ns):
    seconds, nanos = divmod(ts_ns, 1_000_000_000)
    dt = datetime.fromtimestamp(seconds, tz=timezone.utc)
    millis = nanos // 1_000_000
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{millis:03d}Z"


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def http_get(url, params, timeout=DEFAULT_TIMEOUT, retry_delay=RETRY_DELAY):
    query = urllib.parse.urlencode(params, doseq=True)
    full_url = f"{url}?{query}" if query else url

    last_exc = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(full_url, timeout=timeout) as resp:
                return resp.status, resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, OSError) as exc:
            last_exc = exc
            if attempt == 0:
                time.sleep(retry_delay)
                continue
    raise NetworkError(f"failed to reach {url}: {last_exc}")


def raise_for_status(status, body, url):
    if status != 200:
        raise ApiError(f"Loki returned HTTP {status} for {url}: {body.strip()}", status=status)


def parse_json_body(body):
    if not body:
        return {}
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return {}


# ---------------------------------------------------------------------------
# Endpoint URL builders
# ---------------------------------------------------------------------------

def build_query_range_url(base_url, logql, start_ns, end_ns, limit, direction):
    params = {
        "query": logql,
        "start": str(start_ns),
        "end": str(end_ns),
        "limit": str(limit),
        "direction": direction,
    }
    return f"{base_url}/loki/api/v1/query_range", params


def build_labels_url(base_url, start_ns, end_ns, query=None):
    params = {"start": str(start_ns), "end": str(end_ns)}
    if query:
        params["query"] = query
    return f"{base_url}/loki/api/v1/labels", params


def build_label_values_url(base_url, name, start_ns, end_ns, query=None):
    params = {"start": str(start_ns), "end": str(end_ns)}
    if query:
        params["query"] = query
    path = urllib.parse.quote(name, safe="")
    return f"{base_url}/loki/api/v1/label/{path}/values", params


def build_series_url(base_url, selectors, start_ns, end_ns):
    params = {"match[]": list(selectors), "start": str(start_ns), "end": str(end_ns)}
    return f"{base_url}/loki/api/v1/series", params


# ---------------------------------------------------------------------------
# Response parsing (mirrors src/loki/parser.ts)
# ---------------------------------------------------------------------------

def pick_field(fields, names):
    for name in names:
        if name in fields and fields[name] is not None:
            return fields[name]
    return None


def extract_json_fields(raw, parse_json=True):
    if not parse_json:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def parse_response(data, parse_json=True):
    records = []
    result = ((data or {}).get("data") or {}).get("result") or []
    for stream in result:
        labels = stream.get("stream") or stream.get("metric") or {}
        for value in stream.get("values") or []:
            if len(value) != 2:
                continue
            ts_raw, raw = value
            try:
                ts_ns = int(ts_raw)
            except (TypeError, ValueError):
                continue
            fields = extract_json_fields(raw, parse_json)
            records.append({
                "ts_ns": ts_ns,
                "ts_iso": ns_to_iso(ts_ns),
                "labels": labels,
                "raw": raw,
                "fields": fields,
                "level": pick_field(fields, LEVEL_FIELDS) or labels.get("level"),
                "message": pick_field(fields, MESSAGE_FIELDS),
            })
    records.sort(key=lambda r: r["ts_ns"], reverse=True)
    return records


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def project_fields(record, fields):
    if not fields:
        return record
    projected = dict(record)
    projected["fields"] = {k: record["fields"].get(k) for k in fields if k in record["fields"]}
    return projected


def format_text(records, fields=None, max_line_chars=DEFAULT_MAX_LINE_CHARS):
    lines = []
    for r in records:
        label_str = "{" + ",".join(f"{k}={v}" for k, v in sorted(r["labels"].items())) + "}"
        level = r["level"] or "-"
        if fields:
            projected = {k: r["fields"].get(k) for k in fields if k in r["fields"]}
            message = json.dumps(projected, ensure_ascii=False)
        else:
            message = r["message"] if r["message"] is not None else r["raw"]
        line = f'{r["ts_iso"]}  {level}  {label_str}  {message}'
        if len(line) > max_line_chars:
            line = line[: max_line_chars - 1] + "…"
        lines.append(line)
    return "\n".join(lines)


def format_ndjson(records, fields=None):
    return "\n".join(json.dumps(project_fields(r, fields), ensure_ascii=False) for r in records)


def format_json(records, fields=None):
    return json.dumps([project_fields(r, fields) for r in records], ensure_ascii=False, indent=2)


def format_raw(records):
    return "\n".join(r["raw"] for r in records)


def format_records(records, output, fields=None, max_line_chars=DEFAULT_MAX_LINE_CHARS):
    if output == "ndjson":
        return format_ndjson(records, fields)
    if output == "json":
        return format_json(records, fields)
    if output == "raw":
        return format_raw(records)
    return format_text(records, fields, max_line_chars)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_arg_parser():
    parser = argparse.ArgumentParser(
        prog="loki.py",
        description="Query a Grafana Loki server: run LogQL queries, list labels, and inspect streams.",
    )
    parser.add_argument("--url", help="Loki base URL, e.g. http://loki.lan:3100")
    parser.add_argument("--endpoint", help="named endpoint from ~/.config/.loki/loki.json")

    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_time_args(p):
        p.add_argument("--since", help="lookback duration, e.g. 30m, 2h, 7d (default: 1h)")
        p.add_argument("--start", help="range start: ISO-8601, -2h, now, or unix s/ms/ns")
        p.add_argument("--end", help="range end: ISO-8601, -2h, now, or unix s/ms/ns")

    def add_output_args(p):
        p.add_argument("--output", choices=["text", "ndjson", "json", "raw"], default="text")
        p.add_argument("--fields", help="comma-separated list of JSON fields to keep")
        p.add_argument(
            "--no-parse-json", action="store_true",
            help="treat log lines as plain text instead of parsing them as JSON",
        )
        p.add_argument("--max-line-chars", type=int, default=DEFAULT_MAX_LINE_CHARS)

    query_p = subparsers.add_parser("query", help="run a LogQL query over a time range")
    query_p.add_argument("logql")
    add_time_args(query_p)
    query_p.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    query_p.add_argument("--direction", choices=["backward", "forward"], default="backward")
    add_output_args(query_p)

    labels_p = subparsers.add_parser("labels", help="list label names")
    add_time_args(labels_p)
    labels_p.add_argument("--query", help="LogQL stream selector to scope the label search")

    lv_p = subparsers.add_parser("label-values", help="list values for a label")
    lv_p.add_argument("name")
    add_time_args(lv_p)
    lv_p.add_argument("--query", help="LogQL stream selector to scope the label search")

    series_p = subparsers.add_parser("series", help="list streams matching one or more selectors")
    series_p.add_argument("selector", nargs="+", help='LogQL stream selector, e.g. \'{app="api"}\'')
    add_time_args(series_p)

    return parser


def run(args, env=None, fetch=http_get, now_ns_fn=now_ns, config_path=CONFIG_PATH,
        stdout=None, stderr=None):
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr

    start_ns, end_ns = resolve_time_range(args, reference_ns=now_ns_fn())
    base_url = resolve_url(args, env=env, config_path=config_path)
    fields = args.fields.split(",") if getattr(args, "fields", None) else None

    if args.command == "query":
        url, params = build_query_range_url(
            base_url, args.logql, start_ns, end_ns, args.limit, args.direction
        )
        status, body = fetch(url, params)
        raise_for_status(status, body, url)
        data = parse_json_body(body)
        records = parse_response(data, parse_json=not args.no_parse_json)
        text = format_records(records, args.output, fields, args.max_line_chars)
        if text:
            print(text, file=stdout)
        stream_count = len(((data or {}).get("data") or {}).get("result") or [])
        print(f"{len(records)} entries / {stream_count} streams", file=stderr)

    elif args.command == "labels":
        url, params = build_labels_url(base_url, start_ns, end_ns, args.query)
        status, body = fetch(url, params)
        raise_for_status(status, body, url)
        values = parse_json_body(body).get("data") or []
        if values:
            print("\n".join(values), file=stdout)
        print(f"{len(values)} labels", file=stderr)

    elif args.command == "label-values":
        url, params = build_label_values_url(base_url, args.name, start_ns, end_ns, args.query)
        status, body = fetch(url, params)
        raise_for_status(status, body, url)
        values = parse_json_body(body).get("data") or []
        if values:
            print("\n".join(values), file=stdout)
        print(f"{len(values)} values", file=stderr)

    elif args.command == "series":
        url, params = build_series_url(base_url, args.selector, start_ns, end_ns)
        status, body = fetch(url, params)
        raise_for_status(status, body, url)
        series = parse_json_body(body).get("data") or []
        print(json.dumps(series, ensure_ascii=False, indent=2), file=stdout)
        print(f"{len(series)} series", file=stderr)

    return 0


def main(argv=None):
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except LokiError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.exit_code


if __name__ == "__main__":
    sys.exit(main())
