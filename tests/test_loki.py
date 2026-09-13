import io
import json
import sys
import unittest
from argparse import Namespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import loki  # noqa: E402


def ns(args_dict):
    defaults = {
        "url": None, "endpoint": None,
        "since": None, "start": None, "end": None,
        "output": "text", "fields": None, "no_parse_json": False,
        "max_line_chars": loki.DEFAULT_MAX_LINE_CHARS,
        "limit": loki.DEFAULT_LIMIT, "direction": "backward",
        "query": None,
    }
    defaults.update(args_dict)
    return Namespace(**defaults)


class TimeParsingTests(unittest.TestCase):
    def test_duration_units(self):
        self.assertEqual(loki.parse_duration_ns("30m"), 30 * loki.UNIT_NS["m"])
        self.assertEqual(loki.parse_duration_ns("2h"), 2 * loki.UNIT_NS["h"])
        self.assertEqual(loki.parse_duration_ns("7d"), 7 * loki.UNIT_NS["d"])

    def test_invalid_duration(self):
        with self.assertRaises(loki.ConfigError):
            loki.parse_duration_ns("banana")

    def test_timestamp_now(self):
        ref = 1_000_000_000_000_000_000
        self.assertEqual(loki.parse_timestamp_ns("now", ref), ref)

    def test_timestamp_relative(self):
        ref = 1_000_000_000_000_000_000
        self.assertEqual(loki.parse_timestamp_ns("-2h", ref), ref - 2 * loki.UNIT_NS["h"])

    def test_timestamp_unix_seconds(self):
        self.assertEqual(loki.parse_timestamp_ns("1700000000", 0), 1700000000 * loki.UNIT_NS["s"])

    def test_timestamp_unix_millis(self):
        self.assertEqual(loki.parse_timestamp_ns("1700000000000", 0), 1700000000000 * loki.UNIT_NS["ms"])

    def test_timestamp_unix_nanos(self):
        value = 1_700_000_000_000_000_000
        self.assertEqual(loki.parse_timestamp_ns(str(value), 0), value)

    def test_timestamp_iso(self):
        result = loki.parse_timestamp_ns("2026-09-04T10:00:00Z", 0)
        self.assertEqual(result, 1788516000 * loki.UNIT_NS["s"])

    def test_timestamp_invalid(self):
        with self.assertRaises(loki.ConfigError):
            loki.parse_timestamp_ns("not-a-time", 0)


class TimeRangeResolutionTests(unittest.TestCase):
    def test_default_since(self):
        start, end = loki.resolve_time_range(ns({}), reference_ns=10 * loki.UNIT_NS["h"])
        self.assertEqual(end, 10 * loki.UNIT_NS["h"])
        self.assertEqual(start, 9 * loki.UNIT_NS["h"])

    def test_explicit_since(self):
        start, end = loki.resolve_time_range(ns({"since": "2h"}), reference_ns=10 * loki.UNIT_NS["h"])
        self.assertEqual(start, 8 * loki.UNIT_NS["h"])

    def test_start_and_end(self):
        start, end = loki.resolve_time_range(
            ns({"start": "1000", "end": "2000"}), reference_ns=0
        )
        self.assertEqual(start, 1000 * loki.UNIT_NS["s"])
        self.assertEqual(end, 2000 * loki.UNIT_NS["s"])

    def test_since_with_start_is_error(self):
        with self.assertRaises(loki.ConfigError):
            loki.resolve_time_range(ns({"since": "1h", "start": "1000", "end": "2000"}))

    def test_start_without_end_is_error(self):
        with self.assertRaises(loki.ConfigError):
            loki.resolve_time_range(ns({"start": "1000"}))

    def test_end_without_start_is_error(self):
        with self.assertRaises(loki.ConfigError):
            loki.resolve_time_range(ns({"end": "2000"}))


