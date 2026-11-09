import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("pr_context", ROOT / "scripts/pr-context.py")
pr_context = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pr_context)
URL = "https://github.com/example/project/pull/7"
BOT = "chatgpt-codex-connector[bot]"


def codex(body):
    return pr_context.filter_body(body, BOT)


class Fixture:
    """Slurped gh responses with more than one page of each feedback type."""

    def __init__(self):
        self.calls = []
        self.issue = [self.comment(i, f"Finding {i}") for i in range(1, 106)]
        self.issue[0]["body"] = "@codex review"
        self.issue[1].update(body="## Codex Review Summary\nNo new findings.", user={"login": BOT})
        self.inline = [self.comment(i, f"Inline finding {i}") for i in range(1000, 1101)]
        self.inline[0]["body"] = "@codex review"
        self.inline[1]["diff_hunk"] = "@@ -1 +1 @@\n-old\n+new"
        self.inline += [dict(self.comment(i, f"Reply {i}"), in_reply_to_id=1000)
                        for i in range(2000, 2205)]
        self.reviews = [
            dict(self.comment(5000, "## Codex Review Summary\nReview wrapper"), user={"login": BOT},
                 state="CHANGES_REQUESTED", commit_id="abc", submitted_at="2026-01-01T00:00:00Z"),
            dict(self.comment(5001, ""), state="APPROVED", commit_id="abc",
                 submitted_at="2026-01-01T00:00:00Z"),
        ]
        self.raw = {
            "number": 7, "title": "Fix behavior", "body": "PR description", "state": "open",
            "html_url": URL, "user": {"login": "author"}, "commits": 101,
            "changed_files": 101, "comments": len(self.issue), "review_comments": len(self.inline),
            "base": {"ref": "main", "sha": "base", "repo": {"full_name": "example/project"}},
            "head": {"ref": "feature", "sha": "abc", "repo": None},
        }

    @staticmethod
    def comment(number, body):
        return {"id": number, "body": body, "user": {"login": "reviewer"},
                "html_url": f"{URL}#comment-{number}", "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z"}

    def gh(self, *args, as_json=True):
        self.calls.append(args)
        if args[:2] == ("pr", "view"):
            return {"url": URL}
        if args[:2] == ("pr", "diff"):
            return "diff --git a/file b/file\n+fixed\n"
        if "graphql" in args:
            query = next(arg for arg in args if arg.startswith("query="))
            if "reviewThreads(first:100" in query:
                name = "reviewThreads"
                nodes = [{"id": f"thread-{i}", "isResolved": False, "isOutdated": False,
                          "path": "file.py", "line": 1,
                          "comments": {"nodes": [{"databaseId": i}]}}
                         for i in range(1000, 1101)]
            else:
                name = "commits"
                nodes = [{"commit": {"oid": f"sha-{i}", "message": "Fix", "committedDate": "date",
                                     "url": URL, "author": {"name": "Author", "user": None}}}
                         for i in range(101)]
            self.assert_paginated(args)
            return [{"data": {"repository": {"pullRequest": {
                "reviewDecision": "CHANGES_REQUESTED", "mergeStateStatus": "BLOCKED",
                name: {"nodes": nodes[i:i + 100], "totalCount": len(nodes),
                       "pageInfo": {"hasNextPage": i + 100 < len(nodes), "endCursor": str(i)}},
            }}}} for i in range(0, len(nodes), 100)]
        path = args[-1]
        if "--paginate" not in args:
            return copy.deepcopy(self.raw)
        self.assert_paginated(args)
        if "/issues/7/comments?" in path:
            items = self.issue
        elif "/issues/7/reactions?" in path:
            return [[{"id": 9010, "content": "+1", "user": {"login": "chatgpt-codex-connector[bot]"},
                      "created_at": "2026-01-01T00:00:01Z"}]]
        elif "/pulls/7/comments?" in path:
            items = self.inline
        elif "/reviews?" in path:
            items = self.reviews
        elif "/files?" in path:
            items = [{"filename": f"file-{i}.py", "status": "modified"} for i in range(101)]
        elif "/check-runs?" in path:
            return [{"total_count": 101, "check_runs": [{"id": i, "name": f"test-{i}", "conclusion": "success"}
                                    for i in range(start, min(start + 100, 101))]}
                    for start in (0, 100)]
        elif "/statuses?" in path:
            items = [{"id": i, "context": f"status-{i}", "state": "success"} for i in range(101)]
        else:
            raise AssertionError(path)
        return [items[i:i + 100] for i in range(0, len(items), 100)] or [[]]

    @staticmethod
    def assert_paginated(args):
        assert "--paginate" in args and "--slurp" in args
        if "graphql" not in args:
            assert "per_page=100" in args[-1]


