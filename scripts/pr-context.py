#!/usr/bin/env python3
"""Read a GitHub PR through gh, paginate its feedback, and emit compact JSON."""

import argparse
from datetime import datetime, timezone
import json
import os
import re
import subprocess
import sys
from urllib.parse import urlparse


class FetchError(Exception):
    pass


def gh(*args, as_json=True):
    # Disable inherited HTTP debugging: it can expose credentials and response bodies.
    env = {**os.environ, "GH_DEBUG": "", "GH_PAGER": "cat", "GH_PROMPT_DISABLED": "1"}
    try:
        result = subprocess.run(
            ["gh", *args], capture_output=True, text=True, env=env, timeout=60,
        )
    except FileNotFoundError as exc:
        raise FetchError("GitHub CLI (gh) is required; use its existing sign-in.") from exc
    except subprocess.TimeoutExpired as exc:
        raise FetchError("GitHub request timed out; no complete snapshot was produced.") from exc
    if result.returncode:
        status = re.search(r"HTTP \d{3}", result.stderr)
        detail = f"; {status.group()}" if status else ""
        raise FetchError(
            f"gh {args[0]} failed (exit {result.returncode}{detail}). "
            "Check repository access, gh authentication, and rate limits."
        )
    if not as_json:
        return result.stdout
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise FetchError("gh returned invalid JSON; no complete snapshot was produced.") from exc


def select(data, *keys):
    return {key: data[key] for key in keys if key in data}


def login(user):
    return (user or {}).get("login")


DETAILS_TAG = re.compile(r"</?details\b[^>]*>", re.IGNORECASE)
CODEX_ABOUT = re.compile(
    r"<summary\b[^>]*>\s*ℹ️ About Codex in GitHub\s*</summary\s*>", re.IGNORECASE,
)
INLINE_CODE = re.compile(
    r"(?<!`)(`+)(?!`)(?:(?!\n[ \t]*\n).)*?(?<!`)\1(?!`)", re.DOTALL,
)


def mask_markdown_code(body):
    """Hide code from the HTML scan while preserving offsets into the original."""
    blocks = []
    fence, start, offset = None, 0, 0
    prefix = r"[ \t]*(?:>[ \t]*)*"
    for line in body.splitlines(keepends=True):
        if fence:
            if re.fullmatch(prefix + re.escape(fence[0]) + "{" + str(len(fence)) + r",}[ \t]*\r?\n?", line):
                blocks.append((start, offset + len(line)))
                fence = None
        else:
            opening = re.match(prefix + r"(?:[-+*] |\d+[.)] )?(`{3,}|~{3,})([^\r\n]*)", line)
            if opening and (opening[1][0] == "~" or "`" not in opening[2]):
                fence, start = opening[1], offset
        offset += len(line)
    if fence:
        blocks.append((start, len(body)))
    ranges = list(blocks)
    start = 0
    for left, right in [*blocks, (len(body), len(body))]:
        ranges.extend((m.start(), m.end()) for m in INLINE_CODE.finditer(body, start, left))
        start = right
    masked = list(body)
    for left, right in ranges:
        for i in range(left, right):
            if masked[i] not in "\r\n":
                masked[i] = " "
    return "".join(masked)


def filter_body(body):
    """Strip only the marked boilerplate before applying whole-comment exclusions."""
    scan = mask_markdown_code(body)
    stack, removed = [], []
    for tag in DETAILS_TAG.finditer(scan):
        if not tag[0].startswith("</"):
            stack.append((tag.start(), tag.end()))
        elif stack:
            start, content_start = stack.pop()
            # An About summary must belong to this block, not a nested child.
            first_child = DETAILS_TAG.search(scan, content_start, tag.start())
            summary_end = first_child.start() if first_child else tag.start()
            if CODEX_ABOUT.search(scan, content_start, summary_end):
                removed.append((start, tag.end()))
    cursor, pieces = 0, []
    for start, end in sorted(removed):
        if start >= cursor:
            pieces.append(body[cursor:start])
            cursor = end
    body = "".join([*pieces, body[cursor:]])
    if "## Codex Review Summary" in body or "@codex review" in body:
        return None
    return body.replace("<!-- codex-review-receipt:v1 -->", "").strip()


