import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


hosting = module('hosting')
installer = module('install')


class FakeCloudflare:
    def __init__(self, manifest):
        self.zone_id = 'zone-id'
        self.data = [dict(id='mail', type='MX', name='example.com', content='mail.example.net')]
        self.writes = []
        self.fail_at = None

    def zone(self):
        return {'id': self.zone_id, 'name': 'example.com', 'account_id': 'account-id'}

    def records(self, name):
        return copy.deepcopy([r for r in self.data if r['name'] == name])

    def write(self, operation):
        if len(self.writes) == self.fail_at:
            raise hosting.HostingError('simulated interrupted write')
        record = {**operation['desired'], 'id': operation.get('id', 'record-' + str(len(self.writes)))}
        self.data = [r for r in self.data if r['id'] != record['id']] + [record]
        self.writes.append(copy.deepcopy(operation))
        return record


class HostingTests(unittest.TestCase):
    def setUp(self):
        self.wanted = {'type': 'CNAME', 'name': 'example.com', 'content': 'route.up.railway.app', 'proxied': False, 'ttl': 1}

    def test_route_conversion_updates_existing_id_and_preserves_other_types(self):
        records = [{'id': 'old', 'type': 'A', 'name': 'example.com', 'content': '192.0.2.1'},
                   {'id': 'mail', 'type': 'MX', 'name': 'example.com', 'content': 'mail.example.net'}]
        result = hosting.record_operation(self.wanted, records)
        self.assertEqual((result['action'], result['id']), ('update', 'old'))
        self.assertEqual(len(records), 2)

    def test_multiple_address_records_are_rejected(self):
        records = [{'id': 'a', 'type': 'A', 'name': 'example.com', 'content': '192.0.2.1'},
                   {'id': 'b', 'type': 'AAAA', 'name': 'example.com', 'content': '::1'}]
        with self.assertRaises(hosting.HostingError):
            hosting.record_operation(self.wanted, records)

    def test_ns_conflict_is_rejected(self):
        with self.assertRaises(hosting.HostingError):
            hosting.record_operation(self.wanted, [{'type': 'NS', 'name': 'example.com', 'content': 'ns.example.net'}])

    def test_cname_trailing_dot_and_case_are_noop(self):
        actual = {**self.wanted, 'id': 'route', 'content': 'ROUTE.UP.RAILWAY.APP.'}
        self.assertEqual(hosting.record_operation(self.wanted, [actual])['action'], 'noop')

    def test_verification_preserves_unrelated_txt_and_normalizes_quotes(self):
        wanted = {'type': 'TXT', 'name': '_railway-verify.example.com', 'content': 'railway-verify=abc', 'ttl': 1}
        actual = [{'id': 'other', **wanted, 'content': 'other-verification=keep'}, {'id': 'ours', **wanted, 'content': '"railway-verify=abc"'}]
        self.assertEqual(hosting.record_operation(wanted, actual)['action'], 'noop')
        self.assertEqual(actual[0]['content'], 'other-verification=keep')

    def test_conflicting_verification_records_fail(self):
        wanted = {'type': 'TXT', 'name': '_railway-verify.example.com', 'content': 'railway-verify=abc'}
        with self.assertRaises(hosting.HostingError):
            hosting.record_operation(wanted, [{'id': str(i), **wanted} for i in range(2)])

    def test_profile_is_literal_owner_only_and_hides_secrets(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / 'profile.env'
            file.write_text('export CLOUDFLARE_API_TOKEN="dummy-token-value"\n')
            file.chmod(0o600)
            env = hosting.profile_environment(str(file), {})
            self.assertEqual(env['CLOUDFLARE_API_TOKEN'], 'dummy-token-value')
            self.assertEqual(hosting.redact('dummy-token-value failed', env), '<redacted> failed')
            file.chmod(0o644)
            with self.assertRaises(hosting.HostingError):
                hosting.profile_environment(str(file), {})
            file.chmod(0o600)
            file.write_text('CLOUDFLARE_API_TOKEN=$(touch /tmp/never-run)\n')
            with self.assertRaises(hosting.HostingError):
                hosting.profile_environment(str(file), {})

    def test_explicit_railway_profile_does_not_reuse_inherited_token(self):
        with patch.dict(os.environ, {'RAILWAY_API_TOKEN': 'wrong-workspace', 'RAILWAY_TOKEN': 'wrong-project'}):
            with self.assertRaises(hosting.HostingError):
                hosting.railway_env({'railway': {'profile': '/nonexistent-profile'}})

    def test_wrong_workspace_is_rejected(self):
        manifest = json.loads((ROOT / 'config/hosting/paul.json').read_text())
        data = {'project': {'id': manifest['railway']['project_id'], 'workspaceId': 'wrong-workspace'}}
        with patch.object(hosting, 'run_json', return_value=data):
            with self.assertRaises(hosting.HostingError):
                hosting.railway_project(manifest, {})

    def plan_context(self, folder):
        manifest = {'schema_version': 1, 'railway': {'project_id': 'project'}, 'environments': {'dev': {}}, 'cloudflare': {}}
        domain = {'dnsRecords': [{'recordType': 'DNS_RECORD_TYPE_CNAME', 'fqdn': 'example.com', 'requiredValue': 'route.up.railway.app'}],
                  'verification': {'dnsHost': '_railway-verify', 'token': 'railway-verify=abc'}}
        client = FakeCloudflare(manifest)
        return manifest, domain, client

    def test_apply_second_run_noop_and_partial_failure_resume(self):
        with tempfile.TemporaryDirectory() as folder:
            manifest, domain, client = self.plan_context(folder)
            with patch.object(hosting, 'ROOT', Path(folder)), patch.object(hosting, 'railway_env', return_value={}), patch.object(hosting, 'railway_project'), patch.object(hosting, 'domain_status', return_value=domain), patch.object(hosting, 'Cloudflare', return_value=client):
                saved = hosting.dns_plan(manifest, ['dev'])
                client.fail_at = 1
                with self.assertRaises(hosting.HostingError):
                    hosting.apply_plan(manifest, saved, ['dev'])
                self.assertEqual(len(client.writes), 1)
                client.fail_at = None
                resumed = hosting.dns_plan(manifest, ['dev'])
                self.assertEqual(resumed['operations'][0]['action'], 'noop')
                result = hosting.apply_plan(manifest, resumed, ['dev'])
                self.assertEqual(len(result['changed']), 1)
                clean = hosting.dns_plan(manifest, ['dev'])
                self.assertEqual(hosting.apply_plan(manifest, clean, ['dev'])['changed'], [])
                self.assertEqual(client.data[0]['id'], 'mail')
                journal = json.loads((Path(folder) / 'local/hosting/project.json').read_text())
                self.assertEqual(len(journal['events']), 2)

    def test_stale_plan_refuses_all_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            manifest, domain, client = self.plan_context(folder)
            with patch.object(hosting, 'railway_env', return_value={}), patch.object(hosting, 'railway_project'), patch.object(hosting, 'domain_status', return_value=domain), patch.object(hosting, 'Cloudflare', return_value=client):
                saved = hosting.dns_plan(manifest, ['dev'])
                client.data.append({'id': 'new', **self.wanted})
                with self.assertRaises(hosting.HostingError):
                    hosting.apply_plan(manifest, saved, ['dev'])
                self.assertEqual(client.writes, [])


class InstallTests(unittest.TestCase):
    def test_install_preserves_settings_is_idempotent_and_restorable(self):
        with tempfile.TemporaryDirectory() as folder:
            root, home = Path(folder) / 'agents', Path(folder) / 'home'
            (root / 'config').mkdir(parents=True)
            (home / '.codex').mkdir(parents=True)
            (root / 'config/mcp.json').write_text(json.dumps({'mcpServers': {'cloudflare': {'url': 'https://mcp.cloudflare.com/mcp'}}}))
            (root / 'config/links.json').write_text(json.dumps({'links': [
                {'source': 'local/codex/config.toml', 'target': '~/.codex/config.toml', 'kind': 'codex'},
                {'source': 'local/shell/zprofile', 'target': '~/.zprofile', 'kind': 'shell'}]}))
            original = 'model = "existing-model"\n[mcp_servers.existing]\ncommand = "existing-tool"\n'
            target = home / '.codex/config.toml'
            target.write_text(original)
            (home / '.zprofile').write_text('export EXISTING_SETTING=keep\n')
            self.assertEqual(installer.install(root, home)['status'], 'needs_install')
            installed = installer.install(root, home, apply=True)
            self.assertTrue(target.is_symlink())
            self.assertIn('existing-model', target.read_text())
            self.assertIn('mcp_servers.existing', target.read_text())
            self.assertEqual(installer.install(root, home)['status'], 'current')
            installer.restore(Path(installed['backup']))
            self.assertFalse(target.is_symlink())
            self.assertEqual(target.read_text(), original)
            self.assertEqual((home / '.zprofile').read_text(), 'export EXISTING_SETTING=keep\n')


if __name__ == '__main__':
    unittest.main()
