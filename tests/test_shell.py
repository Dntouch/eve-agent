import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from eve_agent.config import ConfigError, editable_config, load_config, update_editable_config
from eve_agent.dialog import Route
from eve_agent.minimal import NativeToolRuntime
from eve_agent.shell import ShellCapability


class ShellTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.provider = ShellCapability({"enabled": True, "executable": "/bin/bash", "forbidden_commands": ["rm -rf"]}, self.root)
        self.addCleanup(self.provider.close_all)

    def run_command(self, command, **kwargs):
        return self.provider.execute_native_operation('execute', {'command': command, 'wait_seconds': 5, **kwargs})

    def test_actual_cwd_environment_pipelines_redirection_and_exit_code(self):
        work = self.root / 'work'; work.mkdir()
        result = self.run_command('printf "%s" "$EVE_SHELL_TEST" | tr a-z A-Z > result; cat result; printf err >&2; exit 7', cwd=str(work), env={'EVE_SHELL_TEST': 'works'})
        self.assertEqual('WORKS', result['stdout'])
        self.assertEqual('err', result['stderr'])
        self.assertEqual(7, result['exit_code'])
        self.assertEqual('failed', result['status'])
        self.assertEqual('WORKS', (work / 'result').read_text())

    def test_output_is_not_truncated_and_utf8_is_preserved(self):
        result = self.run_command("printf 'Grüße'; head -c 200000 /dev/zero | tr '\\0' x")
        self.assertEqual('Grüße' + 'x' * 200000, result['stdout'])
        self.assertEqual('completed', result['status'])

    def test_async_process_can_receive_input_eof_and_incremental_output(self):
        first = self.provider.execute_native_operation('execute', {'command': 'printf ready; read -r answer; printf "%s" "$answer"; cat', 'wait_seconds': 0})
        self.assertEqual('running', first['status'])
        second = self.provider.execute_native_operation('write', {'session_id': first['session_id'], 'text': 'hello\nrest', 'close_stdin': True, 'wait_seconds': 5})
        self.assertEqual('completed', second['status'])
        self.assertEqual('readyhellorest', first['stdout'] + second['stdout'])
        third = self.provider.execute_native_operation('poll', {'session_id': first['session_id'], 'wait_seconds': 0})
        self.assertEqual('', third['stdout'])
        self.assertEqual(0, third['exit_code'])

    def test_wait_is_not_an_execution_timeout_and_process_group_can_be_killed(self):
        first = self.provider.execute_native_operation('execute', {'command': 'sleep 30', 'wait_seconds': 0})
        self.assertIsNone(first['exit_code'])
        result = self.provider.execute_native_operation('terminate', {'session_id': first['session_id'], 'signal': 'SIGKILL', 'wait_seconds': 5})
        self.assertEqual('failed', result['status'])
        self.assertEqual(-9, result['exit_code'])

    def test_configured_rule_blocks_before_launch_including_short_option_variants(self):
        for command in ['rm -rf /test', 'rm   -fr /test', "'rm' '-rf' /test", 'rm -r -f /test', 'rm -rfv /test', '/usr/bin/rm -rf /test', 'echo ok; rm -rf /test', 'echo $(rm -rf /test)']:
            with self.subTest(command=command), patch('eve_agent.shell.subprocess.Popen') as launch:
                result = self.run_command(command)
                self.assertEqual('blocked', result['status'])
                self.assertEqual('rm -rf', result['matched_rule'])
                launch.assert_not_called()

    def test_rules_can_be_changed_and_cleared_without_restart(self):
        config = {'enabled': True, 'executable': '/bin/bash', 'forbidden_commands': ['printf forbidden']}
        self.provider.configure(config)
        self.assertEqual('blocked', self.run_command('printf forbidden')['status'])
        config['forbidden_commands'] = []
        self.provider.configure(config)
        self.assertEqual('forbidden', self.run_command('printf forbidden')['stdout'])
        self.assertEqual('allowed', self.run_command('printf allowed')['stdout'])

    def test_plain_rm_is_not_forbidden_by_recursive_force_rule(self):
        target = self.root / 'removable'; target.touch()
        self.assertEqual('completed', self.run_command('rm removable')['status'])
        self.assertFalse(target.exists())

    def test_disabled_shell_refuses_new_execution_and_existing_session_input(self):
        result = self.provider.execute_native_operation('execute', {'command': 'cat', 'wait_seconds': 0})
        self.provider.configure({'enabled': False})
        self.assertIsNone(self.provider.native_contract())
        self.assertEqual([], self.provider.self_descriptions())
        self.assertEqual('failed', self.run_command('printf test')['status'])
        self.assertEqual('failed', self.provider.execute_native_operation('write', {'session_id': result['session_id'], 'text': 'test'})['status'])

    def test_denylist_also_checks_stdin(self):
        result = self.provider.execute_native_operation('execute', {'command': 'cat', 'wait_seconds': 0})
        blocked = self.provider.execute_native_operation('write', {'session_id': result['session_id'], 'text': 'rm -rf /test\n'})
        self.assertEqual('blocked', blocked['status'])

    def test_failures_are_reported_without_invented_success(self):
        self.assertEqual('failed', self.run_command('true', cwd='/nonexistent-eve-shell-test')['status'])
        self.assertEqual('failed', self.provider.execute_native_operation('poll', {'session_id': 'missing'})['status'])
        self.provider.configure({'enabled': True, 'executable': '/nonexistent-eve-shell'})
        self.assertEqual('failed', self.run_command('true')['status'])

    def test_native_tool_schemas_and_dispatch(self):
        runtime = NativeToolRuntime.__new__(NativeToolRuntime)
        runtime.agent = SimpleNamespace(shell=self.provider)
        tools, bindings = runtime._native_tools({'shell': self.provider.native_contract()})
        self.assertEqual(4, len(tools))
        self.assertTrue(all(binding['capability'] == 'shell' for binding in bindings.values()))
        result, route = runtime._execute_direct('shell', 'execute', {'command': 'printf native', 'wait_seconds': 5}, {}, [])
        self.assertEqual(Route.SHELL, route)
        self.assertEqual('native', result['stdout'])

    def test_delayed_secret_output_stays_confidential_after_turn_scope_closes(self):
        from eve_agent.transient_credentials import credential_scope
        secret = 'Delayed-Only-Secret-9281'
        with credential_scope('Password: ' + secret) as scope:
            ref = '{{eve_secret:' + next(iter(scope.values)) + '}}'
            first = self.provider.execute_native_operation('execute', {
                'command': 'sleep .1; printf %s "$TEST_SECRET"', 'env': {'TEST_SECRET': ref}, 'wait_seconds': 0})
        result = self.provider.execute_native_operation('poll', {'session_id': first['session_id'], 'wait_seconds': 5})
        self.assertEqual('', first['stdout'] + result['stdout'])
        self.assertEqual('confidential', result['output_visibility'])
        self.assertTrue(self.provider.sessions[first['session_id']]['done'].is_set())

    def test_secret_written_to_existing_process_keeps_later_output_confidential(self):
        from eve_agent.transient_credentials import credential_scope
        first = self.provider.execute_native_operation('execute', {'command': 'read -r value; sleep .1; printf %s "$value"', 'wait_seconds': 0})
        with credential_scope('Password: Input-Only-Secret-1845') as scope:
            ref = '{{eve_secret:' + next(iter(scope.values)) + '}}'
            written = self.provider.execute_native_operation('write', {
                'session_id': first['session_id'], 'text': ref + '\n', 'wait_seconds': 0})
        result = self.provider.execute_native_operation('poll', {'session_id': first['session_id'], 'wait_seconds': 5})
        self.assertEqual('', written['stdout'] + result['stdout'])
        self.assertEqual('confidential', result['output_visibility'])

    def test_credential_slices_and_encoded_stderr_are_confidential(self):
        from eve_agent.transient_credentials import credential_scope
        with credential_scope('Password: Test-Secret-1845') as scope:
            ref = '{{eve_secret:' + next(iter(scope.values)) + '}}'
            result = self.provider.execute_native_operation('execute', {
                'command': 'printf %s "${VALUE:0:3}"; printf %s "$VALUE" | base64 >&2; exit 7',
                'env': {'VALUE': ref}, 'wait_seconds': 5})
        self.assertEqual('failed', result['status'])
        self.assertEqual(7, result['exit_code'])
        self.assertEqual('confidential', result['output_visibility'])
        self.assertEqual('', result['stdout'])
        self.assertEqual('', result['stderr'])
        session = self.provider.sessions[result['session_id']]
        self.assertEqual([], session['stdout'])
        self.assertEqual([], session['stderr'])
        self.assertNotIn('Test-Secret-1845', repr(session['process'].args))
        public = self.run_command('printf public-status')
        self.assertEqual('public-status', public['stdout'])
        self.assertEqual('public', public['output_visibility'])

    def test_configuration_roundtrip_and_validation(self):
        path = self.root / 'eve.json'; path.write_text('{}')
        update_editable_config(path, {'values': {'shell.enabled': True, 'shell.forbidden_commands': ['rm -rf', 'printf forbidden']}}, environ={})
        config = load_config(path, environ={})[1]['shell']
        self.assertTrue(config['enabled'])
        self.assertEqual(['rm -rf', 'printf forbidden'], config['forbidden_commands'])
        fields = next(section for section in editable_config(path, environ={})['sections'] if section['id'] == 'shell')['fields']
        self.assertTrue(all(not field['restart_required'] for field in fields))
        for value in ['rm -rf', [None], [''], ['# comment']]:
            with self.subTest(value=value), self.assertRaises(ConfigError):
                update_editable_config(path, {'values': {'shell.forbidden_commands': value}}, environ={})
        update_editable_config(path, {'values': {'shell.forbidden_commands': []}}, environ={})
        self.assertEqual([], load_config(path, environ={})[1]['shell']['forbidden_commands'])
