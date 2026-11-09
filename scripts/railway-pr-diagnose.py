#!/usr/bin/env python3
"""Read-only Railway diagnosis for one environment, chosen by PR number or name.

Reports the step that stopped each failed deployment, its first error lines, every
service's deployment and volumes, and which variables are references. Variable
values are held in memory only to mask them in log lines and are never printed.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hosting import HostingError, profile_environment  # noqa: E402

FAILED = {'FAILED', 'CRASHED'}
BUILD_STEPS = {'SNAPSHOT_CODE', 'BUILD_IMAGE', 'PUBLISH_IMAGE'}
DATABASE_SERVICE = re.compile(r'(?i)postgres|mysql|redis|mongo|clickhouse')
DATABASE_URL = re.compile(r'(?i)(^|_)(DATABASE|DB|POSTGRES|PG|REDIS|MONGO|MYSQL)(_[A-Z0-9]+)*_(URL|URI)$')
REFERENCE = re.compile(r'^\$\{\{\s*([^{}]+?)\s*\}\}$')
ERROR_LINE = re.compile(r'(?i)\b(error|err!|fatal|failed|failure|exception|panic|traceback|'
                        r'enotfound|econnrefused|etimedout|cannot find|not found)\b')
CREDENTIAL = re.compile(r'(?i)\b(pass(?:word|wd)?|secret|token|api[_-]?key|authorization)\b'
                        r'(["\']?\s*[:=]\s*["\']?)([^\s"\',;&]+)')
URL_PASSWORD = re.compile(r'(://[^/\s:@]+):[^@\s/]+@')
BEARER = re.compile(r'(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+')
JWT = re.compile(r'\beyJ[\w-]+\.[\w-]+\.[\w-]+')
LONG_TOKEN = re.compile(r'\b[A-Za-z0-9_-]{32,}\b')
MASK = '***'

PROJECT_QUERY = '''query($id: String!) { project(id: $id) { id name
  environments { edges { node { id name } } } buckets { edges { node { name } } } } }'''
ENVIRONMENT_QUERY = '''query($id: String!) { environment(id: $id) { id name
  serviceInstances { edges { node { serviceId serviceName
    latestDeployment { id status createdAt meta } } } }
  volumeInstances { edges { node { mountPath state serviceId volume { name } } } } } }'''
EVENTS_QUERY = '''query($id: String!) { deploymentEvents(id: $id, first: 100) { edges { node {
  step createdAt completedAt payload { error reason detail } } } } }'''
UNRENDERED_QUERY = '''query($p: String!, $e: String!, $s: String) {
  variables(projectId: $p, environmentId: $e, serviceId: $s, unrendered: true) }'''
RENDERED_QUERY = '''query($p: String!, $e: String!, $s: String) {
  variables(projectId: $p, environmentId: $e, serviceId: $s) }'''
LOGS_QUERY = '''query($id: String!) { %s(deploymentId: $id, limit: 500) { message severity } }'''


class DiagnosisError(Exception):
    pass


def redact(text, masks=()):
    """Remove known variable values and credential-shaped strings from a log line."""
    for value in sorted((m for m in masks if len(m) >= 6), key=len, reverse=True):
        text = text.replace(value, MASK)
    text = URL_PASSWORD.sub(rf'\1:{MASK}@', text)
    text = BEARER.sub(f'Bearer {MASK}', text)
    text = JWT.sub(MASK, text)
    text = CREDENTIAL.sub(rf'\1\2{MASK}', text)
    return LONG_TOKEN.sub(MASK, text)


def classify(value):
    """Return (kind, reference target); only a whole-value reference exposes its target."""
    if value is None or value == '':
        return 'empty', None
    match = REFERENCE.match(value)
    if match:
        return 'reference', match[1]
    return ('mixed', None) if '${{' in value else ('literal', None)


def nodes(connection):
    return [edge['node'] for edge in ((connection or {}).get('edges') or [])]


def find_environment(environments, target):
    """Match a PR number to '<name>-pr-<N>', otherwise an exact name or ID."""
    if re.fullmatch(r'\d+', target):
        suffix = f'-pr-{target}'
        return next((e for e in environments if e['name'].endswith(suffix)), None)
    return next((e for e in environments if target in (e['name'], e['id'])), None)


def failing_step(events):
    """Return (step, error) for the step that stopped a deployment."""
    ordered = sorted(events, key=lambda event: event.get('createdAt') or '')
    for event in ordered:
        error = (event.get('payload') or {}).get('error')
        if error:
            return event['step'], error
    unfinished = [event for event in ordered if not event.get('completedAt')]
    return (unfinished[-1]['step'], None) if unfinished else (None, None)


def error_lines(logs, limit, masks=()):
    """First distinct error-looking lines, or the final lines when none match."""
    messages = [(log.get('message') or '').strip() for log in logs]
    picked = [message for log, message in zip(logs, messages) if message and (
        (log.get('severity') or '').lower() == 'error' or ERROR_LINE.search(message))]
    chosen = list(dict.fromkeys(picked))[:limit] or [m for m in messages if m][-limit:]
    return [redact(message, masks)[:300] for message in chosen]


def variable_report(unrendered):
    shown = []
    for name in sorted(unrendered):
        if name.startswith('RAILWAY_'):
            continue
        kind, target = classify(unrendered[name])
        shown.append({'name': name, 'kind': kind, 'target': target})
    return shown, len(unrendered) - len(shown)


def service_problems(service, statuses, buckets=()):
    """Name the conditions that explain a broken environment."""
    name, deployment, problems = service['name'], service['deployment'], []
    status = deployment['status'] if deployment else None
    if status is None or status == 'SKIPPED':
        problems.append(f'{name}: no deployment ran (skipped or never deployed). A skipped service '
                        'is started from the Railway canvas Deploy button or a source change.')
    elif status in FAILED:
        step = deployment.get('step') or 'unknown step'
        problems.append(f'{name}: {status} at {step}.')
    elif status == 'REMOVED':
        problems.append(f'{name}: latest deployment was removed.')
    if DATABASE_SERVICE.search(name) and not service['volumes']:
        problems.append(f'{name}: database service has no volume in this environment.')
    for variable in service['variables']:
        if DATABASE_URL.search(variable['name']) and variable['kind'] == 'literal':
            problems.append(f"{name}: {variable['name']} is a literal, so it keeps the host and password it was copied "
                            'with; a database URL must be a reference.')
        target = variable['target'] or ''
        owner = target.split('.', 1)[0] if '.' in target else None
        if owner and owner != 'shared' and owner not in buckets:
            if owner not in statuses:
                problems.append(f"{name}: {variable['name']} references {owner}, which is not in this environment.")
            elif statuses[owner] != 'SUCCESS':
                problems.append(f"{name}: {variable['name']} references {owner}, whose latest deployment "
                                f'is {statuses[owner] or "missing"}.')
    return problems


class Railway:
    def __init__(self, profile):
        self.executable = shutil.which('railway')
        if not self.executable:
            raise DiagnosisError('Railway native CLI is not on PATH')
        env = dict(os.environ)
        env.pop('RAILWAY_TOKEN', None)
        env.pop('RAILWAY_API_TOKEN', None)
        self.env = profile_environment(profile, env)
        if not self.env.get('RAILWAY_API_TOKEN'):
            raise DiagnosisError('Missing Railway API credential in the selected workspace profile')

    def query(self, document, **variables):
        command = [self.executable, 'api', document, '--compact']
        for key, value in variables.items():
            command += ['--raw-var', f'{key}={value}']
        result = subprocess.run(command, env=self.env, capture_output=True, text=True, timeout=90)
        if result.returncode:
            raise DiagnosisError('Railway API query failed: ' + redact((result.stderr or result.stdout).strip())[:400])
        reply = json.loads(result.stdout)
        return reply.get('data', reply)

    def inspect_deployment(self, deployment_id, lines, masks):
        events = nodes(self.query(EVENTS_QUERY, id=deployment_id).get('deploymentEvents'))
        step, error = failing_step(events)
        sources = ['buildLogs'] if step in BUILD_STEPS else ['deploymentLogs'] if step else ['buildLogs', 'deploymentLogs']
        found = []
        for source in sources:
            found += error_lines(self.query(LOGS_QUERY % source, id=deployment_id).get(source) or [], lines, masks)
        return {'step': step, 'error': redact(error, masks)[:400] if error else None,
                'errors': list(dict.fromkeys(found))[:lines]}

    def inspect_environment(self, project_id, environment_id, lines, buckets=()):
        environment = self.query(ENVIRONMENT_QUERY, id=environment_id)['environment']
        volumes = nodes(environment.get('volumeInstances'))
        services = []
        for instance in nodes(environment.get('serviceInstances')):
            scope = {'p': project_id, 'e': environment_id, 's': instance['serviceId']}
            unrendered = self.query(UNRENDERED_QUERY, **scope).get('variables') or {}
            rendered = self.query(RENDERED_QUERY, **scope).get('variables') or {}
            masks = [value for value in [*unrendered.values(), *rendered.values()] if isinstance(value, str)]
            shown, hidden = variable_report(unrendered)
            deployment = dict(instance['latestDeployment']) if instance.get('latestDeployment') else None
            if deployment:
                meta = deployment.pop('meta', None) or {}
                deployment.update(branch=meta.get('branch'), commit=(meta.get('commitHash') or '')[:7] or None)
                if deployment['status'] in FAILED:
                    deployment.update(self.inspect_deployment(deployment['id'], lines, masks))
            services.append({'name': instance['serviceName'], 'id': instance['serviceId'], 'deployment': deployment,
                             'volumes': [{'name': (v.get('volume') or {}).get('name'), 'mountPath': v.get('mountPath'),
                                          'state': v.get('state')} for v in volumes
                                         if v.get('serviceId') == instance['serviceId']],
                             'variables': shown, 'railway_managed_hidden': hidden})
        statuses = {s['name']: (s['deployment'] or {}).get('status') for s in services}
        return {'environment': {'id': environment['id'], 'name': environment['name']}, 'services': services,
                'problems': [problem for service in services for problem in service_problems(service, statuses, buckets)]}


def print_report(report, project):
    environment = report['environment']
    print(f"Environment {environment['name']} ({environment['id']}) in project {project['name']}")
    print(f"\nProblems ({len(report['problems'])}):" if report['problems'] else '\nProblems: none detected')
    for problem in report['problems']:
        print(f'  - {problem}')
    for service in report['services']:
        print(f"\n{service['name']} ({service['id']})")
        deployment = service['deployment']
        if deployment:
            print(f"  deployment {deployment['id']} {deployment['status']} "
                  f"branch={deployment.get('branch')} commit={deployment.get('commit')} {deployment['createdAt']}")
            if deployment.get('step') or deployment.get('error'):
                print(f"  failing step: {deployment.get('step')}: {deployment.get('error') or '(no event error)'}")
            for line in deployment.get('errors') or []:
                print(f'    | {line}')
        else:
            print('  deployment: none')
        print('  volumes: ' + (', '.join(f"{v['name']} at {v['mountPath']} ({v['state']})" for v in service['volumes']) or 'none'))
        print(f"  variables ({service['railway_managed_hidden']} Railway-managed hidden):")
        for variable in service['variables']:
            target = f" -> {variable['target']}" if variable['target'] else ''
            print(f"    {variable['name']}: {variable['kind']}{target}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('target', nargs='?', help='PR number, environment name, or environment ID')
    parser.add_argument('--project', default=os.environ.get('RAILWAY_PROJECT_ID'), help='Railway project ID')
    parser.add_argument('--deployment', help='Report one deployment by ID instead of an environment')
    parser.add_argument('--profile', default='railway.workspace', help='Credential profile')
    parser.add_argument('--lines', type=int, default=8, help='Error lines per failed deployment')
    parser.add_argument('--json', action='store_true', help='Print JSON')
    args = parser.parse_args(argv)
    try:
        railway = Railway(args.profile)
        if args.deployment:
            result = railway.inspect_deployment(args.deployment, args.lines, [])
            print(json.dumps(result, indent=2))
            return 0
        if not args.project or not args.target:
            parser.error('a target and --project (or RAILWAY_PROJECT_ID) are required')
        project = railway.query(PROJECT_QUERY, id=args.project)['project']
        environments = nodes(project.get('environments'))
        environment = find_environment(environments, args.target)
        if not environment:
            print(f'No environment matches {args.target}. Environments: ' + ', '.join(e['name'] for e in environments),
                  file=sys.stderr)
            return 3
        buckets = {bucket['name'] for bucket in nodes(project.get('buckets'))}
        report = railway.inspect_environment(project['id'], environment['id'], args.lines, buckets)
    except (DiagnosisError, HostingError, OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as error:
        print(redact(str(error)), file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_report(report, project)
    return 1 if report['problems'] else 0


if __name__ == '__main__':
    sys.exit(main())
