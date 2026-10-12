#!/usr/bin/env python3
"""Read paginated open GitHub work for the selected checkout, across all authors."""
import argparse
import json
import subprocess
import sys
from task_state import Project, verify_repository


def read(repository,resource):
    reply=subprocess.run(['gh','api','--paginate','--slurp',f'repos/{repository}/{resource}?state=open&per_page=100'],capture_output=True,text=True,timeout=45)
    if reply.returncode:raise ValueError('GitHub read failed; inspect gh authentication/network privately')
    pages=json.loads(reply.stdout)
    rows=[row for page in pages for row in page]
    output=[]
    for row in rows:
        if resource=='issues' and 'pull_request' in row:continue
        item={key:row.get(key) for key in ('number','title','html_url','state','draft','updated_at')}
        item['author']=row.get('user',{}).get('login')
        if resource=='pulls':
            item.update(head=row['head']['sha'],base=row['base']['sha'],head_branch=row['head']['ref'],base_branch=row['base']['ref'])
        output.append(item)
    return output


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cwd',required=True);parser.add_argument('--repository')
    args=parser.parse_args();context=Project(args.cwd,args.repository)
    print(json.dumps({'checkout':verify_repository(context),'pulls':read(context.repository,'pulls'),
                      'issues':read(context.repository,'issues')},indent=2))

if __name__=='__main__':
    try:main()
    except (ValueError,OSError,subprocess.TimeoutExpired) as exc:
        print(f'Blocked: {exc}',file=sys.stderr);raise SystemExit(78)
