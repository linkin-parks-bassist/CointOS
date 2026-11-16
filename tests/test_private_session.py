import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cointos import gateway, lanes, private_clients, private_session, snapshots, state


class PrivateSession(unittest.TestCase):
    @unittest.skipUnless(Path.home().joinpath('.local/lib/opencode/2.3.0/opencode').exists(), 'requires installed launcher binary')
    def test_terminal_resize_reaches_the_detached_child(self):
        import fcntl
        import pty
        import select
        import signal
        import struct
        import subprocess
        import sys
        import termios
        import time
        master, slave = pty.openpty()
        self.addCleanup(os.close, master)
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 24, 80, 0, 0))
        stub = """import fcntl,termios,struct,signal,time
def resize(*_):
 r,c,_,_=struct.unpack('HHHH',fcntl.ioctl(0,termios.TIOCGWINSZ,b'\\0'*8))
 print('SIZE',r,c,flush=True)
signal.signal(signal.SIGWINCH,resize)
print('READY',flush=True)
while True: time.sleep(1)
"""
        script = """import subprocess,sys
from cointos import private_session
real=subprocess.Popen
def launch(command,**kw):
 if command[0].endswith('/2.3.0/opencode'): command=[sys.executable,'-u','-c',%r]
 return real(command,**kw)
private_session.subprocess.Popen=launch
raise SystemExit(private_session.main([]))
""" % stub
        def terminal():
            os.setsid()
            fcntl.ioctl(0, termios.TIOCSCTTY, 0)
        process = subprocess.Popen([sys.executable, '-u', '-c', script], stdin=slave, stdout=slave,
            stderr=slave, preexec_fn=terminal, env={**os.environ,
                'PYTHONPATH': str(Path(__file__).resolve().parents[1])})
        os.close(slave)
        def await_text(marker):
            output = b''
            deadline = time.monotonic() + 5
            while marker not in output and time.monotonic() < deadline:
                if select.select([master], [], [], .1)[0]:
                    output += os.read(master, 4096)
            self.assertIn(marker, output)
        try:
            await_text(b'READY')
            fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack('HHHH', 41, 131, 0, 0))
            await_text(b'SIZE 41 131')
        finally:
            process.terminate()
            process.wait(timeout=5)

    def test_private_cache_survives_tool_gaps_but_not_client_exit_or_pid_reuse(self):
        self.enterContext(patch.dict(state.L, {'agents': {}, 'thoughts': {}, 'tasks': {}, 'lanes': [], 'history': []}))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            directory = root / 'cointos-private-fixture'
            directory.mkdir()
            with patch.object(private_clients, 'DIRECTORY', root):
                owner = private_clients.register(directory, 'synthetic-key')
                self.assertTrue(snapshots.live(owner))
                with patch.object(lanes.BACKEND, 'release_residents') as release:
                    lanes.retire_residents(state.CONFIG['work_model'], [owner])
                    release.assert_not_called()
                with patch.object(private_clients.wakeups, 'process', return_value=None):
                    self.assertFalse(snapshots.live(owner))
                    with patch.object(lanes.BACKEND, 'release_residents') as release:
                        lanes.retire_residents(state.CONFIG['work_model'], [owner])
                        release.assert_called_once()
                with patch.object(private_clients.wakeups, 'process', return_value={'state':'S','start_ticks':-1}):
                    self.assertFalse(snapshots.live(owner))
                with patch.object(private_clients.wakeups, 'process', return_value={'state':'Z','start_ticks':-1}):
                    self.assertFalse(snapshots.live(owner))
                with patch.object(snapshots.BACKEND, 'save') as save:
                    self.assertFalse(snapshots.keep(0, [1,2], 'shared', 'checkpoint', owner))
                    save.assert_not_called()

    def test_render_skips_capture_and_tool_history(self):
        model = state.CONFIG['work_model']
        with patch.object(gateway.BACKEND, 'render', return_value={'tokens': [1], 'reader': {}}), \
             patch.object(gateway, '_capture_steer_request') as capture, \
             patch.object(gateway, '_prepare_tool_history') as history:
            result = gateway.render_request({'messages': [{'role': 'user', 'content': 'synthetic'}]},
                                            'user', model, {}, protocol=0, private=True)
        self.assertTrue(result['private'])
        capture.assert_not_called()
        history.assert_not_called()

    def test_private_roundtrip_retains_exact_boundary_before_mutable_message(self):
        model = state.CONFIG['work_model']
        with patch.object(gateway.BACKEND, 'render', side_effect=[
                {'tokens': [1, 2, 3, 4, 5, 6], 'reader': {}},
                {'tokens': [1, 2, 3, 9], 'reader': {}}]), \
                patch.object(gateway, '_capture_steer_request') as capture, \
                patch.object(gateway, '_prepare_tool_history') as history:
            result = gateway.render_request({'messages': [
                {'role': 'user', 'content': 'synthetic earlier turn'},
                {'role': 'assistant', 'content': 'synthetic reply'},
                {'role': 'user', 'content': 'synthetic mutable tail'}]},
                'user', model, {}, protocol=0, private=True)
        self.assertEqual(result['retained_prefix'], 3)
        self.assertTrue(result['private'])
        capture.assert_not_called()
        history.assert_not_called()

    def test_public_standard_prefix_is_shared_but_private_requests_never_publish_it(self):
        model = state.CONFIG['work_model']
        body = {'messages': [{'role': 'system', 'content': 'standard instructions'},
                             {'role': 'user', 'content': 'unique conversation'}]}
        def render(config, model, conversation):
            if conversation['messages'] == body['messages']:
                return {'tokens': list(range(10)), 'reader': {}}
            self.assertNotIn('unique conversation', str(conversation))
            return {'tokens': list(range(6)) + [99], 'reader': {}}
        with patch.object(gateway.BACKEND, 'render', side_effect=render), \
             patch.object(gateway, '_prepare_tool_history', side_effect=lambda a, m, c, r: r), \
             patch.object(gateway, '_capture_steer_request'), \
             patch.dict(state.L, agents={}, tasks={}), \
             patch.dict(state.CONFIG['scheduler'], shared_prefix_tokens=4):
            public = gateway.render_request(body, 'user', model, {}, protocol=0)
            private = gateway.render_request(body, 'user', model, {}, protocol=0, private=True)
        self.assertEqual(public['shared'], [6])
        self.assertNotIn('shared', private)
        self.assertTrue(private['private'])

    def test_native_runtime_changes_follow_the_same_stable_instructions(self):
        def messages(catalog, directory):
            return [{'role': 'system', 'content': 'standard harness\n'
                '## Code Mode tools (call only inside `execute`)\n' + catalog +
                '\n<mcp_instructions>current server guidance</mcp_instructions>\n'
                'Skills provide specialized instructions\n<env>' + directory + '</env>\n'
                'standard project guidance'}, {'role': 'user', 'content': 'private request'},
                {'role': 'system', 'content': 'later instruction'}]
        a = gateway.user_cache_context(messages('tools A', '/tmp/client-A'))
        b = gateway.user_cache_context(messages('tools B', '/tmp/client-B'))
        self.assertEqual(a[0]['content'].split(gateway.RUNTIME_CONTEXT)[0],
                         b[0]['content'].split(gateway.RUNTIME_CONTEXT)[0])
        self.assertIn('tools A', a[0]['content'])
        self.assertIn('/tmp/client-A', a[0]['content'])
        self.assertIn('current server guidance', a[0]['content'])
        self.assertEqual(a[1:], messages('tools A', '/tmp/client-A')[1:])

    def test_personal_coin_skips_capture_and_tool_history(self):
        model = state.CONFIG['work_model']
        with patch.object(gateway.BACKEND, 'render', return_value={'tokens': [1], 'reader': {}}), \
             patch.object(gateway, '_capture_steer_request') as capture, \
             patch.object(gateway, '_prepare_tool_history') as history:
            result = gateway.render_request({'assistant': 'cointelpersonal',
                'messages': [{'role': 'user', 'content': 'synthetic'}]}, 'coin', model, {}, protocol=0)
        self.assertTrue(result['private'])
        capture.assert_not_called()
        history.assert_not_called()

    def test_personal_coin_does_not_save_inference_checkpoints(self):
        from cointos import snapshots
        with patch.object(snapshots.BACKEND, 'save') as save:
            self.assertFalse(snapshots.keep(0, [1, 2], 'cointelpersonal/user', 'checkpoint'))
            self.assertFalse(snapshots.keep(0, [1, 2], 'shared', 'shared', 'cointelpersonal/user'))
        save.assert_not_called()

    def test_private_prefix_never_becomes_a_shared_snapshot_candidate(self):
        model = state.CONFIG['work_model']
        thoughts = {'private': {'owner': 'private/key', 'model': model},
                    'ordinary': {'owner': 'user', 'model': model}}
        runs = {k: {'prompt': [1, 2, 3], 'generated': [], 'private': k == 'private'} for k in thoughts}
        with patch.dict(state.L, thoughts=thoughts, lanes=[]), \
             patch.dict(lanes.RUNS, runs, clear=True), patch.dict(lanes.HELD, {}, clear=True):
            self.assertEqual(lanes.shared_prefix('private', model), 0)
            self.assertEqual(lanes.shared_prefix('ordinary', model), 0)

    def test_launcher_preserves_user_behavior_settings_and_isolates_hook_state(self):
        ordinary = {'plugins': ['/fixture/hooks'], 'skills': ['/fixture/skills'],
                    'permissions': [{'action': 'read', 'resource': '*.env', 'effect': 'deny'}],
                    'instructions': ['/fixture/instructions'], 'compaction': {'auto': True}, 'custom_setting': {'preserve': True}}
        with tempfile.TemporaryDirectory() as temp, patch.object(private_session, 'configured_settings', return_value=ordinary), patch.object(private_session, 'configured_cli', return_value={'tabs': {'mode': 'compact'}}):
            env = private_session.environment(Path(temp), state.CONFIG)
            cfg = json.loads(Path(env['OPENCODE_CONFIG']).read_text())
            for key in ['skills', 'permissions', 'compaction', 'custom_setting']:
                self.assertEqual(cfg[key], ordinary[key])
            self.assertEqual(json.loads(env['OPENCODE_CLI_CONFIG_CONTENT']), {'tabs': {'mode': 'compact'}})
            self.assertEqual(json.loads((Path(temp) / 'config/opencode/cli.json').read_text()), {'tabs': {'mode': 'compact'}})
            self.assertIn('/fixture/instructions', cfg['instructions'])
            self.assertIn('/fixture/hooks', cfg['plugins'])
            self.assertEqual(env['KT_HOOK_STATE_DIR'], temp + '/state/knowledgetrees')

    def test_private_browser_reuses_binary_and_keeps_profile_and_outputs_temporary(self):
        fixture = {'servers': {'playwright': {'type': 'local', 'command': [
            'npx', '-y', '-p', 'node@22', '-p', '@playwright/mcp@0.0.84',
            'playwright-mcp', '--user-data-dir', '/persistent/profile']}}}
        with tempfile.TemporaryDirectory() as temp, patch.object(private_session, 'configured_mcp', return_value=fixture):
            env = private_session.environment(Path(temp), state.CONFIG)
            command = json.loads(Path(env['OPENCODE_CONFIG']).read_text())['mcp']['servers']['playwright']['command']
            self.assertIn('node@22', command)
            self.assertTrue(command[1].startswith('PLAYWRIGHT_BROWSERS_PATH='))
            self.assertEqual(command[command.index('--user-data-dir') + 1], temp + '/browser-profile')
            self.assertEqual(command[command.index('--output-dir') + 1], temp + '/browser-output')
            self.assertNotIn('/persistent/profile', command)

    def test_launcher_uses_memory_database_isolated_stores_and_only_private_gateway(self):
        fixture = {'servers': {'fixture': {'type': 'local', 'command': ['fixture-mcp']}}}
        with tempfile.TemporaryDirectory() as temp, patch.object(private_session, 'configured_mcp', return_value=fixture):
            env = private_session.environment(Path(temp), state.CONFIG)
            self.assertEqual(env['OPENCODE_DB'], ':memory:')
            self.assertEqual(env['XDG_DATA_HOME'], str(Path(temp) / 'data'))
            cfg = json.loads(Path(env['OPENCODE_CONFIG']).read_text())
            self.assertEqual(set(cfg['providers']), {'cointos'})
            self.assertTrue(cfg['providers']['cointos']['settings']['baseURL'].endswith('/v1/private'))
            self.assertFalse(cfg['snapshots'])
            self.assertEqual(cfg['share'], 'disabled')
            self.assertEqual(cfg['mcp'], fixture)


