import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.error
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "parallel_client", ROOT / "skills/engineering-research/scripts/parallel.py")
client = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(client)


class Response(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def ok(document):
    return Response(json.dumps(document).encode())


def http_error(code, message="boom", retry_after=None):
    headers = {"Retry-After": retry_after} if retry_after else {}
    return urllib.error.HTTPError("https://api.parallel.ai", code, "error", headers,
                                  io.BytesIO(json.dumps({"error": {"message": message}}).encode()))


def run(argv, responses, env=None):
    """Run main() with queued urlopen responses; return (exit code, stdout JSON, request bodies)."""
    queue, bodies = list(responses), []

    def fake_urlopen(request, timeout):
        bodies.append((request.full_url, json.loads(request.data) if request.data else None))
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    stdout, stderr = io.StringIO(), io.StringIO()
    environ = {"PARALLEL_API_KEY": "test-key", **(env or {})}
    with patch.object(client.urllib.request, "urlopen", fake_urlopen), \
            patch.object(client.time, "sleep", lambda _: None), \
            patch.dict(os.environ, environ, clear=False), \
            patch.object(sys, "argv", ["parallel.py", *argv]), \
            contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        with self_exit() as code:
            client.main()
    return code[0], json.loads(stdout.getvalue()), bodies, stderr.getvalue()


@contextlib.contextmanager
def self_exit():
    code = [None]
    try:
        yield code
    except SystemExit as error:
        code[0] = error.code


class ParallelClientTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.searches = os.path.join(self.tmp.name, "s.json")
        with open(self.searches, "w") as file:
            json.dump({"searches": [
                {"objective": "A", "search_queries": ["a"]},
                {"objective": "B", "search_queries": ["b"]}]}, file)

    def test_search_applies_options_and_retries_rate_limits(self):
        code, out, bodies, _ = run(
            ["search", self.searches, "--mode", "fast", "--max-results", "3"],
            [http_error(429, retry_after="1"), ok({"results": []}), ok({"results": []})])
        self.assertEqual(code, 0)
        self.assertEqual(len(bodies), 3)
        self.assertTrue(all(b[1]["mode"] == "fast" for b in bodies))
        self.assertTrue(all(b[1]["advanced_settings"]["max_results"] == 3 for b in bodies))
        self.assertTrue(all("data" in s for s in out["searches"]))

    def test_search_partial_failure_keeps_results(self):
        code, out, _, err = run(["search", self.searches],
                                [ok({"results": []}), http_error(422, "bad query")])
        self.assertEqual(code, 1)
        self.assertEqual(sum("error" in s for s in out["searches"]), 1)
        self.assertIn("bad query", err)

    def test_rejected_key_is_not_retried(self):
        code, _, bodies, _ = run(["search", self.searches], [http_error(401), http_error(401)])
        self.assertEqual(code, 3)
        self.assertEqual(len(bodies), 2)

    def test_invalid_search_input(self):
        with open(self.searches, "w") as file:
            json.dump({"searches": [{"objective": "x"}]}, file)
        code, out, bodies, _ = run(["search", self.searches], [])
        self.assertEqual(code, 2)
        self.assertEqual(out["error"]["type"], "invalid_input")
        self.assertEqual(bodies, [])

    def test_missing_key(self):
        code, out, _, _ = run(["search", self.searches], [],
                              env={"PARALLEL_API_KEY": "", "PARALLEL_SECRETS_FILE": "/nonexistent"})
        self.assertEqual(code, 3)
        self.assertEqual(out["error"]["type"], "missing_key")

    def test_extract_writes_full_pages_and_reports_url_errors(self):
        pages = os.path.join(self.tmp.name, "pages")
        response = {"results": [{"url": "https://a.test", "title": "A page", "excerpts": [],
                                 "full_content": "# Full A"}],
                    "errors": [{"url": "https://b.test", "error_type": "fetch_error",
                                "http_status_code": 500, "content": "down"}]}
        code, out, bodies, _ = run(["extract", "https://a.test", "https://b.test", "--out", pages],
                                   [ok(response)])
        self.assertEqual(code, 1)
        self.assertEqual(bodies[0][1]["advanced_settings"], {"full_content": True})
        with open(out["pages"][0]["file"]) as file:
            self.assertIn("# Full A", file.read())
        self.assertEqual(out["errors"][0]["url"], "https://b.test")

    def test_deep_run_does_not_retry_creation(self):
        code, _, bodies, _ = run(["deep", "run", "question"], [http_error(503)])
        self.assertEqual(code, 4)
        self.assertEqual(len(bodies), 1)
        self.assertEqual(bodies[0][1]["task_spec"], {"output_schema": {"type": "text"}})

    def test_deep_result_saves_report(self):
        base = os.path.join(self.tmp.name, "report")
        result = {"run": {"run_id": "trun_1", "status": "completed"},
                  "output": {"type": "text", "content": "Answer [1]",
                             "basis": [{"field": "output", "citations": [{"url": "https://c.test"}]}]}}
        code, out, bodies, _ = run(["deep", "result", "trun_1", "--wait", "5", "--out", base],
                                   [http_error(408), ok(result)])
        self.assertEqual(code, 0)
        self.assertIn("/v1/tasks/runs/trun_1/result?timeout=", bodies[0][0])
        self.assertEqual(out["citation_count"], 1)
        with open(base + ".md") as file:
            self.assertEqual(file.read(), "Answer [1]")

    def test_malformed_retry_after_falls_back_to_backoff(self):
        code, out, bodies, _ = run(["search", self.searches],
                                   [http_error(503, retry_after="not-a-date"), ok({"results": []}),
                                    ok({"results": []})])
        self.assertEqual(code, 0)
        self.assertEqual(len(bodies), 3)

    def test_deep_refuses_existing_report_before_creating_run(self):
        base = os.path.join(self.tmp.name, "report")
        with open(base + ".md", "w") as file:
            file.write("earlier paid report")
        code, out, bodies, _ = run(["deep", "run", "question", "--out", base], [])
        self.assertEqual(code, 2)
        self.assertEqual(out["error"]["type"], "output_exists")
        self.assertEqual(bodies, [])
        with open(base + ".md") as file:
            self.assertEqual(file.read(), "earlier paid report")

    def test_deep_force_overwrites_report(self):
        base = os.path.join(self.tmp.name, "report")
        with open(base + ".md", "w") as file:
            file.write("old")
        result = {"run": {"run_id": "trun_1"}, "output": {"type": "text", "content": "new", "basis": []}}
        code, _, _, _ = run(["deep", "result", "trun_1", "--out", base, "--force"], [ok(result)])
        self.assertEqual(code, 0)
        with open(base + ".md") as file:
            self.assertEqual(file.read(), "new")


if __name__ == "__main__":
    unittest.main()