class PrContextTests(unittest.TestCase):
    def test_all_feedback_pages_and_nested_replies_survive_filtering(self):
        fixture = Fixture()
        with patch.object(pr_context, "gh", side_effect=fixture.gh):
            output = pr_context.fetch_context(pr_context.GitHub(URL), include_diff=True)
        self.assertEqual(len(output["files"]), 101)
        self.assertEqual(len(output["commits"]), 101)
        self.assertEqual(len(output["threads"]), 101)
        self.assertEqual(len(output["checks"]), 101)
        self.assertEqual(len(output["statuses"]), 101)
        self.assertEqual(len([c for c in output["comments"] if c["kind"] == "issue"]), 103)
        self.assertIn(2204, {c["id"] for c in output["comments"]})
        root = output["threads"][0]
        self.assertEqual(root["root_comment_id"], 1000)
        self.assertEqual(len(root["comment_ids"]), 205)
        self.assertNotIn(1000, root["comment_ids"])
        self.assertEqual(output["reviews"][0]["state"], "CHANGES_REQUESTED")
        self.assertEqual(len(output["reviews"]), 2)
        self.assertEqual(output["filtering"]["removed_comments"], 4)
        self.assertIn("+fixed", output["diff"])

    def test_check_and_status_publishers_survive_context_selection(self):
        fixture = Fixture()
        original = fixture.gh
        def published(*args, **kwargs):
            result = original(*args, **kwargs)
            if '/check-runs?' in args[-1]:
                result[0]['check_runs'][0]['app'] = {'slug': 'github-actions'}
            elif '/statuses?' in args[-1]:
                result[0][0]['creator'] = {'login': 'github-actions[bot]'}
            return result
        with patch.object(pr_context, 'gh', side_effect=published):
            output = pr_context.fetch_context(pr_context.GitHub(URL))
        self.assertEqual(output['checks'][0]['app']['slug'], 'github-actions')
        self.assertTrue(any(s.get('creator', {}).get('login') == 'github-actions[bot]'
                            for s in output['statuses']))

    def test_default_thirty_item_pages_and_empty_pages_are_flattened(self):
        api = pr_context.GitHub(URL)
        for pages, expected in (([list(range(30)), [30]], 31), ([list(range(100)), []], 100), ([[]], 0)):
            with self.subTest(expected=expected), patch.object(pr_context, "gh", return_value=pages):
                self.assertEqual(len(api.pages("repos/example/project/issues/7/comments")), expected)

    def test_latest_comment_on_later_page_comes_first(self):
        fixture = Fixture()
        fixture.issue[-1]["updated_at"] = "2026-11-02T00:00:00Z"
        with patch.object(pr_context, "gh", side_effect=fixture.gh):
            output = pr_context.fetch_context(pr_context.GitHub(URL))
        self.assertEqual(output["comments"][0]["id"], 105)

    def test_codex_boilerplate_is_removed_before_whole_comment_filter(self):
        body = '''<!-- codex-review-receipt:v1 -->
### 💡 Codex Review
Useful finding.
<details> <summary>ℹ️ About Codex in GitHub</summary>
Reviews are triggered by "@codex review".
</details>
<details><summary>Reproduction</summary>Keep this.</details>'''
        filtered = codex(body)
        self.assertIn("Useful finding.", filtered)
        self.assertIn("Keep this.", filtered)
        self.assertNotIn("About Codex", filtered)
        self.assertNotIn("codex-review-receipt", filtered)
        self.assertIn("@codex review", codex(body + "\nRe-run with @codex review."))
        self.assertIsNone(codex("Useful preamble\n## Codex Review Summary\nSummary"))
        self.assertIsNone(codex("<!-- codex-pull-request-review-summary -->\nStatus table"))
        for example in ("Finding: `<!-- codex-review-receipt:v1 -->`",
                        "Finding:\n```html\n<!-- codex-review-receipt:v1 -->\n```"):
            with self.subTest(example=example):
                self.assertEqual(codex(example), example)

    def test_substantive_markdown_and_unrelated_details_are_unchanged(self):
        body = "Finding\n\n```python\nx = '''a\n\n\nb'''\n```\n<details>Keep @codex address that feedback</details>"
        self.assertEqual(codex(body), body)

    def test_nested_about_block_preserves_outer_feedback_and_balanced_tags(self):
        body = '''<details><summary>Important finding</summary>
Keep the reproduction before the quote.
<details><summary>Quoted review</summary>Keep quoted findings.
<details><summary>ℹ️ About Codex in GitHub</summary>
Noise with @codex review.
</details>Keep the quote suffix.</details>
Keep the finding suffix.</details>'''
        output = codex(body)
        for text in ("Important finding", "Keep the reproduction", "Keep quoted findings",
                     "Keep the quote suffix", "Keep the finding suffix"):
            self.assertIn(text, output)
        self.assertNotIn("About Codex", output)
        self.assertEqual(output.count("<details>"), 2)
        self.assertEqual(output.count("</details>"), 2)

    def test_multiple_nested_about_blocks_and_unclosed_blocks(self):
        body = ("<details><summary>ℹ️ About Codex in GitHub</summary>"
                "<details><summary>ℹ️ About Codex in GitHub</summary>Noise</details></details>"
                "Keep this.<details><summary>ℹ️ About Codex in GitHub</summary>Noise</details>"
                "<details><summary>ℹ️ About Codex in GitHub</summary>Unclosed")
        self.assertEqual(codex(body),
                         "Keep this.<details><summary>ℹ️ About Codex in GitHub</summary>Unclosed")

    def test_details_examples_in_markdown_code_survive_beside_real_boilerplate(self):
        example = "<details><summary>ℹ️ About Codex in GitHub</summary>Example</details>"
        samples = [f"`{example}`", f"``{example} ` literal tick``",
                   f"```html\n{example}\n```", f"~~~html\n{example}\n~~~",
                   f"````html\n```\n{example}\n````", f"> ```html\n> {example}\n> ```",
                   f"  ```html\n{example}\n  ```", f"- ```html\n  {example}\n  ```",
                   f"`first line\n{example}`", f"```html\n{example}"]
        real = "<details><summary>ℹ️ About Codex in GitHub</summary>Real boilerplate</details>"
        for sample in samples:
            with self.subTest(sample=sample):
                # Keep the real block before a possibly unclosed code fence.
                body = f"Useful finding.\n{real}\n\n{sample}"
                expected = f"Useful finding.\n\n\n{sample}"
                self.assertEqual(codex(body), expected)

    def test_literal_details_inside_code_cannot_unbalance_surrounding_html(self):
        body = ("<details><summary>Reproduction</summary>\n"
                "`</details><details>`\n"
                "<details><summary>ℹ️ About Codex in GitHub</summary>Noise</details>\n"
                "Keep this suffix.</details>")
        expected = body.replace("<details><summary>ℹ️ About Codex in GitHub</summary>Noise</details>", "")
        self.assertEqual(codex(body), expected)

    def test_indented_code_examples_survive_without_masking_real_html_summaries(self):
        example = "<details><summary>ℹ️ About Codex in GitHub</summary>Example</details>"
        for indent in ("    ", "\t"):
            body = f"Reproduction:\n\n{indent}{example}\n\n{indent}Keep code.\n\nExplanation."
            self.assertEqual(codex(body), body)
        raw = "<details>\n    <summary>ℹ️ About Codex in GitHub</summary>Noise\n</details>"
        self.assertEqual(codex("Finding.\n" + raw), "Finding.")

    def test_blockquoted_indented_examples_survive_blank_lines_and_nested_quotes(self):
        example = "<details><summary>ℹ️ About Codex in GitHub</summary>Example</details>"
        for quote in ("> ", ">> ", "> > "):
            for indent in ("    ", "\t"):
                body = (f"{quote}Reproduction:\n{quote}\n{quote}{indent}{example}\n"
                        f"{quote}\n{quote}{indent}Keep code.\n{quote}\n{quote}Explanation.")
                self.assertEqual(codex(body), body.strip())

    def test_only_exact_triggers_and_codex_summaries_are_dropped(self):
        for author in (BOT, "reviewer", None):
            with self.subTest(author=author):
                self.assertIsNone(pr_context.filter_body("  @codex review\n", author))
        for body in ("Run `@codex review`", "Example:\n```text\n@codex review\n```",
                     "Example:\n\n    ## Codex Review Summary", "The `## Codex Review Summary` check"):
            with self.subTest(body=body):
                self.assertEqual(codex(body), body)

    def test_human_comments_are_never_dropped_or_rewritten(self):
        about = "<details><summary>ℹ️ About Codex in GitHub</summary>Quoted</details>"
        for body in ("Blocking: auth check removed. Fix it, then @codex review again.",
                     "Please post `@codex review` as a standalone comment.",
                     "## Codex Review Summary\nThe bot's summary is wrong about X.",
                     f"Quoted bot output:\n{about}\n<!-- codex-review-receipt:v1 -->"):
            with self.subTest(body=body):
                self.assertEqual(pr_context.filter_body(body, "reviewer"), body)

    def test_diff_hunks_are_opt_in(self):
        for include_hunks in (False, True):
            fixture = Fixture()
            with self.subTest(include_hunks=include_hunks), \
                    patch.object(pr_context, "gh", side_effect=fixture.gh):
                output = pr_context.fetch_context(pr_context.GitHub(URL), include_hunks=include_hunks)
                hunks = [c["diff_hunk"] for c in output["comments"] if "diff_hunk" in c]
                self.assertEqual(hunks, ["@@ -1 +1 @@\n-old\n+new"] if include_hunks else [])

    def test_output_file_is_written_only_after_a_complete_fetch(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "context.json"
            fixture = Fixture()
            stdout, stderr = io.StringIO(), io.StringIO()
            with patch.object(pr_context, "gh", side_effect=fixture.gh), \
                    contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                self.assertEqual(pr_context.main([URL, "--output", str(target)]), 0)
            self.assertEqual(stdout.getvalue(), "")
            self.assertEqual(json.loads(target.read_text())["pr"]["number"], 7)
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            fixture.raw["changed_files"] = 3001
            with patch.object(pr_context, "gh", side_effect=fixture.gh), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(pr_context.main([URL, "--output", str(target)]), 1)
            self.assertEqual(json.loads(target.read_text())["pr"]["number"], 7)
            self.assertEqual(sorted(p.name for p in Path(folder).iterdir()), ["context.json"])

    def test_output_never_writes_through_a_planted_temporary_path(self):
        with tempfile.TemporaryDirectory() as folder:
            victim = Path(folder) / "victim.txt"
            victim.write_text("keep")
            target = Path(folder) / "context.json"
            # The previous predictable name; the helper must not follow it.
            planted = Path(folder) / f".context.json.{pr_context.os.getpid()}.tmp"
            planted.symlink_to(victim)
            with patch.object(pr_context, "gh", side_effect=Fixture().gh), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(pr_context.main([URL, "--output", str(target)]), 0)
            self.assertEqual(victim.read_text(), "keep")
            self.assertTrue(planted.is_symlink())
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)

    def test_code_only_comment_keeps_significant_indentation_and_trailing_spaces(self):
        example = "<details><summary>ℹ️ About Codex in GitHub</summary>Example</details>"
        for indent in ("    ", "\t"):
            body = f"{indent}{example}\n{indent}code  "
            self.assertEqual(codex(body), body)

    def test_check_run_total_and_endpoint_cap_cannot_silently_truncate(self):
        api = pr_context.GitHub(URL)
        for total, size in ((1001, 1000), (1000, 1000), (5, 4)):
            pages = [{"total_count": total, "check_runs": [{"id": i} for i in range(size)]}]
            with self.subTest(total=total, size=size), patch.object(pr_context, "gh", return_value=pages):
                with self.assertRaises(pr_context.FetchError):
                    api.pages("repos/example/project/commits/abc/check-runs", "check_runs")
        with patch.object(pr_context, "gh", return_value=[{"total_count": 0, "check_runs": []}]):
            self.assertEqual(api.pages("example/check-runs", "check_runs"), [])

    def test_no_filter_retains_original_bodies_and_excluded_comments(self):
        fixture = Fixture()
        with patch.object(pr_context, "gh", side_effect=fixture.gh):
            output = pr_context.fetch_context(pr_context.GitHub(URL), no_filter=True)
        self.assertEqual(output["filtering"]["removed_comments"], 0)
        self.assertFalse(output["filtering"]["enabled"])
        self.assertIn("@codex review", {c["body"] for c in output["comments"]})

    def test_changed_head_or_base_does_not_emit_a_successful_snapshot(self):
        for ref in ("head", "base"):
            fixture = Fixture()
            original = fixture.gh
            reads = 0

            def changed(*args, **kwargs):
                nonlocal reads
                value = original(*args, **kwargs)
                if args[0] == "api" and args[-1] == "repos/example/project/pulls/7":
                    reads += 1
                    if reads == 2:
                        value[ref]["sha"] = "new-commit"
                return value

            with self.subTest(ref=ref), patch.object(pr_context, "gh", side_effect=changed):
                stdout, stderr = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    self.assertEqual(pr_context.main([URL]), 1)
                self.assertEqual(stdout.getvalue(), "")
                self.assertIn("changed during the fetch", stderr.getvalue())

    def test_api_file_limit_fails_instead_of_silently_truncating(self):
        fixture = Fixture()
        fixture.raw["changed_files"] = 3001
        with patch.object(pr_context, "gh", side_effect=fixture.gh):
            with self.assertRaisesRegex(pr_context.FetchError, "exceed API limits"):
                pr_context.fetch_context(pr_context.GitHub(URL))

    def test_feedback_counts_and_incomplete_graphql_pages_fail(self):
        fixture = Fixture()
        fixture.raw["comments"] += 1
        with patch.object(pr_context, "gh", side_effect=fixture.gh):
            with self.assertRaisesRegex(pr_context.FetchError, "feedback counts changed"):
                pr_context.fetch_context(pr_context.GitHub(URL))
        for pages in ([], [{"errors": [{"message": "private-response-sentinel"}]}],
                      [{"data": {"repository": {"pullRequest": {
                          "commits": {"totalCount": 2, "nodes": []},
                      }}}}]):
            with self.subTest(pages=pages), patch.object(pr_context, "gh", return_value=pages):
                with self.assertRaises(pr_context.FetchError):
                    pr_context.GitHub(URL).connection("commits", "commit { oid }")

    def test_body_only_new_review_or_changed_decision_invalidates_snapshot(self):
        for change in ("new", "state", "body"):
            fixture = Fixture()
            original = fixture.gh
            reads = 0

            def changed(*args, **kwargs):
                nonlocal reads
                value = copy.deepcopy(original(*args, **kwargs))
                if args[-1].endswith('/reviews?per_page=100'):
                    reads += 1
                    if reads == 2:
                        if change == "new":
                            value[0].append(dict(fixture.comment(5002, "New body-only finding"),
                                                 state="CHANGES_REQUESTED", commit_id="abc"))
                        elif change == "state":
                            value[0][0]["state"] = "DISMISSED"
                        else:
                            value[0][0]["body"] = "Updated review finding"
                return value

            with self.subTest(change=change), patch.object(pr_context, "gh", side_effect=changed):
                with self.assertRaisesRegex(pr_context.FetchError, "Submitted PR reviews changed"):
                    pr_context.fetch_context(pr_context.GitHub(URL))

    def test_edited_issue_or_inline_body_invalidates_snapshot_without_count_change(self):
        for endpoint in ("/issues/7/comments?per_page=100", "/pulls/7/comments?per_page=100"):
            fixture = Fixture()
            original = fixture.gh
            reads = 0

            def changed(*args, **kwargs):
                nonlocal reads
                value = copy.deepcopy(original(*args, **kwargs))
                if args[-1].endswith(endpoint):
                    reads += 1
                    if reads == 2:
                        value[0][0]["body"] = "Corrected finding"
                        value[0][0]["updated_at"] = "2026-11-03T00:00:00Z"
                return value

            with self.subTest(endpoint=endpoint), patch.object(pr_context, "gh", side_effect=changed):
                with self.assertRaisesRegex(pr_context.FetchError, "PR comment text changed"):
                    pr_context.fetch_context(pr_context.GitHub(URL))

    @staticmethod
    def state(sha, status="completed"):
        code = {"commit_sha": sha, "has_any_findings": False, "status": status}
        return f"<!-- codex-review-state:v1 {json.dumps({'code_review': code})} -->"

    def test_codex_review_state_survives_filtered_summary(self):
        fixture = Fixture()
        fixture.issue[1]["body"] = f"<!-- codex-pull-request-review-summary -->\n{self.state('abc')}\n## Codex Review Summary"
        with patch.object(pr_context, "gh", side_effect=fixture.gh):
            output = pr_context.fetch_context(pr_context.GitHub(URL))
        visible = {c["id"] for c in output["comments"] if c["kind"] == "issue"}
        self.assertFalse({1, 2} & visible)
        self.assertEqual(output["codex_review"]["comment_id"], 2)
        self.assertEqual(output["codex_review"]["state"]["code_review"]["commit_sha"], "abc")
        self.assertTrue(output["codex_review"]["covers_head"])
        self.assertNotIn("review_requests", output)
        self.assertEqual(output["pr_reactions"][0]["author"], BOT)
        self.assertEqual(output["pr_reactions"][0]["content"], "+1")

    def test_codex_review_covers_only_a_completed_review_of_the_head(self):
        def comment(number, body, author=BOT, updated="2026-01-01T00:00:00Z"):
            return {"id": number, "body": body, "user": {"login": author},
                    "html_url": f"{URL}#issuecomment-{number}", "updated_at": updated}

        self.assertIsNone(pr_context.codex_review([comment(1, "No state")], "abc"))
        for body in (self.state("old"), self.state("abc", "in_progress")):
            with self.subTest(body=body):
                self.assertFalse(pr_context.codex_review([comment(1, body)], "abc")["covers_head"])
        # Only Codex's own marker counts, never one quoted by people or in code examples.
        for quoted in (comment(1, self.state("abc"), "reviewer"),
                       comment(1, f"Example:\n```html\n{self.state('abc')}\n```"),
                       comment(1, f"Example: `{self.state('abc')}`")):
            with self.subTest(quoted=quoted["body"]):
                self.assertIsNone(pr_context.codex_review([quoted], "abc"))
        newest = pr_context.codex_review([
            comment(1, self.state("abc"), updated="2026-01-01T00:00:02Z"),
            comment(2, self.state("old"), updated="2026-01-01T00:00:01Z"),
        ], "abc")
        self.assertEqual((newest["comment_id"], newest["covers_head"]), (1, True))
        broken = pr_context.codex_review([comment(1, "<!-- codex-review-state:v1 {oops} -->")], "abc")
        self.assertEqual((broken["state"], broken["covers_head"]), (None, False))

    def test_codex_review_reports_clean_result_from_edited_summary(self):
        body = (self.state("abc") + '\n| Code Review | Completed <relative-time datetime="2026-01-02T00:00:05Z">'
                "</relative-time> |")
        summary = {"id": 7, "body": body, "user": {"login": BOT}, "html_url": f"{URL}#issuecomment-7",
                   "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-02T00:00:06Z"}
        clean = pr_context.codex_review([summary], "abc")
        self.assertEqual((clean["outcome"], clean["edited_in_place"], clean["completed_at"]),
                         ("clean", True, "2026-01-02T00:00:05Z"))
        self.assertIn("no new findings", clean["summary"])
        self.assertIn("created 2026-01-01T00:00:00Z", clean["summary"])
        self.assertIn("codex-clean-review-note:v1 abc", clean["clean_note"])
        self.assertNotIn("@", clean["clean_note"].replace(URL, ""))
        # An existing note for the head suppresses another one.
        note = {"id": 8, "body": clean["clean_note"], "user": {"login": "agent"}}
        noted = pr_context.codex_review([summary, note], "abc")
        self.assertTrue(noted["clean_note_posted"])
        self.assertNotIn("clean_note", noted)
        # A quoted or code-formatted marker is discussion, not a posted note.
        marker = "<!-- codex-clean-review-note:v1 abc -->"
        for body in (f"Draft: `{marker}`", f"```\n{marker}\n```", f"    {marker}", f"See {marker}"):
            with self.subTest(body=body):
                quoted = {"id": 8, "body": body, "user": {"login": "agent"}}
                self.assertFalse(pr_context.codex_review([summary, quoted], "abc")["clean_note_posted"])

        def review(number, submitted, sha="abc"):
            return {"id": number, "user": {"login": BOT}, "commit_id": sha, "submitted_at": submitted}

        finding = {"id": 9, "user": {"login": BOT}, "pull_request_review_id": 50}
        reply = {"id": 10, "user": {"login": BOT}, "pull_request_review_id": 50, "in_reply_to_id": 9}
        # A Codex review submitted during this run means findings, never clean.
        found = pr_context.codex_review([summary], "abc", [finding, reply],
                                        [review(50, "2026-01-02T00:00:03Z")])
        self.assertEqual((found["outcome"], found["findings_on_reviewed_commit"]), ("findings", 1))
        self.assertNotIn("clean_note", found)
        # Its comments may be deleted; the review object still marks findings.
        deleted = pr_context.codex_review([summary], "abc", [], [review(50, "2026-01-02T00:00:03Z")])
        self.assertEqual((deleted["outcome"], deleted["findings_on_reviewed_commit"]), ("findings", 0))
        # A same-commit review before the run window may be an earlier run or a delayed
        # one: never call that clean, and post no note.
        for earlier in ("2026-01-01T00:00:00Z", "2026-01-01T23:55:05Z"):
            with self.subTest(earlier=earlier):
                rerun = pr_context.codex_review([summary], "abc", [finding], [review(50, earlier)])
                self.assertEqual(rerun["outcome"], "ambiguous")
                self.assertNotIn("clean_note", rerun)
                self.assertIn("unconfirmed", rerun["summary"])
        # A review inside the window wins over an earlier one.
        both = pr_context.codex_review([summary], "abc", [finding], [
            review(49, "2026-01-01T00:00:00Z"), review(50, "2026-01-02T00:00:03Z")])
        self.assertEqual(both["outcome"], "findings")
        # Reviews submitted after completion belong to a later run.
        later = pr_context.codex_review([summary], "abc", [finding], [review(50, "2026-01-02T00:10:00Z")])
        self.assertEqual(later["outcome"], "clean")
        # Reviews of other commits or from people are ignored.
        other = pr_context.codex_review([summary], "abc", [finding], [
            review(50, "2026-01-02T00:00:03Z", "old"),
            {**review(51, "2026-01-02T00:00:03Z"), "user": {"login": "reviewer"}}])
        self.assertEqual(other["outcome"], "clean")
        # A clean review of an older commit says it does not cover the head.
        stale = pr_context.codex_review([summary], "def")
        self.assertIn("does not cover the current head def", stale["summary"])
        self.assertNotIn("clean_note", stale)

    def test_resolved_or_outdated_thread_changes_invalidate_snapshot(self):
        for key in ("isResolved", "isOutdated", "id"):
            fixture = Fixture()
            original = fixture.gh
            reads = 0

            def changed(*args, **kwargs):
                nonlocal reads
                value = copy.deepcopy(original(*args, **kwargs))
                if "graphql" in args and any("reviewThreads(first:100" in a for a in args):
                    reads += 1
                    if reads == 2:
                        node = value[0]["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"][0]
                        node[key] = "new-id" if key == "id" else True
                return value

            with self.subTest(key=key), patch.object(pr_context, "gh", side_effect=changed):
                with self.assertRaisesRegex(pr_context.FetchError, "PR review threads changed"):
                    pr_context.fetch_context(pr_context.GitHub(URL))

    def test_statuses_keep_only_each_contexts_newest_state(self):
        fixture = Fixture()
        original = fixture.gh

        def history(*args, **kwargs):
            value = original(*args, **kwargs)
            if args[-1].endswith("/statuses?per_page=100"):
                value[-1] = value[-1] + [
                    {"id": 900, "context": "deploy", "state": "pending", "updated_at": "2026-01-01T00:00:00Z"},
                    {"id": 902, "context": "deploy", "state": "success", "updated_at": "2026-01-01T00:02:00Z"},
                    {"id": 901, "context": "deploy", "state": "failure", "updated_at": "2026-01-01T00:01:00Z"},
                ]
            return value

        with patch.object(pr_context, "gh", side_effect=history):
            output = pr_context.fetch_context(pr_context.GitHub(URL))
        deploy = [s for s in output["statuses"] if s["context"] == "deploy"]
        self.assertEqual([(s["id"], s["state"]) for s in deploy], [(902, "success")])
        self.assertEqual(len(output["statuses"]), 102)

    def test_status_history_at_the_api_limit_fails(self):
        fixture = Fixture()
        original = fixture.gh

        def capped(*args, **kwargs):
            value = original(*args, **kwargs)
            if args[-1].endswith("/statuses?per_page=100"):
                return [[{"id": i, "context": "noisy", "state": "pending"} for i in range(p, p + 100)]
                        for p in range(0, 1000, 100)]
            return value

        with patch.object(pr_context, "gh", side_effect=capped):
            with self.assertRaisesRegex(pr_context.FetchError, "Commit-status API limit"):
                pr_context.fetch_context(pr_context.GitHub(URL))

    def test_enterprise_host_keeps_custom_port(self):
        self.assertEqual(pr_context.GitHub("https://github.example.com:8443/org/repo/pull/7").host,
                         "github.example.com:8443")
        self.assertEqual(pr_context.GitHub(URL).host, "github.com")
        with self.assertRaises(pr_context.FetchError):
            pr_context.GitHub("https://github.example.com:99999/org/repo/pull/7")

    def test_pr_reaction_changes_invalidate_snapshot(self):
        fixture = Fixture()
        original = fixture.gh
        reads = 0

        def changed(*args, **kwargs):
            nonlocal reads
            value = copy.deepcopy(original(*args, **kwargs))
            if args[-1].endswith("/issues/7/reactions?per_page=100"):
                reads += 1
                if reads == 2:
                    value[0] = []
            return value

        with patch.object(pr_context, "gh", side_effect=changed):
            with self.assertRaisesRegex(pr_context.FetchError, "PR reactions changed"):
                pr_context.fetch_context(pr_context.GitHub(URL))

    def test_partial_failure_has_no_stdout_and_does_not_echo_response_body(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        result = subprocess.CompletedProcess([], 1, stdout='{"partial":true}',
                                             stderr="HTTP 403 private-response-sentinel")
        with patch.object(pr_context.subprocess, "run", return_value=result):
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                self.assertEqual(pr_context.main([URL]), 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("HTTP 403", stderr.getvalue())
        self.assertNotIn("private-response-sentinel", stderr.getvalue())

    def test_transport_uses_argument_array_and_disables_debug(self):
        result = subprocess.CompletedProcess([], 0, stdout="[]", stderr="")
        with patch.object(pr_context.subprocess, "run", return_value=result) as run:
            self.assertEqual(pr_context.gh("api", "example"), [])
        args, kwargs = run.call_args
        self.assertEqual(args[0], ["gh", "api", "example"])
        self.assertEqual(kwargs["env"]["GH_DEBUG"], "")
        self.assertNotIn("shell", kwargs)

    def test_enterprise_host_is_explicit_and_symlinks_share_one_source(self):
        api = pr_context.GitHub("https://github.example.com/team/repo/pull/42")
        with patch.object(pr_context, "gh", return_value={}) as gh:
            api.api(api.pull)
        self.assertIn("github.example.com", gh.call_args.args)
        for skill in ("git-management", "pr-management"):
            script = ROOT / f"skills/{skill}/scripts/pr-context.py"
            self.assertTrue(script.is_symlink())
            self.assertEqual(script.resolve(), ROOT / "scripts/pr-context.py")


if __name__ == "__main__":
    unittest.main()
