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
    for check in context.get('checks', []):
        if check.get('status') != 'completed':
            reasons.append(f"check {check.get('name')} is {check.get('status')}")
        elif check.get('conclusion') not in GOOD_CHECKS:
            reasons.append(f"check {check.get('name')} {check.get('conclusion')}")
    for status in context.get('statuses', []):
        if status.get('context') != CONTEXT and status.get('state') != 'success':
            reasons.append(f"status {status.get('context')} is {status.get('state')}")
    return reasons


def recheck(api, context):
    """Reread the head, checks and statuses just before posting success: the
    snapshot reads them partway through a longer fetch."""
    head = context['pr']['head']['sha']
    if api.api(api.pull)['head']['sha'] != head:
        return ['the PR head changed']
    reasons = []
    for check in api.pages(f'{api.prefix}/commits/{head}/check-runs?filter=latest', 'check_runs'):
        if check.get('status') != 'completed' or check.get('conclusion') not in GOOD_CHECKS:
            reasons.append(f"check {check.get('name')} is {check.get('conclusion') or check.get('status')}")
    latest = {}
    for status in sorted(api.pages(f'{api.prefix}/commits/{head}/statuses'),
                         key=lambda s: (s.get('updated_at') or '', s.get('id') or 0)):
        latest[status.get('context')] = status.get('state')
    reasons += [f'status {name} is {state}' for name, state in latest.items()
                if name != CONTEXT and state != 'success']
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
