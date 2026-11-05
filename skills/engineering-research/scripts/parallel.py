#!/usr/bin/env python3
"""Parallel web research client: search, full-page extract, and deep research.

Standard library only. Reads PARALLEL_API_KEY from the environment, or from
~/.secrets.sh (override with PARALLEL_SECRETS_FILE) when unset. Never prints it.

  parallel.py search SEARCHES.json [--mode MODE] [--max-results N]
  parallel.py extract URL... [--objective TEXT] [--out DIR] [--fresh]
  parallel.py deep run QUESTION [--processor P] [--previous-interaction-id ID]
                                [--wait SECONDS] [--out BASE] [--force]
  parallel.py deep result RUN_ID [--wait SECONDS] [--out BASE] [--force]
  parallel.py deep status RUN_ID

Every command prints one JSON document to stdout. Exit codes: 0 success,
1 some requests failed (successful results are still printed), 2 invalid input,
3 missing or rejected API key, 4 all requests failed, 5 deep run still pending.
"""

import argparse
import concurrent.futures
import email.utils
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

API = "https://api.parallel.ai"
RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_RETRIES = 2
EXTRACT_BATCH = 20


class Failure(Exception):
    def __init__(self, info):
        super().__init__(info.get("message", "request failed"))
        self.info = info


def load_key():
    key = os.environ.get("PARALLEL_API_KEY", "").strip()
    if key:
        return key
    path = os.path.expanduser(os.environ.get("PARALLEL_SECRETS_FILE", "~/.secrets.sh"))
    if os.path.isfile(path):
        try:
            out = subprocess.run(
                ["bash", "-c", 'source "$1" >/dev/null 2>&1; printf %s "${PARALLEL_API_KEY:-}"', "_", path],
                capture_output=True, text=True, timeout=20, check=False,
            )
            key = out.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            key = ""
    if not key:
        emit({"error": {"type": "missing_key", "message": "PARALLEL_API_KEY is not set in the environment or the secrets file."}})
        sys.exit(3)
    return key


def emit(document):
    print(json.dumps(document, ensure_ascii=False, indent=2))


def retry_delay(attempt, retry_after):
    if retry_after:
        try:
            return min(60.0, max(0.0, float(retry_after)))
        except ValueError:
            try:
                parsed = email.utils.parsedate_to_datetime(retry_after)
                return min(60.0, max(0.0, parsed.timestamp() - time.time()))
            except (TypeError, ValueError, OverflowError):
                pass
    return min(30.0, 2 ** attempt + random.uniform(0, 1))