class GitHub:
    def __init__(self, url):
        parsed = urlparse(url)
        match = re.fullmatch(r"/([^/]+)/([^/]+)/pull/(\d+)/?", parsed.path)
        if parsed.scheme != "https" or not parsed.hostname or not match:
            raise FetchError("gh returned an unrecognized PR URL.")
        self.host = parsed.hostname
        self.owner, self.repo, number = match.groups()
        self.number = int(number)
        self.prefix = f"repos/{self.owner}/{self.repo}"
        self.pull = f"{self.prefix}/pulls/{self.number}"

    def api(self, path):
        return gh("api", "--hostname", self.host, path)

    def pages(self, path, key=None):
        separator = "&" if "?" in path else "?"
        pages = gh(
            "api", "--hostname", self.host, "--paginate", "--slurp",
            f"{path}{separator}per_page=100",
        )
        items = []
        totals = []
        for page in pages:
            batch = page[key] if key else page
            if not isinstance(batch, list):
                raise FetchError("Unexpected paginated API response.")
            items.extend(batch)
            if key:
                totals.append(page["total_count"])
        if key and (not totals or any(total != len(items) for total in totals)):
            raise FetchError(f"Incomplete {key} pagination; counts changed or an API limit was reached.")
        if key == "check_runs" and len(items) >= 1000:
            raise FetchError("Check-run API limit reached; inspect check suites before claiming completeness.")
        return items

    def connection(self, name, fields):
        # Only this outer connection has pageInfo. Inline bodies come from the
        # separately paginated REST list, so nested thread replies cannot truncate.
        query = """
          query($owner:String!, $repo:String!, $number:Int!, $endCursor:String) {
            repository(owner:$owner, name:$repo) {
              pullRequest(number:$number) {
                reviewDecision mergeStateStatus
                CONNECTION(first:100, after:$endCursor) {
                  totalCount pageInfo { hasNextPage endCursor }
                  nodes { FIELDS }
                }
              }
            }
          }
        """.replace("CONNECTION", name).replace("FIELDS", fields)
        pages = gh(
            "api", "--hostname", self.host, "graphql", "--paginate", "--slurp",
            "-f", f"query={query}", "-f", f"owner={self.owner}",
            "-f", f"repo={self.repo}", "-F", f"number={self.number}",
        )
        items = []
        state = {}
        connection = None
        for page in pages:
            if page.get("errors"):
                raise FetchError("GitHub returned GraphQL errors; snapshot is incomplete.")
            pull = page["data"]["repository"]["pullRequest"]
            state = select(pull, "reviewDecision", "mergeStateStatus")
            connection = pull[name]
            items.extend(connection["nodes"])
        if connection is None or len(items) != connection["totalCount"]:
            raise FetchError(f"Incomplete {name} pagination; rerun the helper.")
        return items, state


def feedback(raw, kind):
    item = {
        "kind": kind, "id": raw["id"], "author": login(raw.get("user")),
        "body": raw.get("body") or "", "url": raw.get("html_url"),
        "created_at": raw.get("created_at") or raw.get("submitted_at"),
        "updated_at": raw.get("updated_at") or raw.get("submitted_at"),
    }
    if kind == "inline":
        item.update(select(
            raw, "path", "line", "start_line", "side", "start_side", "original_line",
            "original_start_line", "diff_hunk", "in_reply_to_id", "commit_id",
            "original_commit_id", "subject_type",
        ))
        item["review_id"] = raw.get("pull_request_review_id")
    elif kind == "review":
        item["review_id"] = raw["id"]
    return item


