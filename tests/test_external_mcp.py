import base64
import json
from pathlib import Path
import sys
import tempfile
import unittest

from eve_agent.external_mcp import ExternalMcpServers, validate_servers
from eve_agent.transport_access import transport_access

SERVER = r'''
import json, os, sys
from pathlib import Path
count = 0
for line in sys.stdin:
    req = json.loads(line)
    if 'id' not in req: continue
    method, params = req['method'], req.get('params', {})
    if method == 'initialize':
        result = {'protocolVersion':params['protocolVersion'], 'serverInfo':{'name':'fixture','version':'1'},
                  'instructions':'Native fixture instructions', 'capabilities':{'tools':{},'resources':{}}}
    elif method == 'tools/list':
        result = {'tools':[{'name':n,'description':n,'inputSchema':{'type':'object','properties':{},'additionalProperties':False},
                    'annotations':{'readOnlyHint':n == 'inspect'}} for n in ('change','inspect','fail','image','export','persist','restore')]}
    elif method == 'resources/list': result = {'resources':[{'uri':'fixture://state','name':'state'}]}
    elif method == 'resources/read': result = {'contents':[{'uri':params['uri'],'text':str(count)}]}
    else:
        name = params['name']
        if name == 'change': count += 1
        if name == 'export': Path('part.step').write_bytes(b'ISO-10303-21;fixture')
        if name == 'persist': Path('state.json').write_text(str(count))
        if name == 'restore': count = int(Path('state.json').read_text())
        result = {'content':[{'type':'text','text':json.dumps({'count':count,'cwd':os.getcwd(),'env':os.getenv('FIXTURE_WORKSPACE')})}]}
        if name == 'fail': result['isError'] = True
        if name == 'image': result['content'] = [{'type':'image','mimeType':'image/png','data':'aW1hZ2U='}]
    print(json.dumps({'jsonrpc':'2.0','id':req['id'],'result':result}), flush=True)
'''


class ExternalMcpTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cfg = {'servers': {'fixture': {'command': sys.executable, 'args': ['-u', '-c', SERVER],
                    'env': {'FIXTURE_WORKSPACE': '{workspace}'}}}}
        self.mcp = ExternalMcpServers(self.cfg, self.root)

    def tearDown(self):
        self.mcp.close_all()
        self.tmp.cleanup()

    def call(self, tool, conversation='one', args=None):
        return self.mcp.execute('mcp_fixture', tool, args or {}, conversation)

    @staticmethod
    def payload(result):
        return json.loads(result['result']['content'][0]['text'])

    def test_native_contract_and_conversation_sessions(self):
        contract = self.mcp.contracts('one')['mcp_fixture']
        self.assertEqual(contract['runtime']['server']['instructions'], 'Native fixture instructions')
        self.assertEqual(contract['operations']['inspect']['effect'], 'read')
        self.assertEqual(contract['operations']['change']['effect'], 'write')
        changed = self.payload(self.call('change'))
        self.assertEqual(changed['count'], 1)
        self.assertEqual(changed['env'], changed['cwd'])
        self.assertEqual(self.payload(self.call('inspect'))['count'], 1)
        self.assertEqual(self.payload(self.call('inspect', 'two'))['count'], 0)
        self.assertNotEqual(self.payload(self.call('inspect', 'two'))['cwd'], changed['cwd'])
        self.assertEqual(self.call('fail')['status'], 'failed')
        self.assertEqual(self.call('image')['resources'][0]['content'], 'data:image/png;base64,aW1hZ2U=')
        resources = self.call('eve_list_resources')['result']['resources']
        self.assertEqual(resources[0]['uri'], 'fixture://state')
        self.assertEqual(self.call('eve_read_resource', args={'uri': resources[0]['uri']})['result']['contents'][0]['text'], '1')

    def test_file_attachment_is_explicit_and_confined_including_symlinks(self):
        self.call('export')
        file = self.call('eve_attach_file', args={'path': 'part.step'})['resources'][0]
        self.assertEqual(file['type'], 'file')
        self.assertEqual(file['filename'], 'part.step')
        self.assertEqual(base64.b64decode(file['content'].partition(';base64,')[2]), b'ISO-10303-21;fixture')
        workspace = Path(self.payload(self.call('inspect'))['cwd'])
        outside = self.root / 'private.txt'
        outside.write_text('private')
        (workspace / 'escape').symlink_to(outside)
        for path in [str(outside), 'escape', '../private.txt']:
            with self.assertRaises(PermissionError): self.call('eve_attach_file', args={'path': path})
        with self.assertRaises(FileNotFoundError): self.call('eve_attach_file', 'two', {'path': 'part.step'})

    def test_transport_denial_does_not_start_server(self):
        with transport_access({}, public=True):
            self.assertEqual(self.mcp.contracts('one'), {})
            with self.assertRaises(PermissionError): self.call('change')
        self.assertEqual(self.mcp.sessions, {})

    def test_shared_scope_is_explicit(self):
        self.mcp.config['fixture']['scope'] = 'shared'
        self.call('change')
        self.assertEqual(self.payload(self.call('inspect', 'two'))['count'], 1)

    def test_unknown_execution_blocks_later_mutations(self):
        self.call('inspect')
        next(iter(self.mcp.sessions.values()))['uncertain'] = True
        self.assertEqual(self.payload(self.call('inspect'))['count'], 0)
        with self.assertRaisesRegex(RuntimeError, 'outcome unknown'): self.call('change')

    def test_configured_lifecycle_persists_and_restores_without_domain_logic(self):
        self.cfg['servers']['fixture'].update({
            'startup': [{'tool': 'restore', 'if_exists': '{workspace}/state.json'}],
            'after_write': [{'tool': 'persist'}]})
        self.mcp.close_all()
        self.mcp = ExternalMcpServers(self.cfg, self.root)
        self.call('change')
        self.call('change')
        self.mcp.close_all()
        self.mcp = ExternalMcpServers(self.cfg, self.root)
        self.assertEqual(self.payload(self.call('inspect'))['count'], 2)
        self.assertEqual(self.payload(self.call('inspect', 'two'))['count'], 0)

    def test_checkpoint_failure_does_not_disguise_success_or_retry_the_change(self):
        self.mcp.config['fixture']['after_write'] = [{'tool': 'fail'}]
        result = self.call('change')
        self.assertEqual(result['status'], 'completed')
        self.assertTrue(result['do_not_retry_operation'])
        self.assertIn('checkpoint_error', result)
        self.assertEqual(self.payload(self.call('inspect'))['count'], 1)
        with self.assertRaises(RuntimeError): self.call('change')

    def test_native_runtime_routes_resources_through_existing_answer_path(self):
        from types import SimpleNamespace
        from eve_agent.minimal import NativeToolRuntime
        agent = SimpleNamespace(external_mcp=self.mcp, conversation_id='one', _presentation_resources=[])
        runtime = NativeToolRuntime(agent)
        result, route = runtime._execute_direct('mcp_fixture', 'image', {}, {}, [])
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(agent._presentation_resources[0]['type'], 'image')
        with transport_access({}, public=True):
            with self.assertRaises(PermissionError):
                runtime._execute_direct('mcp_fixture', 'change', {}, {}, [])

    def test_thread_branch_retains_mcp_session_without_changing_other_conversations(self):
        from eve_agent.transport_access import update_transport_metadata
        self.mcp.config['fixture']['chatto_reply_mode'] = 'thread'
        def activity(event):
            self.assertEqual(event['reply_mode'], 'thread')
            update_transport_metadata({'mcp_session_id': 'stable-project'})
        with transport_access({'transport': 'chatto'}, activity=activity):
            self.call('change', 'room')
            self.assertEqual(self.payload(self.call('inspect', 'branched-thread'))['count'], 1)
        self.assertEqual(self.payload(self.call('inspect', 'other-room'))['count'], 0)

    def test_validation_rejects_bad_configuration(self):
        for cfg in [{'bad-name': {'command':'a'}}, {'okay':{'command':'a','scope':'guess'}},
                    {'okay':{'command':'a','timeout_seconds':True}}, {'okay':{'command':'a','args':'shell'}}]:
            with self.assertRaises(ValueError): validate_servers(cfg)


if __name__ == '__main__': unittest.main()
