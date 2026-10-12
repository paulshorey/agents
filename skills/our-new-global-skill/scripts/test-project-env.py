#!/usr/bin/env python3
"""Provider-free tests for the map's shell-only environment boundary."""
import importlib.util
import io
import os
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("project_env", Path(__file__).with_name("project-env.py"))
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


class EnvironmentTests(unittest.TestCase):
    def test_shell_only_never_loads_dotenv_values(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.env').write_text('PROJECT_SECRET=dotenv\n')
            (root / '.env.example').write_text('PROJECT_SECRET=\n')
            with patch.object(helper, 'project_root', return_value=root), \
                 patch.object(helper, 'login_environment', return_value={'PROJECT_SECRET': 'shell'}), \
                 patch.dict(os.environ, {}, clear=True):
                env, files, declared = helper.build_environment(root, set(), shell_only=True)
                self.assertEqual(env['PROJECT_SECRET'], 'shell')
                self.assertEqual(files, [])
                self.assertIn('PROJECT_SECRET', declared)

    def test_other_projects_retain_dotenv_precedence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.env').write_text('PROJECT_SECRET=dotenv\n')
            with patch.object(helper, 'project_root', return_value=root), \
                 patch.object(helper, 'login_environment', return_value={'PROJECT_SECRET': 'shell'}), \
                 patch.dict(os.environ, {}, clear=True):
                env, files, _ = helper.build_environment(root, set())
                self.assertEqual(env['PROJECT_SECRET'], 'dotenv')
                self.assertEqual(files, [root / '.env'])
                self.assertEqual(dict(os.environ), {})

    def run_main(self, directory, environment, arguments):
        output = io.StringIO()
        with patch.object(helper, 'build_environment', return_value=(environment, [], {'REQUIRED', 'OPTIONAL'})), \
             patch.object(helper.os, 'execvpe') as execute, \
             patch.object(helper.os, 'chdir'), \
             patch.object(helper.sys, 'argv', ['project-env.py', '--cwd', directory, *arguments]), \
             redirect_stdout(output), redirect_stderr(output):
            result = helper.main()
        return result, output.getvalue(), execute

    def test_missing_required_variable_prevents_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            result, output, execute = self.run_main(directory, {}, ['--require', 'REQUIRED', '--', 'test-command'])
        self.assertEqual(result, 78)
        self.assertIn('missing required environment names: REQUIRED', output)
        execute.assert_not_called()

    def test_empty_required_variable_prevents_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            result, _, execute = self.run_main(directory, {'REQUIRED': ''}, ['--require', 'REQUIRED', '--', 'test-command'])
        self.assertEqual(result, 78)
        execute.assert_not_called()

    def test_optional_example_variable_does_not_prevent_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            result, output, execute = self.run_main(directory, {'REQUIRED': 'private-fixture'}, ['--require', 'REQUIRED', '--', 'test-command'])
        self.assertEqual(result, 0)
        execute.assert_called_once_with('test-command', ['test-command'], {'REQUIRED': 'private-fixture'})
        self.assertNotIn('private-fixture', output)

    def test_check_reports_optional_names_without_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            result, output, execute = self.run_main(directory, {'REQUIRED': 'private-fixture'}, ['--check', '--require', 'REQUIRED'])
        self.assertEqual(result, 0)
        self.assertIn('Missing names: OPTIONAL', output)
        self.assertNotIn('private-fixture', output)
        execute.assert_not_called()

    def test_check_fails_for_explicit_requirement(self):
        with tempfile.TemporaryDirectory() as directory:
            result, output, execute = self.run_main(directory, {}, ['--check', '--require', 'REQUIRED'])
        self.assertEqual(result, 1)
        self.assertIn('Missing required names: REQUIRED', output)
        execute.assert_not_called()

    def test_required_undeclared_shell_variable_is_imported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(helper, 'project_root', return_value=root), \
                 patch.object(helper, 'login_environment', return_value={'UNDECLARED_SECRET': 'shell-fixture'}), \
                 patch.dict(os.environ, {}, clear=True):
                environment, files, declared = helper.build_environment(root, {'UNDECLARED_SECRET'}, shell_only=True)
        self.assertEqual(environment['UNDECLARED_SECRET'], 'shell-fixture')
        self.assertEqual(declared, {'UNDECLARED_SECRET'})
        self.assertEqual(files, [])


if __name__ == '__main__':
    unittest.main()