def fetch_context(api, include_diff=False, no_filter=False):
    raw = api.api(api.pull)
    head = raw["head"]["sha"]
    pr = select(
        raw, "number", "title", "body", "state", "draft", "created_at", "updated_at",
        "closed_at", "merged_at", "mergeable", "mergeable_state", "merged",
        "additions", "deletions", "changed_files", "maintainer_can_modify",
    )
    pr.update({
        "url": raw["html_url"], "author": login(raw.get("user")),
        "base": {"ref": raw["base"]["ref"], "sha": raw["base"]["sha"],
                 "repo": raw["base"]["repo"]["full_name"]},
        "head": {"ref": raw["head"]["ref"], "sha": head,
                 "repo": (raw["head"].get("repo") or {}).get("full_name")},
        "labels": [label["name"] for label in raw.get("labels", [])],
        "assignees": [login(user) for user in raw.get("assignees", [])],
        "requested_reviewers": [login(user) for user in raw.get("requested_reviewers", [])],
        "requested_teams": [team["slug"] for team in raw.get("requested_teams", [])],
        "milestone": (raw.get("milestone") or {}).get("title"),
    })

    issue_comments = api.pages(f"{api.prefix}/issues/{api.number}/comments")
    inline_comments = api.pages(f"{api.pull}/comments")
    raw_reviews = api.pages(f"{api.pull}/reviews")
    raw_threads, state = api.connection(
        "reviewThreads",
        "id isResolved isOutdated path line startLine diffSide "
        "comments(first:1) { nodes { databaseId } }",
    )
    pr.update(state)
    raw_commits, _ = api.connection(
        "commits", "commit { oid message committedDate url author { name user { login } } }",
    )
    commits = []
    for node in raw_commits:
        commit = node["commit"]
        author = commit.get("author") or {}
        commits.append({
            "sha": commit["oid"], "message": commit["message"],
            "committed_at": commit["committedDate"], "url": commit["url"],
            "author": login(author.get("user")) or author.get("name"),
        })
    files = [select(file, "filename", "previous_filename", "status", "additions",
                    "deletions", "changes", "blob_url") for file in api.pages(f"{api.pull}/files")]
    # GitHub caps the files endpoint at 3,000. Never silently call that complete.
    if len(files) != raw["changed_files"] or len(commits) != raw["commits"]:
        raise FetchError("PR file/commit counts changed or exceed API limits; inspect with git and rerun.")
    checks = [select(check, "id", "name", "status", "conclusion", "html_url", "head_sha",
                     "started_at", "completed_at") for check in api.pages(
                         f"{api.prefix}/commits/{head}/check-runs?filter=latest", "check_runs")]
    statuses = [select(status, "id", "context", "state", "description", "target_url",
                       "created_at", "updated_at") for status in api.pages(
                           f"{api.prefix}/commits/{head}/statuses")]

    comments = ([feedback(c, "issue") for c in issue_comments]
                + [feedback(c, "inline") for c in inline_comments]
                + [feedback(r, "review") for r in raw_reviews if r.get("body")])
    filtering = {"enabled": not no_filter, "removed_comments": 0, "cleaned_comments": 0}
    kept = []
    for comment in comments:
        body = comment["body"] if no_filter else filter_body(comment["body"])
        if body is None:
            filtering["removed_comments"] += 1
            continue
        if body != comment["body"]:
            filtering["cleaned_comments"] += 1
        kept.append({**comment, "body": body})
    kept.sort(key=lambda c: (c["updated_at"] or c["created_at"] or "", c["kind"], c["id"]),
              reverse=True)
    inline_by_root = {}
    for comment in inline_comments:
        root = comment.get("in_reply_to_id") or comment["id"]
        inline_by_root.setdefault(root, []).append(comment["id"])
    visible_inline = {c["id"] for c in kept if c["kind"] == "inline"}
    threads = []
    for thread in raw_threads:
        roots = thread["comments"]["nodes"]
        root = roots[0]["databaseId"] if roots else None
        threads.append({
            **select(thread, "id", "isResolved", "isOutdated", "path", "line", "startLine", "diffSide"),
            "root_comment_id": root,
            "comment_ids": [cid for cid in inline_by_root.get(root, []) if cid in visible_inline],
        })
    # Review state is independent of review text. Filtering must never hide a
    # CHANGES_REQUESTED/APPROVED/DISMISSED decision or its reviewed commit.
    reviews = [{**select(r, "id", "state", "commit_id", "submitted_at"),
                "author": login(r.get("user")), "url": r.get("html_url")} for r in raw_reviews]
    output = {
        "schema_version": 1, "fetched_at": datetime.now(timezone.utc).isoformat(),
        "pr": pr, "commits": commits, "files": files, "checks": checks,
        "statuses": statuses, "reviews": reviews, "comments": kept,
        "threads": threads, "filtering": filtering,
    }
    if include_diff:
        output["diff"] = gh("pr", "diff", raw["html_url"], "--color", "never", as_json=False)
    final = api.api(api.pull)
    if final["head"]["sha"] != head or final["base"]["sha"] != raw["base"]["sha"]:
        raise FetchError("PR head or base changed during the fetch; rerun before acting.")
    if len(issue_comments) != final["comments"] or len(inline_comments) != final["review_comments"]:
        raise FetchError("PR feedback counts changed during the fetch; rerun for the latest comments.")
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pr", nargs="?", help="PR URL, number, or branch; default: current branch")
    parser.add_argument("--repo", "-R", help="[HOST/]OWNER/REPO; otherwise use the current Git repository")
    parser.add_argument("--diff", action="store_true", help="include the full GitHub diff")
    parser.add_argument("--no-filter", action="store_true", help="retain all comment text and entries")
    args = parser.parse_args(argv)
    view_args = ["pr", "view"]
    if args.pr:
        view_args.append(args.pr)
    if args.repo:
        view_args.extend(["--repo", args.repo])
    try:
        resolved = gh(*view_args, "--json", "url")
        output = fetch_context(GitHub(resolved["url"]), args.diff, args.no_filter)
    except (FetchError, KeyError, TypeError, IndexError) as exc:
        message = str(exc) if isinstance(exc, FetchError) else "Unexpected GitHub response; snapshot is incomplete."
        print(f"pr-context: {message}", file=sys.stderr)
        return 1
    # One document only after every request succeeds; failed reads emit no partial JSON.
    print(json.dumps(output, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
