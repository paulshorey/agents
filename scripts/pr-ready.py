#!/usr/bin/env python3
"""Show the developer whether an agent is still working on a PR.

Sets the `agent/ready` commit status on the PR's current head, which GitHub shows
in the PR's checks and which branch protection can require before merging:

  working PR "what"   pending: an agent is changing the PR or waiting for review
  blocked PR "what"   failure: the agent needs the developer's decision
  ready PR            success, only after verifying that the PR is open, Codex's
                      review of the head is clean, no thread is unresolved, other
                      checks pass and there are no conflicts; otherwise pending
                      with the first unmet condition (exit 1)
  status PR           print the current agent/ready status of the head

A new push creates a new head without this status, so the PR stops looking ready
until an agent verifies it again.
"""

import argparse
import importlib.util
import json
from pathlib import Path
import sys

CONTEXT = 'agent/ready'
SCRIPT = Path(__file__).resolve().parent / 'pr-context.py'
GOOD_CHECKS = {'success', 'neutral', 'skipped'}
COMPLETION_GATE = 'PR checks finished'
COMPLETION_OBSERVER = 'Observe PR check completion'
COMPLETION_WORKFLOW = '.github/workflows/pr-check-completion.yml'


def _context_module():
    spec = importlib.util.spec_from_file_location('pr_context', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pr_context = _context_module()


def readiness(context):
    """Return the unmet conditions (empty when the PR is ready) for a pr-context snapshot."""
    pr, head = context['pr'], context['pr']['head']['sha']
    reasons = []
    if pr.get('state') != 'open' or pr.get('merged'):
        reasons.append('PR is not open')
    if pr.get('draft'):
        reasons.append('PR is a draft')
    if pr.get('mergeable') is None:
        reasons.append('GitHub is still computing mergeability')
    elif pr.get('mergeable') is not True or pr.get('mergeable_state') == 'dirty':
        reasons.append('merge conflicts with the base branch')
    if pr.get('reviewDecision') == 'CHANGES_REQUESTED':
        reasons.append('a reviewer requested changes')
    review = context.get('codex_review') or {}
    if not review.get('covers_head'):
        reasons.append(f'waiting for Codex review of {head[:7]}')
    elif review.get('outcome') != 'clean':
        reasons.append(f"Codex review of {head[:7]} is {review.get('outcome')}")
    open_threads = sum(1 for thread in context.get('threads', []) if not thread.get('isResolved'))
    if open_threads:
        reasons.append(f'{open_threads} unresolved review thread(s)')
    reasons += check_reasons(context.get('checks', []), context.get('statuses', []))
    return reasons


def has_completion_gate(statuses):
    return any(status.get('context') == COMPLETION_GATE
               and (status.get('creator') or {}).get('login') == 'github-actions[bot]'
               for status in statuses)


def is_completion_observer(check):
    return (check.get('name') == COMPLETION_OBSERVER
            and (check.get('app') or {}).get('slug') == 'github-actions')


def check_reasons(checks, statuses, completion_gate=None):
    if completion_gate is None:
        completion_gate = has_completion_gate(statuses)
    reasons = []
    for check in checks:
        # The observer summarizes other checks and can fail while inspecting
        # another PR. Its result is not an application quality check.
        if completion_gate and is_completion_observer(check):
            continue
        if check.get('status') != 'completed':
            reasons.append(f"check {check.get('name')} is {check.get('status')}")
        elif check.get('conclusion') not in GOOD_CHECKS:
            reasons.append(f"check {check.get('name')} {check.get('conclusion')}")
    for status in statuses:
        if status.get('context') == CONTEXT:
            continue
        # This derived completion signal may itself be waiting for agent/ready.
        # recheck independently validates head AND test-merge checks/workflows.
        if (completion_gate and status.get('context') == COMPLETION_GATE
                and (status.get('creator') or {}).get('login') == 'github-actions[bot]'):
            continue
        if status.get('state') != 'success':
            reasons.append(f"status {status.get('context')} is {status.get('state')}")
    return reasons


def latest_statuses(api, ref):
    history = api.pages(f'{api.prefix}/commits/{ref}/statuses')
    if len(history) >= 1000:
        raise pr_context.FetchError('Commit-status API limit reached; cannot verify readiness.')
    latest = {}
    for status in sorted(history,
                         key=lambda s: (s.get('updated_at') or s.get('created_at') or '',
                                        s.get('id') or 0), reverse=True):
        latest.setdefault(status.get('context'), status)
    return list(latest.values())


def latest_workflows(runs):
    """Keep the latest execution per workflow/event, plus every active run."""
    latest, selected = set(), []
    for run in sorted(runs, key=lambda r: (r.get('created_at') or '', r.get('id') or 0,
                                          r.get('run_attempt') or 0), reverse=True):
        identity = (run.get('workflow_id') or run.get('path') or run.get('id') or id(run),
                    run.get('event'))
        if identity not in latest or run.get('status') != 'completed':
            selected.append(run)
        latest.add(identity)
    return selected


def same_tested_tree(api, head, merge, base):
    """Head CI also covers a merge with verified parents and identical contents."""
    head_commit = api.api(f'{api.prefix}/git/commits/{head}')
    merge_commit = api.api(f'{api.prefix}/git/commits/{merge}')
    tree = (head_commit.get('tree') or {}).get('sha')
    return (head_commit.get('sha') == head and merge_commit.get('sha') == merge
            and bool(tree) and tree == (merge_commit.get('tree') or {}).get('sha')
            and {head, base} <= {parent['sha'] for parent in merge_commit.get('parents', [])})


def recheck(api, context):
    """Verify raw quality signals, independent of derived completion observers."""
    head = context['pr']['head']['sha']
    pull = api.api(api.pull)
    if pull['head']['sha'] != head or pull.get('state') != 'open':
        return ['the PR head changed or the PR is no longer open']
    statuses = latest_statuses(api, head)
    completion_gate = has_completion_gate(statuses)
    merge = pull.get('merge_commit_sha')
    base = (pull.get('base') or {}).get('sha')
    if completion_gate and not merge:
        return ['waiting for the test-merge revision to verify completion inputs']
    refs = list(dict.fromkeys([head, merge] if completion_gate else [head]))
    reasons = []
    for ref in refs:
        checks = api.pages(f'{api.prefix}/commits/{ref}/check-runs?filter=latest', 'check_runs')
        ref_statuses = statuses if ref == head else latest_statuses(api, ref)
        reasons += check_reasons(checks, ref_statuses, completion_gate)
        if completion_gate:
            runs = [run for run in api.pages(f'{api.prefix}/actions/runs?head_sha={ref}', 'workflow_runs')
                    if (run.get('path') or '').split('@')[0] != COMPLETION_WORKFLOW]
            merge_signals = (runs or any(not is_completion_observer(check) for check in checks)
                             or any(status.get('context') not in {CONTEXT, COMPLETION_GATE}
                                    for status in ref_statuses))
            if ref == merge and not merge_signals and not same_tested_tree(api, head, merge, base):
                reasons.append('waiting for test-merge quality signals or verified identical tested contents')
            for run in latest_workflows(runs):
                if run.get('status') != 'completed' or run.get('conclusion') not in GOOD_CHECKS:
                    reasons.append(f"workflow {run.get('name')} is {run.get('conclusion') or run.get('status')}")
    current = api.api(api.pull)
    if current['head']['sha'] != head or current.get('state') != 'open':
        reasons.append('the PR head changed or the PR is no longer open')
    if completion_gate and (current.get('merge_commit_sha') != merge
                            or (current.get('base') or {}).get('sha') != base):
        reasons.append('the test-merge revision changed')
    return reasons


def describe(text):
    """GitHub limits a status description to 140 characters."""
    text = ' '.join(text.split())
    return text if len(text) <= 140 else text[:139] + '…'


def set_status(api, sha, state, description, url):
    return pr_context.gh(
        'api', '--hostname', api.host, '-X', 'POST', f'{api.prefix}/statuses/{sha}',
        '-f', f'state={state}', '-f', f'context={CONTEXT}',
        '-f', f'description={describe(description)}', '-f', f'target_url={url}')


def resolve(pr, repo=None):
    args = ['pr', 'view'] + ([pr] if pr else []) + (['--repo', repo] if repo else [])
    return pr_context.GitHub(pr_context.gh(*args, '--json', 'url')['url'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('action', choices=('working', 'blocked', 'ready', 'status'))
    parser.add_argument('pr', help='PR URL, number, or branch')
    parser.add_argument('message', nargs='?', default='', help='what the agent is doing or needs (working/blocked)')
    parser.add_argument('--repo', '-R', help='[HOST/]OWNER/REPO; otherwise the current Git repository')
    parser.add_argument('--note', default='', help='appended to the ready description, e.g. "182 tests pass"')
    args = parser.parse_args(argv)
    if args.action in ('working', 'blocked') and not args.message.strip():
        parser.error(f'{args.action} needs a message saying what the agent is doing or needs')
    try:
        api = resolve(args.pr, args.repo)
        if args.action == 'status':
            pull = api.api(api.pull)
            statuses = api.pages(f"{api.prefix}/commits/{pull['head']['sha']}/statuses")
            mine = [s for s in statuses if s.get('context') == CONTEXT]
            latest = max(mine, key=lambda s: (s.get('updated_at') or '', s.get('id') or 0)) if mine else None
            print(json.dumps({'head': pull['head']['sha'], 'state': latest and latest['state'],
                              'description': latest and latest.get('description')}))
            return 0
        if args.action == 'ready':
            context = pr_context.fetch_context(api)
            sha, url = context['pr']['head']['sha'], context['pr']['url']
            reasons = readiness(context) or recheck(api, context)
            if reasons:
                if 'PR is not open' not in reasons:
                    set_status(api, sha, 'pending', 'Not ready: ' + '; '.join(reasons), url)
                print('pr-ready: not ready: ' + '; '.join(reasons), file=sys.stderr)
                return 1
            note = f'; {args.note}' if args.note.strip() else ''
            base = context['pr']['base']['sha'][:7]
            set_status(api, sha, 'success', f'Ready to merge: Codex clean on {sha[:7]} (base {base}){note}', url)
            print(f'pr-ready: {sha[:7]} marked ready to merge')
            return 0
        pull = api.api(api.pull)
        if pull.get('state') != 'open':
            print('pr-ready: PR is not open; nothing to mark', file=sys.stderr)
            return 1
        sha, url = pull['head']['sha'], pull['html_url']
        if args.action == 'working':
            set_status(api, sha, 'pending', 'Agent working: ' + args.message, url)
        else:
            set_status(api, sha, 'failure', 'Needs your decision: ' + args.message, url)
        print(f'pr-ready: {sha[:7]} marked {args.action}')
        return 0
    except pr_context.FetchError as exc:
        message = str(exc)
        if args.action != 'status' and ('HTTP 403' in message or 'HTTP 404' in message):
            # Statuses need push access to the base repository (e.g. a fork PR).
            print(f'pr-ready: cannot set {CONTEXT} here ({message}); report readiness in the PR '
                  'conversation instead', file=sys.stderr)
            return 3
        print(f'pr-ready: {message}', file=sys.stderr)
        return 1
    except (KeyError, TypeError, IndexError):
        print('pr-ready: Unexpected GitHub response.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
