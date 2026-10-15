import contextlib
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import inventory
import install


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / 'agents'
        shutil.copytree(ROOT, self.root, ignore=shutil.ignore_patterns('.git', 'local', 'node_modules', '__pycache__'))
        self.home = Path(self.temporary.name) / 'home'
        self.home.mkdir()
        self.data = inventory.load_inventory(self.root)

    def write_inventory(self, data):
        (self.root / 'config/inventory.json').write_text(json.dumps(data))

    def test_shared_inventory_works_without_local_state_or_credentials(self):
        self.assertFalse((self.root / 'local').exists())
        self.assertGreater(len(self.data['entries']), 20)
        self.assertIn('cloudflare.dns-token', inventory.documentation(self.data, self.root))
        self.assertIn('scripts/inventory.py', inventory.utility_files(self.root))

    def test_configuration_inventory_is_independent_of_skills_and_import_provenance(self):
        expected = inventory.documentation(self.data, self.root)
        shutil.rmtree(self.root / 'skills')
        shutil.rmtree(self.root / 'licenses')
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(inventory.main(['--root', str(self.root), 'validate']), 0)
            self.assertEqual(inventory.main(['--root', str(self.root), 'docs']), 0)
            self.assertEqual(inventory.main(['--root', str(self.root), 'docs', '--check']), 0)
        self.assertEqual((self.root / 'docs/INVENTORY.md').read_text(), expected)

    def test_secret_value_field_is_rejected_without_echoing_value(self):
        data = copy.deepcopy(self.data)
        data['entries'][0]['value'] = 'sentinel-private-value'
        self.write_inventory(data)
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            code = inventory.main(['--root', str(self.root), 'validate'])
        self.assertEqual(code, 1)
        self.assertNotIn('sentinel-private-value', output.getvalue())
        self.assertIn('unexpected field', output.getvalue())

    def test_ignored_or_outside_references_cannot_be_read(self):
        for path in ('.', 'local/credentials/private.json', '../private.json', '/tmp/private.json'):
            data = copy.deepcopy(self.data)
            data['entries'][0]['path_ref']['file'] = path
            self.write_inventory(data)
            with self.assertRaises(inventory.InventoryError):
                inventory.load_inventory(self.root)

    def test_duplicate_ids_unknown_consumers_and_missing_link_entries_fail(self):
        variants = []
        data = copy.deepcopy(self.data)
        data['entries'][1]['id'] = data['entries'][0]['id']
        variants.append(data)
        data = copy.deepcopy(self.data)
        data['entries'][0]['consumers'].append('unregistered.consumer')
        variants.append(data)
        data = copy.deepcopy(self.data)
        data['entries'] = [e for e in data['entries'] if e.get('link_index') != 0]
        variants.append(data)
        for data in variants:
            self.write_inventory(data)
            with self.assertRaises(inventory.InventoryError):
                inventory.load_inventory(self.root)

    def test_unknown_schema_extensions_fail_instead_of_being_ignored(self):
        with self.assertRaises(inventory.InventoryError):
            inventory.schema_check('x', {'type': 'string', 'secret_extension': True}, {})
        with self.assertRaises(inventory.InventoryError):
            inventory.schema_check(True, {'type': 'integer'}, {})

    def test_reference_and_runtime_share_changed_profile_location(self):
        from hosting import resolve_profile
        path = self.root / 'config/profiles.json'
        profiles = json.loads(path.read_text())
        profiles['profiles']['cloudflare.default']['path'] = '~/.agents/local/credentials/replacement.env'
        path.write_text(json.dumps(profiles))
        entry = inventory.load_inventory(self.root)['entries'][0]
        self.assertEqual(inventory.displayed_entry(entry, self.root)['resolved_path'], profiles['profiles']['cloudflare.default']['path'])
        self.assertEqual(inventory.location(entry, self.root), resolve_profile('cloudflare.default', self.root))

    def test_validation_rejects_unsupported_defaults_and_unregistered_config_or_server(self):
        path = self.root / 'config/codex.defaults.toml'
        original = path.read_text()
        path.write_text('unsupported_setting="sentinel-private-text"\n')
        with self.assertRaises(inventory.InventoryError):
            inventory.load_inventory(self.root)
        path.write_text(original)
        extra = self.root / 'config/new-settings.json'
        extra.write_text('{}')
        with self.assertRaises(inventory.InventoryError):
            inventory.load_inventory(self.root)
        extra.unlink()
        path = self.root / 'config/mcp.json'
        servers = json.loads(path.read_text())
        servers['mcpServers']['unregistered'] = {'url': 'https://example.test/mcp'}
        path.write_text(json.dumps(servers))
        with self.assertRaises(inventory.InventoryError):
            inventory.load_inventory(self.root)

    def test_new_application_plugins_and_runtimes_are_reported(self):
        path = self.home / '.codex/config.toml'
        path.parent.mkdir(parents=True)
        text = '\n'.join('[plugins.' + json.dumps(p['id']) + ']\nenabled = ' + str(p['enabled']).lower()
                         for entry in self.data['entries'] for p in entry.get('plugins', []))
        text += '\n[plugins.unregistered]\nenabled = true\n[mcp_servers.unregistered]\ncommand = "private-path-not-to-echo"\n'
        path.write_text(text)
        results = inventory.local_checks(self.data, self.root, self.home)
        for id in ('application.codex-plugins', 'application.codex-mcp'):
            self.assertFalse(next(r for r in results if r['id'] == id)['passed'])
        self.assertNotIn('private-path-not-to-echo', json.dumps(results))

    def test_profile_catalog_rejects_secret_fields(self):
        path = self.root / 'config/profiles.json'
        profiles = json.loads(path.read_text())
        profiles['profiles']['cloudflare.default']['value'] = 'sentinel-private-text'
        path.write_text(json.dumps(profiles))
        with self.assertRaises(inventory.InventoryError) as error:
            inventory.load_inventory(self.root)
        self.assertNotIn('sentinel-private-text', str(error.exception))

    def test_profile_environment_uses_catalog_without_stale_path(self):
        import hosting
        path = self.root / 'config/profiles.json'
        profiles = json.loads(path.read_text())
        for label in ('first', 'replacement'):
            private = self.root / ('local/credentials/' + label + '.env')
            private.parent.mkdir(parents=True, exist_ok=True)
            private.write_text('CLOUDFLARE_API_TOKEN=dummy-' + label + '\n')
            private.chmod(0o600)
            profiles['profiles']['cloudflare.default']['path'] = str(private)
            path.write_text(json.dumps(profiles))
            with patch.object(hosting, 'ROOT', self.root):
                self.assertEqual(hosting.profile_environment('cloudflare.default', {})['CLOUDFLARE_API_TOKEN'], 'dummy-' + label)

    def test_live_check_uses_explicit_manifest(self):
        manifest = json.loads((self.root / 'config/hosting/paul.json').read_text())
        with patch('hosting.load_manifest', return_value=manifest) as loading, patch('hosting.Cloudflare'), patch.object(inventory, 'cloudflare_access', return_value=True), patch.object(inventory, 'mcp_read', return_value=True), patch('hosting.railway_env', return_value={}), patch('hosting.railway_project', return_value={'id': 'selected'}):
            results = inventory.live_checks(self.root, Path('/explicit/project.json'))
        loading.assert_called_once_with(Path('/explicit/project.json'))
        self.assertTrue(all(item['passed'] for item in results))

    def test_live_mcp_probe_refuses_unapproved_token_destination_before_network(self):
        with patch.object(inventory.urllib.request, 'urlopen') as network:
            with self.assertRaises(ValueError):
                inventory.mcp_read('dummy-private-token', 'account', 'example.com', 'https://other.example/mcp')
        network.assert_not_called()

    def test_documentation_is_deterministic_and_never_reads_secret_profiles(self):
        first = inventory.documentation(self.data, self.root)
        private = self.root / 'local/credentials/cloudflare.env'
        private.parent.mkdir(parents=True)
        private.write_text('CLOUDFLARE_API_TOKEN=sentinel-secret\n')
        self.assertEqual(inventory.documentation(self.data, self.root), first)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(inventory.main(['--root', str(self.root), 'show', 'cloudflare.dns-token']), 0)
        self.assertNotIn('sentinel-secret', output.getvalue())
        self.assertNotIn('sentinel-secret', first)

    def test_stale_generated_docs_fail_check_without_writing(self):
        path = self.root / 'docs/INVENTORY.md'
        path.write_text('stale\n')
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            self.assertEqual(inventory.main(['--root', str(self.root), 'docs', '--check']), 1)
        self.assertEqual(path.read_text(), 'stale\n')

    def test_local_checks_never_read_unsafe_profile_or_legacy_shell(self):
        path = self.home / '.agents/local/credentials/cloudflare.env'
        path.parent.mkdir(parents=True)
        path.write_text('CLOUDFLARE_API_TOKEN=sentinel-secret\n')
        path.chmod(0o644)
        actual_read = Path.read_text
        def reading(file, *args, **kwargs):
            if file == path or file == self.home / '.secrets.sh':
                raise AssertionError('Unsafe or legacy credential file read')
            return actual_read(file, *args, **kwargs)
        with patch.object(Path, 'read_text', reading):
            result = inventory.local_checks(self.data, self.root, self.home)
        cloudflare = next(item for item in result if item['id'] == 'cloudflare.dns-token')
        self.assertFalse(cloudflare['passed'])
        self.assertNotIn('sentinel-secret', json.dumps(result))

    def test_provider_failure_message_cannot_escape_into_status(self):
        class FailingClient:
            def __init__(self, *args):
                raise RuntimeError('sentinel-provider-secret')
        with patch('hosting.Cloudflare', FailingClient), patch.object(inventory, 'mcp_read', side_effect=RuntimeError('sentinel-mcp-secret')), patch('hosting.railway_project', side_effect=RuntimeError('sentinel-railway-secret')), patch('hosting.railway_env', return_value={}), patch('hosting.profile_environment', return_value={'CLOUDFLARE_API_TOKEN': 'sentinel-token'}):
            result = inventory.live_checks(self.root)
        self.assertTrue(all(not item['passed'] for item in result))
        self.assertNotIn('sentinel', json.dumps(result))

    def test_non_table_plugin_settings_report_failure_and_continue(self):
        path = self.home / '.codex/config.toml'
        path.parent.mkdir(parents=True)
        plugin_id = next(e for e in self.data['entries'] if e.get('plugins'))['plugins'][0]['id']
        for text in ('plugins = "sentinel-private-text"\n',
                     '[plugins]\n' + json.dumps(plugin_id) + ' = true\n'):
            with self.subTest(text_format='root' if text.startswith('plugins =') else 'entry'):
                path.write_text(text)
                results = inventory.local_checks(self.data, self.root, self.home)
                result = next(item for item in results if item['id'] == 'application.codex-plugins')
                self.assertFalse(result['passed'])
                self.assertIn('railway.cli', [item['id'] for item in results])
                self.assertNotIn('sentinel-private-text', json.dumps(results))

    def test_saved_observation_is_owner_only_and_contains_only_status(self):
        result = {'passed': True, 'results': [{'id': 'cloudflare.api', 'passed': True}]}
        inventory.save_status(self.root, result)
        path = self.root / 'local/inventory/status.json'
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(json.loads(path.read_text()), result)

    def test_cloudflare_read_check_does_not_require_legacy_membership_permissions(self):
        class Client:
            def __init__(self, *args):
                pass
            def zone(self):
                return {'id': 'zone'}
            def request(self, method, path):
                self.assert_read = method == 'GET'
                if path == '/user/tokens/verify':
                    return {'result': {'status': 'active'}}
                if path == '/user':
                    return {'result': {}}
                if path == '/zones/zone/dns_records?per_page=1':
                    return {'result': []}
                raise AssertionError('Unexpected provider request')
        self.assertTrue(inventory.cloudflare_access({'cloudflare': {'profile': 'unused', 'account_id': 'account'}}, Client, lambda *args: {}))

    def test_legacy_dns_edit_membership_does_not_bypass_denied_dns_read(self):
        class Client:
            def __init__(self, *args):
                pass
            def zone(self):
                return {'id': 'zone', 'permissions': ['#dns_records:edit']}
            def request(self, method, path):
                if 'dns_records' in path:
                    raise inventory.InventoryError('DNS read denied')
                return {'result': {'status': 'active'}}
        with self.assertRaises(inventory.InventoryError):
            inventory.cloudflare_access({'cloudflare': {'profile': 'unused'}}, Client, lambda *args: {})


