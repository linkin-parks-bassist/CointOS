"""Opt-in native V2 checks. Run inside a disposable, uniquely named user scope.

COINTOS_NATIVE_OPENCODE2=1 python3 -m unittest tests.test_opencode2_native
Only local stub providers and disposable stores are used; no model gateway calls.
"""
import io
import hashlib
import fcntl
import json
import os
from pathlib import Path
import subprocess
import select
import struct
import tempfile
import threading
import time
import termios
import copy
from unittest.mock import patch
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from cointos import messages, opencode, opencode2, sessions, transcript

SUMMARY = ('## Objective\n- Fixture.\n\n## Requirements\n- (none)\n\n## Decisions\n- (none)\n\n'
           '## Work State\n### Completed\n- Stub reply.\n### Active\n- (none)\n### Blocked\n- (none)\n\n'
           '## Next Move\n1. (none)\n\n## Relevant Files\n- (none)\n\n## Important Context\n- (none)')


class Provider(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers['content-length'])))
        self.server.requests.append(request)
        self.send_response(200)
        self.send_header('content-type', 'text/event-stream')
        self.end_headers()
        if self.server.block and any(m.get('role') == 'tool' for m in request['messages']):
            self.server.blocked.set()
            self.server.release.wait(20)
            return
        summary = any('structured summary' in str(m.get('content')) for m in request['messages'])
        if self.server.tool and not summary:
            name, arguments = self.server.tool
            self.server.tool = None
            deltas = [({'role': 'assistant', 'tool_calls': [{'index': 0, 'id': 'call_once', 'type': 'function',
                        'function': {'name': name, 'arguments': json.dumps(arguments)}}]}, None), ({}, 'tool_calls')]
        else:
            reasoning = self.server.reasoning and not summary
            self.server.reasoning = False
            deltas = [({'role': 'assistant', 'reasoning_content' if reasoning else 'content':
                        SUMMARY if summary else 'Native fixture complete.'}, None), ({}, 'unknown' if reasoning else 'stop')]
        try:
            for delta, finish in deltas:
                chunk = {'id': 'fixture', 'object': 'chat.completion.chunk', 'created': int(time.time()),
                         'model': 'test', 'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish}]}
                self.wfile.write(b'data: ' + json.dumps(chunk).encode() + b'\n\n')
                self.wfile.flush()
                if self.server.partial and (delta.get('content') or delta.get('reasoning_content')):
                    self.server.blocked.set()
                    self.server.release.wait(20)
            self.wfile.write(b'data: [DONE]\n\n')
        except (BrokenPipeError, ConnectionResetError):
            pass


@unittest.skipUnless(os.environ.get('COINTOS_NATIVE_OPENCODE2') == '1', 'opt-in native V2 fixture')
class NativeV2(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory(prefix='cointos-opencode2-native-')))
        for name in ('run', 'work', 'store', 'run/scratch'):
            (self.root / name).mkdir(mode=0o700)
        self.stub = ThreadingHTTPServer(('127.0.0.1', 0), Provider)
        self.stub.requests, self.stub.tool, self.stub.block, self.stub.partial = [], None, False, False
        self.stub.reasoning = False
        self.stub.blocked, self.stub.release = threading.Event(), threading.Event()
        threading.Thread(target=self.stub.serve_forever, daemon=True).start()
        self.addCleanup(self.stub.server_close)
        self.addCleanup(self.stub.shutdown)
        self.addCleanup(self.stub.release.set)
        self.run, self.store, self.work = (self.root / n for n in ('run', 'store', 'work'))
        fixture = self.root / 'mcp.py'
        fixture.write_text('''import json, sys
from pathlib import Path
for line in sys.stdin:
 m=json.loads(line)
 if 'id' not in m: continue
 if m['method']=='initialize':
  r={'protocolVersion':'2024-11-05','capabilities':{'tools':{}},'serverInfo':{'name':'fixture','version':'1'}}
 elif m['method']=='tools/list':
  r={'tools':[{'name':'echo','description':'Echo fixture text.','inputSchema':{'type':'object','properties':{'text':{'type':'string'}},'required':['text'],'additionalProperties':False}}]}
 elif m['method']=='tools/call':
  with Path(__file__).with_name('mcp-requests').open('a') as f: f.write(json.dumps(m['params'])+'\\n')
  unknown=set(m['params']['arguments'])-{'text'}
  if unknown: r={'content':[{'type':'text','text':'unsupported argument(s): '+', '.join(sorted(unknown))}], 'isError':True}
  else:
   with Path(__file__).with_name('mcp-calls').open('a') as f: f.write(json.dumps(m['params'])+'\\n')
   r={'content':[{'type':'text','text':m['params']['arguments']['text']}]}
 else: r={}
 print(json.dumps({'jsonrpc':'2.0','id':m['id'],'result':r}),flush=True)
''')
        self.cfg = {'model': 'fixture/test', 'small_model': 'fixture/test', 'autoupdate': False, 'share': 'disabled',
                    'provider': {'fixture': {'npm': '@ai-sdk/openai-compatible',
                        'options': {'baseURL': f'http://127.0.0.1:{self.stub.server_port}/v1', 'apiKey': 'fixture'},
                        'models': {'test': {'name': 'Fixture', 'limit': {'context': 131072, 'output': 1024}}}}},
                    'mcp': {'cointos': {'type': 'local', 'command': ['python3', str(fixture)]}},
                    'permission': {'*': 'allow', 'shell': {'*': 'allow', 'printf forbidden*': 'deny'}},
                    'plugin': [str(opencode.ROOT / 'cointos/opencode_plugin')], 'compaction': {'auto': False}}
        (self.run / 'opencode.json').write_text(json.dumps(self.cfg))
        (self.store / 'models.json').write_text('{}')
        self.env = sessions.environment(self.run, self.store, self.store / 'models.json')
        self.env.update(COINTOS_OPENCODE_BINARY=opencode.OPENCODE2, COINTOS_OPENCODE_V2='1',
                        COINTOS_PROVIDER='fixture',
                        OPENCODE_PASSWORD='disposable-native-fixture', PWD=str(self.work),
                        TMPDIR=str(self.run / 'scratch'), COINTOS_WRITE_PATHS=json.dumps([str(self.root), '/dev/null']),
                        COINTOS_COMPACTION_CONTEXT_COMMAND=json.dumps(['printf', 'Verified fixture context.']))
        self.server, self.url = opencode.start_server(self.run, str(self.work), self.env)
        self.addCleanup(self.server.wait)
        self.addCleanup(opencode.stop_group, self.server.pid)
        token = opencode2.AUTH.set(self.env['OPENCODE_PASSWORD'])
        self.addCleanup(opencode2.AUTH.reset, token)

    def create(self):
        return opencode2.request(self.url, 'session', {'title': 'Native fixture',
            'model': {'providerID': 'fixture', 'id': 'test'}, 'location': {'directory': str(self.work)}})['data']['id']

    def wait(self, session):
        opencode2.request(self.url, 'experimental/' + opencode2.path(session, 'wait'), {})

    def test_interrupted_tool_effect_is_not_repeated_by_source_resume(self):
        count = self.work / 'count'
        self.stub.tool, self.stub.block = ('shell', {'command': f'printf x >> {count}'}), True
        session = self.create()
        user = opencode2.request(self.url, opencode2.path(session, 'prompt'), {'text': 'Execute once.'})['data']['id']
        self.assertTrue(self.stub.blocked.wait(15))
        opencode2.request(self.url, opencode2.path(session, 'interrupt'), {})
        before = next(m for m in opencode2.messages(self.url, session) if m['id'] == user)
        self.stub.block = False; self.stub.release.set()
        output = io.BytesIO()
        self.assertEqual(opencode2.resume(self.url, session, output), 0)
        history = opencode2.messages(self.url, session)
        self.assertEqual([m for m in history if m['type'] == 'user'], [before])
        self.assertEqual(count.read_text(), 'x')
        self.assertIn('"reason": "stop"', output.getvalue().decode())
        db = self.store / 'data/opencode/opencode.db'
        text, _ = transcript.render(db, [session])
        self.assertIn('[tool shell completed]', text)
        found = transcript.entries(db, [session])
        self.assertEqual(len([e for e in found if e['kind'] == 'user']), 1)
        self.assertTrue(any(e['kind'] == 'system' and 'Continue the interrupted turn.' in e['text'] for e in found))

    def test_native_compaction_persists_the_factual_anchor(self):
        session = self.create()
        opencode2.request(self.url, opencode2.path(session, 'prompt'), {'text': 'Keep this context.'})
        self.wait(session)
        opencode2.request(self.url, opencode2.path(session, 'compact'), {})
        self.wait(session)
        compact = next(m for m in reversed(opencode2.messages(self.url, session)) if m['type'] == 'compaction')
        self.assertEqual(compact['status'], 'completed', compact)
        self.assertIn('Verified fixture context.', compact['summary'])
        self.assertIn('Verified fixture context.', transcript.render(self.store / 'data/opencode/opencode.db', [session])[0])

    def test_source_finishes_interrupted_compaction_before_recovery_input(self):
        session = self.create()
        opencode2.request(self.url, opencode2.path(session, 'prompt'), {'text': 'Keep this original task.'})
        self.wait(session)
        self.stub.partial = True
        opencode2.request(self.url, opencode2.path(session, 'compact'), {})
        self.assertTrue(self.stub.blocked.wait(15))
        opencode2.request(self.url, opencode2.path(session, 'interrupt'), {})
        self.stub.partial = False; self.stub.release.set()
        self.assertTrue(opencode2.finish_compaction(self.url, session))
        history = opencode2.messages(self.url, session)
        self.assertEqual(next(m for m in reversed(history) if m['type'] == 'compaction')['status'], 'completed')
        self.assertEqual(len([m for m in history if m['type'] == 'user']), 1)

    def test_offline_trace_preserves_the_current_turn_while_native_text_is_in_progress(self):
        self.stub.partial = True
        session = self.create()
        opencode2.request(self.url, opencode2.path(session, 'prompt'), {'text': 'Stream this fixture.'})
        self.assertTrue(self.stub.blocked.wait(15))
        shown = transcript.render(self.store / 'data/opencode/opencode.db', [session])[0]
        self.assertIn('Stream this fixture.', shown)
        self.stub.release.set(); self.wait(session)
        self.assertIn('Native fixture complete.', transcript.render(self.store / 'data/opencode/opencode.db', [session])[0])

    def test_peer_guidance_does_not_interrupt_writing_and_repeated_admission_is_idempotent(self):
        self.stub.partial = True
        session = self.create()
        opencode2.request(self.url, opencode2.path(session, 'prompt'), {'text': 'Write the fixture response.'})
        self.assertTrue(self.stub.blocked.wait(15))
        for _ in range(2):
            messages.post_native(self.url, session, '<message>New peer guidance.</message>',
                                 self.env['OPENCODE_PASSWORD'], 'msg_cointos_fixture_delivery')
        history = opencode2.messages(self.url, session)
        self.assertFalse(any(m.get('error', {}).get('type') == 'aborted' for m in history))
        self.stub.partial = False; self.stub.release.set(); self.wait(session)
        history = opencode2.messages(self.url, session)
        self.assertEqual(sum(m.get('text') == '<message>New peer guidance.</message>' for m in history), 1)
        self.assertTrue(any(any('New peer guidance.' in str(m.get('content')) for m in req['messages'])
                            for req in self.stub.requests[1:]))

    def test_reasoning_only_yield_rereads_the_admitted_peer_message(self):
        self.stub.partial = self.stub.reasoning = True
        session = self.create()
        opencode2.request(self.url, opencode2.path(session, 'prompt'), {'text': 'Think, then follow peer guidance.'})
        self.assertTrue(self.stub.blocked.wait(15))
        messages.post_native(self.url, session, '<message>Reasoning boundary guidance.</message>',
                             self.env['OPENCODE_PASSWORD'], 'msg_cointos_reasoning_delivery')
        self.stub.partial = False; self.stub.release.set(); self.wait(session)
        history = opencode2.messages(self.url, session)
        self.assertTrue(any(m.get('finish') == 'stop' for m in history), history)
        self.assertTrue(any(any('Reasoning boundary guidance.' in str(m.get('content')) for m in req['messages'])
                            for req in self.stub.requests[1:]))

    def test_native_mcp_dispatch_keeps_the_registered_server_and_result(self):
        self.stub.tool = ('execute', {'code': 'return await tools.cointos.echo({text:"MCP fixture result"})'})
        session = self.create()
        opencode2.request(self.url, opencode2.path(session, 'prompt'), {'text': 'Use the registered fixture.'})
        self.wait(session)
        calls = [p for m in opencode2.messages(self.url, session) for p in m.get('content', []) if p['type'] == 'tool']
        self.assertTrue(calls)
        self.assertEqual(calls[0]['state']['status'], 'completed', calls)
        self.assertIn('MCP fixture result', json.dumps(calls[0]['state']))

    def test_native_mcp_preserves_unknown_fields_for_broker_refusal(self):
        self.stub.tool = ('execute', {'code':
            'return await tools.cointos.echo({text:"Must not dispatch",undeclared_field:40})'})
        session = self.create()
        opencode2.request(self.url, opencode2.path(session, 'prompt'), {'text': 'Exercise invalid MCP input.'})
        self.wait(session)
        self.assertFalse((self.root / 'mcp-calls').exists(), 'V2 silently stripped an undeclared argument')
        history = json.dumps(opencode2.messages(self.url, session))
        self.assertIn('unsupported argument(s): undeclared_field', history)
        requests = [json.loads(line) for line in (self.root / 'mcp-requests').read_text().splitlines()]
        self.assertEqual(requests[0]['arguments']['undeclared_field'], 40)
        # The same registered tool still executes valid input.
        self.stub.tool = ('execute', {'code': 'return await tools.cointos.echo({text:"Valid dispatch"})'})
        opencode2.request(self.url, opencode2.path(session, 'prompt'), {'text': 'Now use valid MCP input.'})
        self.wait(session)
        calls = [json.loads(line) for line in (self.root / 'mcp-calls').read_text().splitlines()]
        self.assertEqual([(call['name'], call['arguments']) for call in calls],
                         [('echo', {'text': 'Valid dispatch'})])
        opencode2.request(self.url, 'location/reload', {})
        # Reloading the adapter retains the session and does not repeat effects.
        self.assertIn('Valid dispatch', json.dumps(opencode2.messages(self.url, session)))
        self.assertEqual((self.root / 'mcp-calls').read_text().splitlines(),
                         [json.dumps(calls[0])])

    def test_native_shell_denial_prevents_the_effect(self):
        forbidden = self.work / 'forbidden'
        self.stub.tool = ('shell', {'command': f'printf forbidden >> {forbidden}'})
        session = self.create()
        opencode2.request(self.url, opencode2.path(session, 'prompt'), {'text': 'Exercise a denied operation.'})
        self.wait(session)
        calls = [p for m in opencode2.messages(self.url, session) for p in m.get('content', []) if p['type'] == 'tool']
        self.assertEqual(calls[0]['state']['status'], 'error', calls)
        self.assertFalse(forbidden.exists())

    def test_offline_trace_reads_the_persisted_running_tool_projection(self):
        ready, release = self.work / 'ready', self.work / 'release'
        command = f'printf x > {ready}; while [ ! -f {release} ]; do sleep 0.05; done'
        self.stub.tool = ('shell', {'command': command, 'timeout': 15000})
        session = self.create()
        opencode2.request(self.url, opencode2.path(session, 'prompt'), {'text': 'Observe this controlled tool.'})
        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and not ready.exists():
                time.sleep(.1)
            self.assertTrue(ready.exists())
            shown = transcript.render(self.store / 'data/opencode/opencode.db', [session])[0]
            self.assertIn('[tool shell running]', shown)
            self.assertIn(command, shown)
        finally:
            release.touch()
            self.wait(session)

    def test_managed_cli_uses_private_server_and_emits_terminal_events(self):
        result = subprocess.run([opencode.OPENCODE2, 'run', '--server', self.url, '--format', 'json', '--auto',
                                 '--title', 'Native fixture', '--model', 'fixture/test', 'Use this fixture.'],
                                cwd=self.work, env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        events = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertTrue(any(e['type'] == 'step_finish' and e['part']['reason'] == 'stop' for e in events))
        self.assertEqual(opencode2.request(self.url, 'info')['paths']['tmp'], str(self.run / 'scratch/opencode'))

    def test_source_supervisor_launches_v2_in_the_explicit_worktree(self):
        run, store = self.root / 'supervisor-run', self.root / 'supervisor-store'
        run.mkdir(); (run / 'scratch').mkdir(); store.mkdir()
        config = copy.deepcopy(opencode.load_config())
        config.update(opencode_v2=True, port=self.stub.server_port, work_model='fixture',
                      models={'fixture': {'ctx_size': 131072, 'lanes': 1}}, projects=[])
        task = {'id': 'system:fixture', 'role': 'worker', 'worktree': str(self.work)}
        with patch.object(opencode.stations, 'servers', return_value={}):
            cfg = opencode.settings(config, 'disposable-fixture', task, [])
        # Only broker transport is replaced; model/provider settings are the actual launch output.
        cfg['mcp'] = self.cfg['mcp']
        self.stub.tool = ('execute', {'code': 'return await tools.cointos.echo({text:"Full configuration reached MCP"})'})
        (run / 'opencode.json').write_text(json.dumps(cfg))
        password = run / 'server-password'; password.write_text('disposable-supervisor-fixture'); password.chmod(0o600)
        (store / 'models.json').write_text('{}')
        spec = {'protocol': 2, 'task': {'id': 'system:fixture', 'worktree': str(self.work)},
                'command': [opencode.OPENCODE2, 'run', '--format', 'json', '--auto', '--model', 'cointos/default',
                            '--title', 'Supervisor fixture'], 'session': None, 'text': 'Run this fixture.',
                'agent_data': str(store), 'write_paths': [str(self.root), '/dev/null'], 'read_paths': None,
                'model': {'providerID': 'cointos', 'modelID': 'default'}}
        (run / 'run.json').write_text(json.dumps(spec))
        opencode.serve_run(run)
        self.assertEqual(json.loads((run / 'exit.json').read_text())['code'], 0)
        self.assertEqual(json.loads((run / 'server.json').read_text())['protocol'], 2)
        events = [json.loads(line) for line in (run / 'events.jsonl').read_text().splitlines()]
        self.assertTrue(any(e['type'] == 'step_finish' and e['part']['reason'] == 'stop' for e in events))
        self.assertTrue(any(e.get('part', {}).get('state', {}).get('status') == 'completed'
                            and 'Full configuration reached MCP' in json.dumps(e) for e in events), events)

    def test_native_terminal_attaches_to_the_owned_private_session(self):
        session = self.create()
        master, slave = os.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 40, 120, 0, 0))
        window = subprocess.Popen([opencode.OPENCODE2, '--server', self.url, '--session', session],
                                  cwd=self.work, env={**self.env, 'TERM': 'xterm-256color'},
                                  stdin=slave, stdout=slave, stderr=slave)
        os.close(slave)
        raw = b''
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline and window.poll() is None:
                if select.select([master], [], [], .2)[0]:
                    raw += os.read(master, 65536)
                    if b'Native fixture' in raw:
                        break
            self.assertIn(b'Native fixture', raw, raw[-2000:])
            self.assertIsNone(window.poll())
        finally:
            window.terminate()
            try:
                window.wait(timeout=5)
            except subprocess.TimeoutExpired:
                window.kill(); window.wait()
            os.close(master)

    def test_source_migrates_only_the_assigned_legacy_conversation(self):
        legacy_run, legacy_store = self.root / 'legacy-run', self.root / 'legacy-store'
        legacy_run.mkdir(); legacy_store.mkdir()
        cfg = {**self.cfg, 'plugin': [], 'mcp': {}}
        (legacy_run / 'opencode.json').write_text(json.dumps(cfg))
        (legacy_store / 'models.json').write_text('{}')
        env = sessions.environment(legacy_run, legacy_store, legacy_store / 'models.json')
        env['PWD'] = str(self.work)
        result = subprocess.run([opencode.LEGACY_OPENCODE, 'run', '--pure', '--dir', str(self.work),
                                 '--format', 'json', '--model', 'fixture/test', 'Retain this original task.'],
                                cwd=self.work, env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        session = next(json.loads(line)['sessionID'] for line in result.stdout.splitlines() if 'sessionID' in json.loads(line))
        task = {'id': 'fixture:retained', 'session': session, 'worktree': str(self.work), 'session_store': str(legacy_store)}
        target, run = self.root / 'converted/v2', self.root / 'converted-run'
        target.mkdir(parents=True); run.mkdir()
        (target / 'models.json').write_text('{}'); (run / 'opencode.json').write_text(json.dumps(self.cfg))
        sessions.prepare_v2(task, run, target, opencode.OPENCODE2, opencode.LEGACY_OPENCODE, 30)
        receipt = (sessions.STATE / 'session-migrations-v2' / hashlib.sha256(task['id'].encode()).hexdigest()
                   / hashlib.sha256(session.encode()).hexdigest() / 'receipt.json')
        self.assertEqual(json.loads(receipt.read_text())['session'], session)
        self.assertFalse(receipt.is_relative_to(target), 'a managed tool must not be able to forge its migration receipt')
        self.assertTrue((legacy_store / 'data/opencode/opencode.db').is_file())
        retry = self.root / 'retry-run'; retry.mkdir()
        (retry / 'opencode.json').write_text(json.dumps(self.cfg))
        # A completed preparation survives lost publication of session_store.
        sessions.prepare_v2(task, retry, target, opencode.OPENCODE2, opencode.LEGACY_OPENCODE, 30)

    def test_source_recognises_an_already_native_private_conversation(self):
        session = self.create()
        opencode2.request(self.url, opencode2.path(session, 'prompt'), {'text': 'Retain native history.'})
        self.wait(session)
        before = opencode2.messages(self.url, session)
        run = self.root / 'native-resume'; run.mkdir()
        (run / 'opencode.json').write_text(json.dumps(self.cfg))
        task = {'id': 'fixture:native', 'session': session, 'worktree': str(self.work), 'session_store': str(self.store)}
        sessions.prepare_v2(task, run, self.store, opencode.OPENCODE2, opencode.LEGACY_OPENCODE, 30)
        self.assertEqual(opencode2.messages(self.url, session), before)

    def test_coin_view_replays_tool_results_without_executing_coin_controls(self):
        from cointos.coin_mirror_v2 import Mirror
        mirror = Mirror(self.root / 'coin-view', opencode.OPENCODE2)
        mirror.name = 'Synthetic Professional'
        mirror.start()
        try:
            mirror.feed({'kind': 'user', 'text': 'Fixture view.'})
            mirror.feed({'kind': 'assistant', 'reasoning': 'Observed reasoning.', 'content': 'Observed words.'})
            mirror.feed({'kind': 'tool', 'name': 'send', 'input': {'message': 'Recorded only.'}, 'output': 'recorded result'})
            mirror.feed({'kind': 'assistant', 'content': 'After recorded tool.'})
            mirror.idle()
            mirror.call('/api/experimental/session/' + mirror.session + '/wait', {})
            history = mirror.call('/api/experimental/session/' + mirror.session + '/export')['data']['messages']
            calls = [p for m in history for p in m.get('content', []) if p['type'] == 'tool']
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0]['name'], 'coin_observation')
            self.assertEqual(calls[0]['state']['content'][0]['text'], 'recorded result')
            self.assertTrue(any(p.get('text') == 'After recorded tool.' for m in history for p in m.get('content', [])))
            mirror.call('/api/session/' + mirror.session + '/prompt', {'text': 'Please send a new message.'})
            mirror.call('/api/experimental/session/' + mirror.session + '/wait', {})
            history = mirror.call('/api/experimental/session/' + mirror.session + '/export')['data']['messages']
            self.assertTrue(any('This window only shows Synthetic Professional.' in p.get('text', '')
                                for m in history for p in m.get('content', [])))
            self.assertEqual(len(mirror.stand_in.results), 1)
        finally:
            mirror.stop()