class UrlBuilderTests(unittest.TestCase):
    def test_query_range_url(self):
        url, params = loki.build_query_range_url("http://loki", '{app="api"}', 1, 2, 50, "backward")
        self.assertEqual(url, "http://loki/loki/api/v1/query_range")
        self.assertEqual(params, {
            "query": '{app="api"}', "start": "1", "end": "2",
            "limit": "50", "direction": "backward",
        })

    def test_labels_url_without_query(self):
        url, params = loki.build_labels_url("http://loki", 1, 2)
        self.assertEqual(url, "http://loki/loki/api/v1/labels")
        self.assertEqual(params, {"start": "1", "end": "2"})

    def test_labels_url_with_query(self):
        _, params = loki.build_labels_url("http://loki", 1, 2, query='{app="api"}')
        self.assertEqual(params["query"], '{app="api"}')

    def test_label_values_url(self):
        url, params = loki.build_label_values_url("http://loki", "app", 1, 2)
        self.assertEqual(url, "http://loki/loki/api/v1/label/app/values")
        self.assertEqual(params, {"start": "1", "end": "2"})

    def test_label_values_url_escapes_name(self):
        url, _ = loki.build_label_values_url("http://loki", "a b", 1, 2)
        self.assertIn("a%20b", url)

    def test_series_url(self):
        url, params = loki.build_series_url("http://loki", ['{app="api"}', '{app="web"}'], 1, 2)
        self.assertEqual(url, "http://loki/loki/api/v1/series")
        self.assertEqual(params["match[]"], ['{app="api"}', '{app="web"}'])


class ParseResponseTests(unittest.TestCase):
    def make_data(self):
        return {
            "data": {
                "result": [
                    {
                        "stream": {"app": "api"},
                        "values": [
                            ["1000000000", json.dumps({"level": "info", "message": "hello"})],
                            ["3000000000", json.dumps({"level": "error", "message": "boom"})],
                        ],
                    },
                    {
                        "stream": {"app": "web"},
                        "values": [
                            ["2000000000", "plain text line"],
                        ],
                    },
                ]
            }
        }

    def test_flattens_and_sorts_newest_first(self):
        records = loki.parse_response(self.make_data())
        self.assertEqual([r["ts_ns"] for r in records], [3000000000, 2000000000, 1000000000])

    def test_extracts_level_and_message_from_json(self):
        records = loki.parse_response(self.make_data())
        error_record = next(r for r in records if r["ts_ns"] == 3000000000)
        self.assertEqual(error_record["level"], "error")
        self.assertEqual(error_record["message"], "boom")

    def test_non_json_line_has_no_parsed_fields(self):
        records = loki.parse_response(self.make_data())
        plain_record = next(r for r in records if r["ts_ns"] == 2000000000)
        self.assertEqual(plain_record["fields"], {})
        self.assertIsNone(plain_record["message"])
        self.assertEqual(plain_record["raw"], "plain text line")

    def test_no_parse_json_skips_parsing(self):
        records = loki.parse_response(self.make_data(), parse_json=False)
        error_record = next(r for r in records if r["ts_ns"] == 3000000000)
        self.assertEqual(error_record["fields"], {})
        self.assertIsNone(error_record["level"])

    def test_level_falls_back_to_label(self):
        data = {"data": {"result": [{
            "stream": {"app": "api", "level": "warn"},
            "values": [["1000000000", "plain"]],
        }]}}
        records = loki.parse_response(data)
        self.assertEqual(records[0]["level"], "warn")

    def test_malformed_timestamp_is_skipped(self):
        data = {"data": {"result": [{
            "stream": {"app": "api"},
            "values": [["not-a-number", "line"]],
        }]}}
        self.assertEqual(loki.parse_response(data), [])

    def test_empty_response(self):
        self.assertEqual(loki.parse_response({}), [])
        self.assertEqual(loki.parse_response(None), [])


class OutputFormatterTests(unittest.TestCase):
    def setUp(self):
        self.records = loki.parse_response({
            "data": {"result": [{
                "stream": {"app": "api"},
                "values": [["1000000000", json.dumps({"level": "error", "message": "boom"})]],
            }]}
        })

    def test_text_format(self):
        text = loki.format_text(self.records)
        self.assertIn("error", text)
        self.assertIn("boom", text)
        self.assertIn("app=api", text)

    def test_text_format_truncates_long_lines(self):
        text = loki.format_text(self.records, max_line_chars=20)
        line = text.splitlines()[0]
        self.assertLessEqual(len(line), 20)
        self.assertTrue(line.endswith("…"))

    def test_ndjson_format_is_one_object_per_line(self):
        text = loki.format_ndjson(self.records)
        lines = text.splitlines()
        self.assertEqual(len(lines), 1)
        parsed = json.loads(lines[0])
        self.assertEqual(parsed["level"], "error")

    def test_json_format_is_array(self):
        parsed = json.loads(loki.format_json(self.records))
        self.assertIsInstance(parsed, list)
        self.assertEqual(parsed[0]["message"], "boom")

    def test_raw_format(self):
        text = loki.format_raw(self.records)
        self.assertEqual(text, json.dumps({"level": "error", "message": "boom"}))

    def test_fields_projection(self):
        parsed = json.loads(loki.format_json(self.records, fields=["level"]))
        self.assertEqual(parsed[0]["fields"], {"level": "error"})