class ManagedDefaultsTests(unittest.TestCase):
    def test_restore_refuses_newer_application_edits_before_changing_any_link(self):
        with tempfile.TemporaryDirectory() as folder:
            root, home = Path(folder) / 'agents', Path(folder) / 'home'
            (root / 'config').mkdir(parents=True)
            (home / '.codex').mkdir(parents=True)
            (root / 'config/mcp.json').write_text('{"mcpServers":{}}')
            (root / 'config/links.json').write_text(json.dumps({'links': [
                {'source': 'local/codex/config.toml', 'target': '~/.codex/config.toml', 'kind': 'codex'},
                {'source': 'local/shell/zprofile', 'target': '~/.zprofile', 'kind': 'shell'}]}))
            target = home / '.codex/config.toml'
            target.write_text('model="original"\n')
            installed = install.install(root, home, apply=True)
            target.write_text('model="new-user-edit"\n')
            with self.assertRaises(ValueError):
                install.restore(Path(installed['backup']))
            self.assertTrue(target.is_symlink())
            self.assertTrue((home / '.zprofile').is_symlink())
            self.assertIn('new-user-edit', target.read_text())

    def test_mcp_rendering_handles_quoted_dotted_inline_and_multiline_toml(self):
        cases = [
            'note = """keep\n[mcp_servers.cloudflare]\nkeep too\n"""\n',
            '[mcp_servers."cloudflare"]\nurl="https://mcp.cloudflare.com/mcp"\n',
            'mcp_servers.cloudflare.url="https://mcp.cloudflare.com/mcp"\n',
            'mcp_servers={cloudflare={url="https://mcp.cloudflare.com/mcp"},existing={command="keep"}}\n'
        ]
        for text in cases:
            with self.subTest(toml_format=cases.index(text)):
                original = install.tomllib.loads(text)
                rendered = install.render_codex(text, {'cloudflare': {'url': 'https://mcp.cloudflare.com/mcp'}})
                parsed = install.tomllib.loads(rendered)
                self.assertEqual(parsed.get('note'), original.get('note'))
                self.assertEqual(parsed['mcp_servers'].get('existing'), original.get('mcp_servers', {}).get('existing'))
                self.assertEqual(install.render_codex(rendered, {'cloudflare': {'url': 'https://mcp.cloudflare.com/mcp'}}), rendered)

    def test_managed_defaults_preserve_inline_comments(self):
        rendered = install.render_defaults('model="old" # keep comment\n', {'model': 'new'})
        self.assertIn('# keep comment', rendered)

    def test_link_sources_and_token_destinations_are_guarded(self):
        for server in ({'url': 'https://other.example/mcp'}, {'url': 'https://user:sentinel@mcp.cloudflare.com/mcp'}, {'url': 'https://mcp.cloudflare.com/mcp?token=sentinel'}):
            with self.assertRaises(ValueError):
                install.validate_mcp({'cloudflare': server})
        with tempfile.TemporaryDirectory() as folder:
            root, home = Path(folder) / 'agents', Path(folder) / 'home'
            root.mkdir()
            home.mkdir()
            with self.assertRaises(ValueError):
                install.validate_links(root, [{'source': '../outside', 'target': '~/.config/example', 'kind': 'text'}], home)

    def test_installer_applies_defaults_and_restores_original_config(self):
        with tempfile.TemporaryDirectory() as folder:
            root, home = Path(folder) / 'agents', Path(folder) / 'home'
            (root / 'config').mkdir(parents=True)
            (home / '.codex').mkdir(parents=True)
            (root / 'config/codex.defaults.toml').write_text('model = "chosen-model"\nweb_search = "live"\n')
            (root / 'config/mcp.json').write_text('{"mcpServers":{}}')
            (root / 'config/links.json').write_text(json.dumps({'links': [
                {'source': 'local/codex/config.toml', 'target': '~/.codex/config.toml', 'kind': 'codex'},
                {'source': 'local/shell/zprofile', 'target': '~/.zprofile', 'kind': 'shell'}]}))
            original = 'model = "old-model"\n[plugins.existing]\nenabled = true\n'
            target = home / '.codex/config.toml'
            target.write_text(original)
            installed = install.install(root, home, apply=True)
            parsed = install.tomllib.loads(target.read_text())
            self.assertEqual(parsed['model'], 'chosen-model')
            self.assertTrue(parsed['plugins']['existing']['enabled'])
            self.assertEqual(install.install(root, home)['status'], 'current')
            install.restore(Path(installed['backup']))
            self.assertEqual(target.read_text(), original)

    def test_managed_changes_preserve_unrelated_multiline_values_and_sections(self):
        original = '''# keep this comment
model = "old-model"
notify = [
  "keep-notifier",
  "arg"
]
custom = """keep
[text inside a string]
"""
[plugins.existing]
enabled = true
'''
        desired = {'model': 'chosen-model', 'web_search': 'live'}
        changed = install.render_defaults(original, desired)
        self.assertIn('keep this comment', changed)
        self.assertIn('keep-notifier', changed)
        self.assertIn('[text inside a string]', changed)
        self.assertIn('[plugins.existing]', changed)
        self.assertEqual(install.tomllib.loads(changed)['model'], 'chosen-model')
        self.assertEqual(install.render_defaults(changed, desired), changed)

    def test_equal_defaults_do_not_rewrite_application_config(self):
        text = 'model = "chosen-model" # preserve comment\n'
        self.assertEqual(install.render_defaults(text, {'model': 'chosen-model'}), text)
        self.assertEqual(install.render_defaults(text, {}), text)

    def test_secret_or_unknown_defaults_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'config').mkdir()
            (root / 'config/codex.defaults.toml').write_text('api_key = "sentinel-secret"\n')
            with self.assertRaises(ValueError):
                install.load_defaults(root)


if __name__ == '__main__':
    unittest.main()
