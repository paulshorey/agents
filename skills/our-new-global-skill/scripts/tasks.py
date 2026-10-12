#!/usr/bin/env python3
"""Track one project's native Codex tasks; emit tool arguments without launching agents."""
import argparse
import json
import os
import sqlite3
import subprocess
import sys
from task_state import Project, state, verify_repository, connection, begin, end, prepare_task, claim_task, bind_project, dispatch_plan, attach_task, start_task, observe_task, DEFAULT_CODING_MODEL, DEFAULT_CODING_REASONING


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cwd',required=True)
    parser.add_argument('--repository',help='Expected reviewed GitHub owner/repository')
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('doctor');sub.add_parser('tasks')
    b=sub.add_parser('begin');b.add_argument('--thread',default=os.environ.get('CODEX_THREAD_ID'))
    e=sub.add_parser('end');e.add_argument('--pass-id',required=True);e.add_argument('--evidence',required=True);e.add_argument('--recovered',action='store_true')
    bind=sub.add_parser('bind');bind.add_argument('--project-id',required=True)
    prepare=sub.add_parser('task-prepare')
    for name in ('scope','base','prompt','authority','acceptance'):prepare.add_argument('--'+name,required=True)
    claim=sub.add_parser('task-claim');claim.add_argument('--task',required=True);claim.add_argument('--pass-id',required=True)
    plan=sub.add_parser('dispatch-plan');plan.add_argument('--task',required=True)
    attach=sub.add_parser('task-attach');attach.add_argument('--task',required=True);attach.add_argument('--thread',required=True);attach.add_argument('--host',default='local')
    start=sub.add_parser('task-start');start.add_argument('--task',required=True);start.add_argument('--actual-cwd',required=True);start.add_argument('--thread',default=os.environ.get('CODEX_THREAD_ID'))
    observe=sub.add_parser('task-observe');observe.add_argument('--task',required=True);observe.add_argument('--status',required=True);observe.add_argument('--evidence',required=True);observe.add_argument('--close',action='store_true')
    args=parser.parse_args();context=Project(args.cwd,args.repository)
    if args.command=='doctor':
        result={'checkout':verify_repository(context),'state':str(state(context)),
                'coding_preference':{'model':DEFAULT_CODING_MODEL,'reasoning':DEFAULT_CODING_REASONING},
                'native_thread':os.environ.get('CODEX_THREAD_ID'),
                'desktop_bridge_hint':bool(os.environ.get('CODEX_APP_TOOLS_PIPE_PATH'))}
    elif args.command=='begin':result=begin(context,args.thread)
    elif args.command=='end':
        end(context,args.pass_id,args.evidence,args.recovered);result={'status':'released','pass_id':args.pass_id}
    elif args.command=='bind':
        bind_project(context,args.project_id);result={'status':'bound','project_id':args.project_id}
    elif args.command=='task-prepare':result=prepare_task(context,args.scope,args.base,args.prompt,args.authority,args.acceptance)
    elif args.command=='task-claim':result=claim_task(context,args.task,args.pass_id)
    elif args.command=='dispatch-plan':result=dispatch_plan(context,args.task)
    elif args.command=='task-attach':result=attach_task(context,args.task,args.thread,args.host)
    elif args.command=='task-start':result=start_task(context,args.task,args.actual_cwd,args.thread)
    elif args.command=='task-observe':result=observe_task(context,args.task,args.status,args.evidence,args.close)
    else:
        db=connection(context)
        try:result={'tasks':[dict(r) for r in db.execute('SELECT * FROM tasks ORDER BY created_at DESC')],
                    'active_passes':[dict(r) for r in db.execute("SELECT * FROM passes WHERE state='active'")]}
        finally:db.close()
    print(json.dumps(result,indent=2));return 3 if result.get('status')=='blocked' else 0

if __name__=='__main__':
    os.umask(0o077)
    try:raise SystemExit(main())
    except (ValueError,OSError,sqlite3.Error,subprocess.TimeoutExpired) as exc:
        print(f'Blocked: {exc}',file=sys.stderr);raise SystemExit(78)
