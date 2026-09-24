#!/usr/bin/env python3
"""Run distinct Parallel Search requests concurrently and return structured JSON."""

import concurrent.futures
import json
import os
import sys
import urllib.error
import urllib.request


API_URL = "https://api.parallel.ai/v1/search"


def search(index, item, api_key):
    body = json.dumps(item).encode("utf-8")
    request = urllib.request.Request(
        API_URL,
        data=body,
        headers={"Content-Type": "application/json", "x-api-key": api_key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            return {"index": index, "data": json.load(response)}
    except urllib.error.HTTPError as error:
        return {"index": index, "error": {"status": error.code, "retry_after": error.headers.get("Retry-After") if error.headers else None, "message": error.read(1000).decode("utf-8", "replace")}}
    except (urllib.error.URLError, TimeoutError, ValueError) as error:
        return {"index": index, "error": {"message": str(error)}}


def main():
    if len(sys.argv) != 2:
        sys.exit("Usage: search.py searches.json")
    api_key = os.environ.get("PARALLEL_API_KEY")
    if not api_key:
        sys.exit("Set PARALLEL_API_KEY or PARALLEL_AI_API_KEY")
    try:
        with open(sys.argv[1], encoding="utf-8") as file:
            searches = json.load(file)["searches"]
        if not isinstance(searches, list) or len(searches) < 1:
            raise ValueError("searches must contain at least one request")
        for item in searches:
            if (not isinstance(item, dict)
                    or not isinstance(item.get("objective"), str)
                    or not item["objective"].strip()
                    or not isinstance(item.get("search_queries"), list)
                    or not item["search_queries"]
                    or not all(isinstance(q, str) and q.strip() for q in item["search_queries"])):
                raise ValueError("each search needs an objective and nonempty search_queries")
    except (OSError, ValueError, KeyError, TypeError) as error:
        sys.exit(f"Invalid search input: {error}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(searches))) as pool:
        futures = [pool.submit(search, index, item, api_key) for index, item in enumerate(searches)]
        results = [future.result() for future in futures]
    print(json.dumps({"searches": results}, ensure_ascii=False, indent=2))
    if any("error" in result for result in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