@unittest.skipUnless(os.environ.get('COINTOS_NATIVE_OPENCODE2') == '1', 'opt-in native private fixture')
class NativePrivateSession(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(private_session, 'configured_mcp', return_value={}))
        self.enterContext(patch.object(private_session, 'configured_settings', return_value={}))
        self.enterContext(patch.object(private_session, 'configured_cli', return_value={}))

    def test_private_native_mcp_call_does_not_retain_its_transcript(self):
        import subprocess
        import sys
        import threading
        from http.server import ThreadingHTTPServer
        from tests.test_opencode2_native import Provider
        class SkillThenMCP(Provider):
            def do_POST(self):
                if not self.server.requests:
                    self.server.tool = ('skill', {'id': 'private-fixture'})
                elif len(self.server.requests) == 1:
                    self.server.tool = ('execute', {'code': 'return await tools.fixture.echo({text:\"PRIVATE_MCP_CANARY_916265\"})'})
                super().do_POST()
        server = ThreadingHTTPServer(('127.0.0.1', 0), SkillThenMCP)
        marker = 'PRIVATE_MCP_CANARY_916265'
        server.requests, server.tool = [], ('execute', {'code': 'return await tools.fixture.echo({text:"' + marker + '"})'})
        server.block, server.partial, server.reasoning = False, False, False
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        with tempfile.TemporaryDirectory(dir='/dev/shm', prefix='cointos-private-mcp-') as temp:
            root = Path(temp)
            fixture = root / 'fixture.py'
            fixture.write_text('''import json,sys
for line in sys.stdin:
 m=json.loads(line)
 if 'id' not in m:continue
 if m['method']=='initialize':r={'protocolVersion':'2024-11-05','capabilities':{'tools':{}},'serverInfo':{'name':'fixture','version':'1'}}
 elif m['method']=='tools/list':r={'tools':[{'name':'echo','description':'Echo synthetic test text','inputSchema':{'type':'object','properties':{'text':{'type':'string'}},'required':['text']}}]}
 elif m['method']=='tools/call':r={'content':[{'type':'text','text':m['params']['arguments']['text']}]}
 else:r={}
 print(json.dumps({'jsonrpc':'2.0','id':m['id'],'result':r}),flush=True)
''')
            hook = Path.home() / '.config/opencode2/opencode/plugins/knowledgetrees'
            handler = root / 'fixture-knowledge/.tools'
            handler.mkdir(parents=True)
            (handler / 'kt-hooks').write_text("import json,sys\nfrom pathlib import Path\njson.load(sys.stdin)\np=Path(__file__).with_name('events')\nseen=p.read_text() if p.exists() else ''\np.write_text(seen+sys.argv[-1]+'\\n')\nr={'additionalContext':'PRIVATE_HOOK_STARTUP_SENTINEL'} if sys.argv[-1]=='start' else ({'decision':'block','reason':'PRIVATE_HOOK_MAINTENANCE_SENTINEL'} if 'stop' not in seen else {})\nprint(json.dumps(r))\n")
            env = private_session.environment(root, state.CONFIG, workdir=root / 'work')
            env['KT_GLOBAL_ROOT'] = str(handler.parent)
            path = Path(env['OPENCODE_CONFIG'])
            cfg = json.loads(path.read_text())
            cfg['providers']['cointos']['settings']['baseURL'] = f'http://127.0.0.1:{server.server_port}/v1'
            skill = root / 'skills/private-fixture'
            skill.mkdir(parents=True)
            (skill / 'SKILL.md').write_text('---\nname: private-fixture\ndescription: Synthetic private skill fixture\n---\nPRIVATE_SKILL_EXECUTION_SENTINEL\n')
            cfg['skills'] = [str(root / 'skills')]
            cfg['plugins'].append(str(hook))
            cfg['mcp'] = {'servers': {'fixture': {'type': 'local', 'command': [sys.executable, str(fixture)]}}}
            path.write_text(json.dumps(cfg))
            (root / 'work').mkdir()
            (root / 'work/AGENTS.md').write_text('PRIVATE_PROJECT_INSTRUCTIONS_SENTINEL')
            (root / 'work/.opencode').mkdir()
            project_override = {'providers': {'cointos': {'settings': {'baseURL': 'http://127.0.0.1:1/v1'}}}}
            for project_config in (root / 'work/opencode.json', root / 'work/.opencode/opencode.json'):
                project_config.write_text(json.dumps(project_override))
            result = subprocess.run([str(Path.home() / '.local/lib/opencode/2.3.0/opencode'),
                'run', '--standalone', '--auto', '--log-level', 'none', '--format', 'json', 'Use the synthetic echo fixture'],
                env=env, cwd=root / 'work', capture_output=True, timeout=40)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
            self.assertIn(marker.encode(), result.stdout)
            self.assertGreaterEqual(len(server.requests), 2)
            self.assertTrue('PRIVATE_SKILL_EXECUTION_SENTINEL' in json.dumps(server.requests), 'native skill execution omitted its body')
            self.assertIn('PRIVATE_HOOK_STARTUP_SENTINEL', json.dumps(server.requests))
            self.assertTrue('PRIVATE_HOOK_MAINTENANCE_SENTINEL' in json.dumps(server.requests), 'native turn-end maintenance continuation was omitted')
            self.assertTrue('PRIVATE_PROJECT_INSTRUCTIONS_SENTINEL' in json.dumps(server.requests), 'project AGENTS.md was omitted')
            for path in root.rglob('*'):
                if path.is_file():
                    self.assertNotIn(marker.encode(), path.read_bytes(), str(path.relative_to(root)))

    def test_launcher_crash_removes_its_transient_store(self):
        import copy
        import signal
        import subprocess
        import sys
        import threading
        import time
        from http.server import ThreadingHTTPServer
        from tests.test_opencode2_native import Provider
        server = ThreadingHTTPServer(('127.0.0.1', 0), Provider)
        server.requests, server.tool, server.block, server.partial, server.reasoning = [], None, False, True, False
        server.blocked, server.release = threading.Event(), threading.Event()
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.addCleanup(server.release.set)
        with tempfile.TemporaryDirectory(dir='/dev/shm', prefix='private-fixture-') as temp:
            root = Path(temp)
            cfg = copy.deepcopy(state.CONFIG)
            cfg['port'] = server.server_port
            path = root / 'config.json'
            path.write_text(json.dumps(cfg))
            before = set(Path('/dev/shm').glob('cointos-private-*'))
            env = {**os.environ, 'COINTOS_CONFIG': str(path),
                   'PYTHONPATH': str(Path(__file__).resolve().parents[1])}
            script = ('from cointos import private_session as p; p.configured_mcp=lambda: {}; p.configured_settings=lambda: {}; p.configured_cli=lambda: {}; '
                      'raise SystemExit(p.main(["run","--format","json","Synthetic crash-cleanup fixture"]))')
            process = subprocess.Popen([sys.executable, '-P', '-c', script],
                env=env, cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                self.assertTrue(server.blocked.wait(20), 'native private request did not reach fixture')
                created = set(Path('/dev/shm').glob('cointos-private-*')) - before
                self.assertEqual(len(created), 1)
                process.kill()
                process.wait(timeout=5)
                deadline = time.monotonic() + 5
                while any(p.exists() for p in created) and time.monotonic() < deadline:
                    time.sleep(.05)
                self.assertTrue(all(not p.exists() for p in created))
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                server.release.set()

    def test_real_opencode_retains_no_canary_or_database_in_its_stores(self):
        import subprocess
        import threading
        from http.server import ThreadingHTTPServer
        from tests.test_opencode2_native import Provider
        server = ThreadingHTTPServer(('127.0.0.1', 0), Provider)
        server.requests, server.tool, server.block, server.partial, server.reasoning = [], None, False, False, False
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        marker = 'PRIVATE_NATIVE_CANARY_916263'
        with tempfile.TemporaryDirectory(dir='/dev/shm', prefix='cointos-private-test-') as temp:
            root = Path(temp)
            env = private_session.environment(root, state.CONFIG, workdir=root / 'work')
            path = Path(env['OPENCODE_CONFIG'])
            cfg = json.loads(path.read_text())
            cfg['providers']['cointos']['settings']['baseURL'] = f'http://127.0.0.1:{server.server_port}/v1'
            path.write_text(json.dumps(cfg))
            (root / 'work').mkdir()
            result = subprocess.run([str(Path.home() / '.local/lib/opencode/2.3.0/opencode'),
                'run', '--standalone', '--log-level', 'none', '--format', 'json', marker],
                env=env, cwd=root / 'work', capture_output=True, timeout=40)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
            self.assertTrue(server.requests)
            for path in root.rglob('*'):
                if path.is_file():
                    self.assertNotIn(marker.encode(), path.read_bytes(), str(path.relative_to(root)))
                    self.assertNotIn(path.suffix, ('.db', '.sqlite', '.sqlite3'))
