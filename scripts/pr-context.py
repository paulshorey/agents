#!/usr/bin/env python3
"""Read a GitHub PR through gh, paginate its feedback, and emit compact JSON."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
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


REVIEW_TRIGGER = "@codex review"
CODEX_RECEIPT = re.compile(re.escape("<!-- codex-review-receipt:v1 -->"))
CODEX_BOTS = frozenset({"chatgpt-codex-connector[bot]", "chatgpt-codex-connector"})
DETAILS_TAG = re.compile(r"</?details\b[^>]*>", re.IGNORECASE)
CODEX_ABOUT = re.compile(
    r"<summary\b[^>]*>\s*ℹ️ About Codex in GitHub\s*</summary\s*>", re.IGNORECASE,
)
CODEX_STATE = re.compile(r"<!-- codex-review-state:v1 (\{.*?\}) -->", re.DOTALL)
CODEX_SUMMARY = re.compile(
    r"<!-- codex-pull-request-review-summary -->|^##[ \t]+Codex Review Summary[ \t]*$",
    re.MULTILINE,
)
INLINE_CODE = re.compile(
    r"(?<!`)(`+)(?!`)(?:(?!\n[ \t]*\n).)*?(?<!`)\1(?!`)", re.DOTALL,
)


def mask_markdown_code(body):
    """Hide code from the HTML scan while preserving offsets into the original."""
    blocks = []
    fence, start, offset = None, 0, 0
    indented, blank_before = None, True
    prefix = r"[ \t]*(?:>[ \t]*)*"
    for line in body.splitlines(keepends=True):
        content = re.sub(r"^(?: {0,3}>[ \t]?)+", "", line)
        code_line = re.match(r"(?: {4}|\t)", content) is not None
        if indented is not None:
            if code_line or not content.strip():
                offset += len(line)
                blank_before = not content.strip()
                continue
            blocks.append((indented, offset))
            indented = None
        if fence:
            if re.fullmatch(prefix + re.escape(fence[0]) + "{" + str(len(fence)) + r",}[ \t]*\r?\n?", line):
                blocks.append((start, offset + len(line)))
                fence = None
        elif code_line and blank_before:
            indented = offset
        else:
            opening = re.match(prefix + r"(?:[-+*] |\d+[.)] )?(`{3,}|~{3,})([^\r\n]*)", line)
            if opening and (opening[1][0] == "~" or "`" not in opening[2]):
                fence, start = opening[1], offset
        offset += len(line)
        blank_before = not content.strip()
    if fence:
        blocks.append((start, len(body)))
    if indented is not None:
        blocks.append((indented, len(body)))
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


def filter_body(body, author=None):
    """Drop bare review-request comments; clean only Codex-authored boilerplate.

    Human comments are returned unchanged, and Codex findings are never dropped,
    even when they mention the trigger or quote Codex boilerplate.
    """
    if body.strip() == REVIEW_TRIGGER:
        return None
    if author not in CODEX_BOTS:
        return body
    scan = mask_markdown_code(body)
    # Codex's sticky summary is completion state, reported as codex_review.
    if CODEX_SUMMARY.search(scan):
        return None
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
    # Markers inside code examples are masked in the scan and therefore kept.
    removed.extend(marker.span() for marker in CODEX_RECEIPT.finditer(scan))
    cursor, pieces = 0, []
    for start, end in sorted(removed):
        if start >= cursor:
            pieces.append(body[cursor:start])
            cursor = end
    body = "".join([*pieces, body[cursor:]])
    lines = body.splitlines(keepends=True)
    start, end = 0, len(lines)
    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    return "".join(lines[start:end]).rstrip("\r\n")


class GitHub:
    def __init__(self, url):
        parsed = urlparse(url)
        match = re.fullmatch(r"/([^/]+)/([^/]+)/pull/(\d+)/?", parsed.path)
        if parsed.scheme != "https" or not parsed.hostname or not match:
            raise FetchError("gh returned an unrecognized PR URL.")
        try:
            port = parsed.port
        except ValueError:
            raise FetchError("gh returned an unrecognized PR URL.") from None
        # gh selects Enterprise hosts by host[:port]; dropping a custom port targets another host.
        self.host = parsed.hostname if port is None else f"{parsed.hostname}:{port}"
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


def feedback(raw, kind, include_hunks=False):
    item = {
        "kind": kind, "id": raw["id"], "author": login(raw.get("user")),
        "body": raw.get("body") or "", "url": raw.get("html_url"),
        "created_at": raw.get("created_at") or raw.get("submitted_at"),
        "updated_at": raw.get("updated_at") or raw.get("submitted_at"),
    }
    if kind == "inline":
        # Hunks repeat diff context per comment and dominate output size.
        item.update(select(
            raw, "path", "line", "start_line", "side", "start_side", "original_line",
            "original_start_line", *(["diff_hunk"] if include_hunks else []),
            "in_reply_to_id", "commit_id", "original_commit_id", "subject_type",
        ))
        item["review_id"] = raw.get("pull_request_review_id")
    elif kind == "review":
        item["review_id"] = raw["id"]
    return item


def review_state(reviews):
    return {review["id"]: tuple(review.get(key) for key in (
        "state", "commit_id", "submitted_at", "body",
    )) for review in reviews}


def comment_state(comments):
    return {comment["id"]: (comment.get("updated_at"), comment.get("body"))
            for comment in comments}


THREAD_FIELDS = ("id isResolved isOutdated path line startLine diffSide "
                 "comments(first:1) { nodes { databaseId } }")


def thread_state(threads):
    return {thread["id"]: (
        tuple(thread.get(key) for key in ("isResolved", "isOutdated", "path", "line", "startLine", "diffSide")),
        thread["comments"]["nodes"],
    ) for thread in threads}


def reactions(api, path):
    return [{**select(reaction, "id", "content", "created_at"),
             "author": login(reaction.get("user"))} for reaction in api.pages(path)]


CODEX_COMPLETED_AT = re.compile(r'<relative-time datetime="([^"]+)"')
CLEAN_NOTE = re.compile(r"<!-- codex-clean-review-note:v1 ([0-9a-f]+) -->")


# Codex submits a run's review 2-4 s before marking the run completed, and a run takes
# minutes, so an earlier run's review of the same commit can't fall inside this window.
REVIEW_RUN_WINDOW = 120


def parse_time(value):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None
    except ValueError:
        return None


def codex_findings(sha, completed_at, inline_comments, reviews):
    """Link Codex's reviews of `sha` to the run that finished at completed_at.

    Returns (match, top-level inline findings in the matched review), where match is
    "run" (a review submitted within REVIEW_RUN_WINDOW before completion), "earlier"
    (only reviews submitted before that window: an earlier run or a delayed one, so
    the run can't be called clean), or None (no Codex review of the commit before
    completion). Codex marks `has_any_findings` for the whole PR, not per review,
    so it can't classify a run.
    """
    done = parse_time(completed_at)
    run, earlier = None, False
    for review in reviews:
        submitted = parse_time(review.get("submitted_at"))
        if not (login(review.get("user")) in CODEX_BOTS and sha and review.get("commit_id") == sha
                and done and submitted and submitted <= done):
            continue
        if (done - submitted).total_seconds() > REVIEW_RUN_WINDOW:
            earlier = True
        elif run is None or submitted > parse_time(run.get("submitted_at")):
            run = review
    if run is None:
        return ("earlier" if earlier else None), 0
    count = sum(1 for c in inline_comments if c.get("pull_request_review_id") == run["id"]
                and not c.get("in_reply_to_id"))
    return "run", count


def codex_review(comments, head, inline_comments=(), reviews=()):
    """Codex's latest machine-readable review state, from its summary comment.

    A review without findings posts no review object, so this state is the only
    record linking it to a commit. Codex edits one summary comment in place, so
    GitHub shows it at its original time; `summary` says so in plain words. It is
    reported even when filtering hides the summary comment. Markers quoted inside
    code examples are ignored.
    """
    latest = None
    for comment in comments:
        if login(comment.get("user")) not in CODEX_BOTS:
            continue
        body = comment.get("body") or ""
        match = CODEX_STATE.search(mask_markdown_code(body))
        if match and (latest is None
                      or (comment.get("updated_at") or "") > (latest[0].get("updated_at") or "")):
            latest = (comment, body[match.start(1):match.end(1)])
    if latest is None:
        return None
    comment, text = latest
    try:
        state = json.loads(text)
    except json.JSONDecodeError:
        state = None
    code = state.get("code_review") if isinstance(state, dict) else None
    code = code if isinstance(code, dict) else {}
    sha, status = code.get("commit_sha"), code.get("status")
    covers = sha == head and status == "completed"
    created, updated = comment.get("created_at"), comment.get("updated_at")
    completed = CODEX_COMPLETED_AT.search(comment.get("body") or "")
    completed_at = completed[1] if completed else updated
    match, findings = codex_findings(sha, completed_at, inline_comments, reviews)
    if not sha or not status:
        outcome = "unknown"
    elif status != "completed":
        outcome = status
    else:
        # A review object from this run means findings, even if its comments were deleted.
        outcome = {"run": "findings", "earlier": "ambiguous"}.get(match, "clean")
    edited = bool(created and updated and created != updated)
    short = (sha or "?")[:7]
    if outcome == "clean":
        summary = f"Codex completed a review of {short} at {completed_at} and posted no new findings."
    elif outcome == "findings":
        summary = f"Codex completed a review of {short} at {completed_at} and posted a review with {findings} inline finding(s)."
    elif outcome == "ambiguous":
        summary = (f"Codex completed a review of {short} at {completed_at}, but a Codex review of the same"
                   " commit was submitted earlier than this run's window; it may be an earlier run or a"
                   " delayed one, so treat this run as unconfirmed and check that review's findings.")
    else:
        summary = f"Codex review of {short} is {outcome} (summary updated {updated})."
    if edited:
        summary += (f" This is recorded only by editing Codex's summary comment, created {created};"
                    " GitHub shows it at that original time, not as a new comment.")
    if sha != head:
        summary += f" It does not cover the current head {head[:7]}."
    # Only a comment that starts with the marker counts; quoted or code examples don't.
    noted = any(m[1] == head for c in comments
                if (m := CLEAN_NOTE.match(mask_markdown_code(c.get("body") or ""))))
    result = {
        "comment_id": comment["id"], "url": comment.get("html_url"),
        "created_at": created, "updated_at": updated, "edited_in_place": edited,
        "reviewed_commit": sha, "status": status, "completed_at": completed_at,
        "findings_on_reviewed_commit": findings, "outcome": outcome,
        "summary": summary, "state": state, "covers_head": covers,
        "clean_note_posted": noted,
    }
    if covers and outcome == "clean" and not noted:
        result["clean_note"] = (
            f"<!-- codex-clean-review-note:v1 {head} -->\n"
            f"Codex review of `{head[:7]}` completed at {completed_at} with no new findings. "
            f"Codex records clean reviews only by editing its [summary comment]({comment.get('html_url')}), "
            "which GitHub keeps at its original time, so this note marks the result.")
    return result


def fetch_context(api, include_diff=False, no_filter=False, include_hunks=False):
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
    initial_issue_state = comment_state(issue_comments)
    initial_inline_state = comment_state(inline_comments)
    raw_reviews = api.pages(f"{api.pull}/reviews")
    initial_review_state = review_state(raw_reviews)
    raw_threads, state = api.connection("reviewThreads", THREAD_FIELDS)
    initial_thread_state = thread_state(raw_threads)
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
    # The statuses endpoint returns every update; keep each context's newest state
    # so an earlier pending/failure is never mistaken for the current result.
    history = api.pages(f"{api.prefix}/commits/{head}/statuses")
    # GitHub caps a ref's status history at 1,000; a truncated list could omit a context.
    if len(history) >= 1000:
        raise FetchError("Commit-status API limit reached; inspect statuses directly before claiming completeness.")
    history.sort(reverse=True,
                 key=lambda s: (s.get("updated_at") or s.get("created_at") or "", s.get("id") or 0))
    latest = {}
    for status in history:
        latest.setdefault(status.get("context"), status)
    statuses = [select(status, "id", "context", "state", "description", "target_url",
                       "created_at", "updated_at") for status in latest.values()]

    comments = ([feedback(c, "issue") for c in issue_comments]
                + [feedback(c, "inline", include_hunks) for c in inline_comments]
                + [feedback(r, "review") for r in raw_reviews if r.get("body")])
    filtering = {"enabled": not no_filter, "removed_comments": 0, "cleaned_comments": 0}
    kept = []
    for comment in comments:
        body = comment["body"] if no_filter else filter_body(comment["body"], comment["author"])
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
        "codex_review": codex_review(issue_comments, head, inline_comments, raw_reviews),
        "pr_reactions": reactions(api, f"{api.prefix}/issues/{api.number}/reactions"),
    }
    if include_diff:
        output["diff"] = gh("pr", "diff", raw["html_url"], "--color", "never", as_json=False)
    if review_state(api.pages(f"{api.pull}/reviews")) != initial_review_state:
        raise FetchError("Submitted PR reviews changed during the fetch; rerun for the latest feedback.")
    if (comment_state(api.pages(f"{api.prefix}/issues/{api.number}/comments")) != initial_issue_state
            or comment_state(api.pages(f"{api.pull}/comments")) != initial_inline_state):
        raise FetchError("PR comment text changed during the fetch; rerun for the latest feedback.")
    final_threads, _ = api.connection("reviewThreads", THREAD_FIELDS)
    if thread_state(final_threads) != initial_thread_state:
        raise FetchError("PR review threads changed during the fetch; rerun for current dispositions.")
    if reactions(api, f"{api.prefix}/issues/{api.number}/reactions") != output["pr_reactions"]:
        raise FetchError("PR reactions changed during the fetch; rerun for current review status.")
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
    parser.add_argument("--hunks", action="store_true", help="include each inline comment's diff_hunk (large)")
    parser.add_argument("--output", "-o", type=Path,
                        help="write the JSON to this file instead of stdout; replaced only after a complete fetch")
    args = parser.parse_args(argv)
    view_args = ["pr", "view"]
    if args.pr:
        view_args.append(args.pr)
    if args.repo:
        view_args.extend(["--repo", args.repo])
    try:
        resolved = gh(*view_args, "--json", "url")
        output = fetch_context(GitHub(resolved["url"]), args.diff, args.no_filter, args.hunks)
    except (FetchError, KeyError, TypeError, IndexError) as exc:
        message = str(exc) if isinstance(exc, FetchError) else "Unexpected GitHub response; snapshot is incomplete."
        print(f"pr-context: {message}", file=sys.stderr)
        return 1
    # One document only after every request succeeds; failed reads emit no partial JSON.
    text = json.dumps(output, ensure_ascii=False, separators=(",", ":"))
    if not args.output:
        print(text)
        return 0
    temporary = None
    try:
        # mkstemp creates a new 0600 file exclusively; it never follows a planted path.
        descriptor, name = tempfile.mkstemp(
            prefix=f".{args.output.name}.", suffix=".tmp", dir=args.output.parent)
        temporary = Path(name)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
        os.replace(temporary, args.output)
    except OSError as exc:
        if temporary:
            temporary.unlink(missing_ok=True)
        print(f"pr-context: could not write {args.output}: {exc.strerror or type(exc).__name__}",
              file=sys.stderr)
        return 1
    print(f"pr-context: wrote {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