class ConfigResolutionTests(unittest.TestCase):
    def test_flag_takes_priority(self):
        args = ns({"url": "http://from-flag:3100"})
        url = loki.resolve_url(args, env={"LOKI_URL": "http://from-env:3100"})
        self.assertEqual(url, "http://from-flag:3100")

    def test_env_used_when_no_flag(self):
        args = ns({})
        url = loki.resolve_url(args, env={"LOKI_URL": "http://from-env:3100"})
        self.assertEqual(url, "http://from-env:3100")

    def test_config_file_default_used_last(self):
        args = ns({})
        config = {"default": "prod", "endpoints": {"prod": {"url": "http://from-config:3100"}}}
        url = loki.resolve_url(args, env={}, config=config)
        self.assertEqual(url, "http://from-config:3100")

    def test_named_endpoint_flag(self):
        args = ns({"endpoint": "staging"})
        config = {"endpoints": {"staging": {"url": "http://staging:3100"}, "prod": {"url": "http://prod:3100"}}}
        url = loki.resolve_url(args, env={}, config=config)
        self.assertEqual(url, "http://staging:3100")

    def test_named_endpoint_env(self):
        args = ns({})
        config = {"endpoints": {"staging": {"url": "http://staging:3100"}}}
        url = loki.resolve_url(args, env={"LOKI_ENDPOINT": "staging"}, config=config)
        self.assertEqual(url, "http://staging:3100")

    def test_unknown_endpoint_raises(self):
        args = ns({"endpoint": "missing"})
        with self.assertRaises(loki.ConfigError):
            loki.resolve_url(args, env={}, config={"endpoints": {}})

    def test_no_source_raises(self):
        args = ns({})
        with self.assertRaises(loki.ConfigError):
            loki.resolve_url(args, env={}, config=None)

    def test_trailing_slash_is_stripped(self):
        args = ns({"url": "http://host:3100/"})
        self.assertEqual(loki.resolve_url(args, env={}), "http://host:3100")


class RunNetworkTests(unittest.TestCase):
    def test_5xx_raises_api_error_without_retry(self):
        calls = []

        def fake_fetch(url, params):
            calls.append(1)
            return 500, "internal error"

        args = ns({"url": "http://loki", "command": "query", "logql": '{app="api"}'})
        with self.assertRaises(loki.ApiError):
            loki.run(args, env={}, fetch=fake_fetch, now_ns_fn=lambda: 0)
        self.assertEqual(len(calls), 1)

    def test_query_success_writes_summary_to_stderr(self):
        def fake_fetch(url, params):
            return 200, json.dumps({"data": {"result": [{
                "stream": {"app": "api"},
                "values": [["1000000000", "line"]],
            }]}})

        args = ns({"url": "http://loki", "command": "query", "logql": '{app="api"}'})
        stdout, stderr = io.StringIO(), io.StringIO()
        code = loki.run(args, env={}, fetch=fake_fetch, now_ns_fn=lambda: 0, stdout=stdout, stderr=stderr)
        self.assertEqual(code, 0)
        self.assertIn("line", stdout.getvalue())
        self.assertIn("1 entries / 1 streams", stderr.getvalue())

    def test_config_error_before_any_network_call(self):
        calls = []

        def fake_fetch(url, params):
            calls.append(1)
            return 200, "{}"

        args = ns({"command": "labels"})
        with self.assertRaises(loki.ConfigError):
            loki.run(args, env={}, fetch=fake_fetch, now_ns_fn=lambda: 0)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