def request(key, method, path, body=None, timeout=90, retry=True, query=""):
    """Send one API request. Returns (status, parsed JSON). Raises Failure."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    url = API + path + query
    attempt = 0
    while True:
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Content-Type": "application/json", "x-api-key": key, "User-Agent": "agents-engineering-research/1"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            text = error.read(2000).decode("utf-8", "replace")
            info = {"status": error.code, "message": text}
            try:
                info["message"] = json.loads(text).get("error", {}).get("message", text)
            except (ValueError, AttributeError):
                pass
            retry_after = error.headers.get("Retry-After") if error.headers else None
            if retry and error.code in RETRY_STATUSES and attempt < MAX_RETRIES:
                time.sleep(retry_delay(attempt, retry_after))
                attempt += 1
                continue
            info["attempts"] = attempt + 1
            raise Failure(info) from None
        except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError) as error:
            if retry and attempt < MAX_RETRIES:
                time.sleep(retry_delay(attempt, None))
                attempt += 1
                continue
            raise Failure({"message": f"{type(error).__name__}: {error}", "attempts": attempt + 1}) from None


def describe(error):
    parts = [str(error[k]) for k in ("url", "status", "message") if error.get(k) not in (None, "")]
    return ("parallel.py error: " + " | ".join(parts))[:400]


def auth_failed(errors):
    return any(e.get("status") in (401, 403) for e in errors)


def finish(document, errors, total):
    emit(document)
    if not errors:
        return 0
    for error in errors:
        print(describe(error), file=sys.stderr)
    if auth_failed(errors):
        return 3
    return 4 if len(errors) >= total else 1


# ---------------------------------------------------------------- search

def load_searches(path):
    try:
        with open(path, encoding="utf-8") as file:
            searches = json.load(file)["searches"]
        if not isinstance(searches, list) or not searches:
            raise ValueError("searches must contain at least one request")
        for item in searches:
            queries = item.get("search_queries") if isinstance(item, dict) else None
            if (not isinstance(item.get("objective"), str) or not item["objective"].strip()
                    or not isinstance(queries, list) or not queries
                    or not all(isinstance(q, str) and q.strip() for q in queries)):
                raise ValueError("each search needs an objective and nonempty search_queries")
        return searches
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        emit({"error": {"type": "invalid_input", "message": str(error)}})
        sys.exit(2)


def cmd_search(args):
    searches = load_searches(args.file)
    key = load_key()

    def run(index, item):
        body = dict(item)
        if args.mode and "mode" not in body:
            body["mode"] = args.mode
        if args.max_results:
            body.setdefault("advanced_settings", {}).setdefault("max_results", args.max_results)
        try:
            return {"index": index, "data": request(key, "POST", "/v1/search", body)[1]}
        except Failure as failure:
            return {"index": index, "error": failure.info}

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(searches))) as pool:
        results = list(pool.map(lambda pair: run(*pair), enumerate(searches)))
    errors = [r["error"] for r in results if "error" in r]
    return finish({"searches": results}, errors, len(results))


# ---------------------------------------------------------------- extract

def slug(text, limit=60):
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-")[:limit] or "page"


def cmd_extract(args):
    key = load_key()
    out_dir = args.out or tempfile.mkdtemp(prefix="parallel-extract-")
    os.makedirs(out_dir, exist_ok=True)
    settings = {"full_content": {"max_chars_per_result": args.max_chars} if args.max_chars else True}
    if args.fresh:
        settings["fetch_policy"] = {"max_age_seconds": 600}
    batches = [args.urls[i:i + EXTRACT_BATCH] for i in range(0, len(args.urls), EXTRACT_BATCH)]
    pages, errors = [], []
    for batch in batches:
        body = {"urls": batch, "advanced_settings": settings}
        if args.objective:
            body["objective"] = args.objective
        try:
            data = request(key, "POST", "/v1/extract", body, timeout=150)[1]
        except Failure as failure:
            errors.extend({**failure.info, "url": url} for url in batch)
            continue
        for item in data.get("errors") or []:
            errors.append({"url": item.get("url"), "status": item.get("http_status_code"),
                           "message": f"{item.get('error_type')}: {item.get('content') or ''}".strip()})
        for item in data.get("results") or []:
            content = item.get("full_content") or ""
            path = os.path.join(out_dir, f"{len(pages) + 1:02d}-{slug(item.get('title') or item['url'])}.md")
            with open(path, "w", encoding="utf-8") as file:
                file.write(f"<!-- source: {item['url']} | title: {item.get('title') or ''} | published: {item.get('publish_date') or ''} -->\n\n")
                file.write(content if content else "\n\n".join(item.get("excerpts") or []))
            pages.append({"url": item["url"], "title": item.get("title"), "publish_date": item.get("publish_date"),
                          "file": path, "full_content_chars": len(content),
                          "excerpts": item.get("excerpts") if args.objective else None})
    return finish({"output_dir": out_dir, "pages": pages, "errors": errors}, errors, len(args.urls))


# ---------------------------------------------------------------- deep research

def save_result(base, result, force=False):
    existing = [base + ext for ext in (".json", ".md") if os.path.exists(base + ext)]
    if existing and not force:
        raise Failure({"type": "output_exists", "message": f"Refusing to overwrite {', '.join(existing)}; "
                       "choose a new --out or pass --force"})
    os.makedirs(os.path.dirname(os.path.abspath(base)), exist_ok=True)
    paths = {"json": base + ".json"}
    with open(paths["json"], "w", encoding="utf-8") as file:
        json.dump(result, file, ensure_ascii=False, indent=2)
    output = result.get("output") or {}
    if output.get("type") == "text":
        paths["markdown"] = base + ".md"
        with open(paths["markdown"], "w", encoding="utf-8") as file:
            file.write(output.get("content") or "")
    return paths


def summarize(result, paths):
    output = result.get("output") or {}
    citations = [c.get("url") for basis in output.get("basis") or [] for c in basis.get("citations") or []]
    return {"run": result.get("run"), "files": paths, "citation_count": len(citations),
            "content_chars": len(output.get("content") or "") if isinstance(output.get("content"), str) else None}


def wait_for_result(key, run_id, wait, base, force=False):
    deadline = time.time() + wait
    while True:
        chunk = int(max(1, min(60, deadline - time.time())))
        try:
            status, result = request(key, "GET", f"/v1/tasks/runs/{run_id}/result",
                                     timeout=chunk + 60, query=f"?timeout={chunk}")
            base = base or os.path.join(tempfile.mkdtemp(prefix="parallel-deep-"), run_id)
        except Failure as failure:
            code = failure.info.get("status")
            if code == 404:
                _, run = request(key, "GET", f"/v1/tasks/runs/{run_id}")
                return 4, {"run": run, "error": failure.info}
            if code != 408 or time.time() >= deadline:
                if code == 408:
                    return 5, {"run_id": run_id, "pending": True,
                               "message": f"Still running; resume with: deep result {run_id} --wait SECONDS"}
                return (3 if code in (401, 403) else 4), {"run_id": run_id, "error": failure.info}
            continue
        try:
            return 0, summarize(result, save_result(base, result, force))
        except Failure as failure:
            return 2, {"run_id": run_id, "error": failure.info}


def cmd_deep(args):
    existing = [args.out + ext for ext in (".json", ".md") if args.out and os.path.exists(args.out + ext)]
    if existing and not args.force and args.action != "status":
        emit({"error": {"type": "output_exists",
                        "message": f"Refusing to overwrite {', '.join(existing)}; choose a new --out or pass --force"}})
        return 2
    key = load_key()
    try:
        if args.action == "status":
            emit(request(key, "GET", f"/v1/tasks/runs/{args.target}")[1])
            return 0
        if args.action == "run":
            body = {"input": args.target, "processor": args.processor,
                    "task_spec": {"output_schema": {"type": "text"}}}
            if args.previous_interaction_id:
                body["previous_interaction_id"] = args.previous_interaction_id
            # Do not retry creation: a lost response may still have created a billed run.
            run = request(key, "POST", "/v1/tasks/runs", body, retry=False)[1]
            print(json.dumps({"created": {k: run.get(k) for k in ("run_id", "interaction_id", "status", "processor")}}),
                  file=sys.stderr)
            if not args.wait:
                emit({"run": run, "message": f"Started; fetch with: deep result {run['run_id']} --wait SECONDS"})
                return 0
            run_id = run["run_id"]
        else:
            run_id = args.target
        code, document = wait_for_result(key, run_id, args.wait or 60, args.out, args.force)
    except Failure as failure:
        code, document = (3 if failure.info.get("status") in (401, 403) else 4), {"error": failure.info}
    emit(document)
    if "error" in document:
        print(describe(document["error"]), file=sys.stderr)
    return code


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    search = sub.add_parser("search", help="run a batch of searches concurrently")
    search.add_argument("file", help='JSON file: {"searches": [{"objective", "search_queries"}]}')
    search.add_argument("--mode", choices=["turbo", "fast", "basic", "advanced"],
                        help="search mode for entries without one (API default: advanced)")
    search.add_argument("--max-results", type=int, help="results per search (API default: 10)")
    search.set_defaults(handler=cmd_search)

    extract = sub.add_parser("extract", help="save full pages as markdown files")
    extract.add_argument("urls", nargs="+")
    extract.add_argument("--objective", help="also return excerpts focused on this goal")
    extract.add_argument("--out", help="directory for page files (default: new temp directory)")
    extract.add_argument("--max-chars", type=int, help="truncate each page at this many characters")
    extract.add_argument("--fresh", action="store_true", help="refetch pages cached more than 10 minutes ago")
    extract.set_defaults(handler=cmd_extract)

    deep = sub.add_parser("deep", help="asynchronous deep research with a cited report")
    deep.add_argument("action", choices=["run", "result", "status"])
    deep.add_argument("target", help="question (run) or run ID (result, status)")
    deep.add_argument("--processor", default="pro-fast", help="Task processor (default: pro-fast)")
    deep.add_argument("--previous-interaction-id", help="continue from an earlier run's interaction_id")
    deep.add_argument("--wait", type=int, default=0, help="seconds to wait for the report (default: run 0, result 60)")
    deep.add_argument("--out", help="output base path; writes BASE.md and BASE.json (default: temp directory)")
    deep.add_argument("--force", action="store_true", help="overwrite existing BASE.md and BASE.json")
    deep.set_defaults(handler=cmd_deep)

    args = parser.parse_args()
    if getattr(args, "max_results", None) is not None and args.max_results < 1:
        parser.error("--max-results must be positive")
    sys.exit(args.handler(args))


if __name__ == "__main__":
    main()
