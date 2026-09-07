"""Characterize the real server boundary without requesting model inference."""
import importlib.util
import json
import os
import pty
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/opencode_observable.py'
sys.path.insert(0, str(SCRIPT.parent))
OPENCODE = Path('/home/david/.local/bin/opencode')


def test_real_server_session_viewer_disconnect_and_cleanup_without_inference():
    # Losing --hostname, the inherited config FD, session binding, or cleanup
    # breaks this real-process integration, not a mock call assertion.
    spec = importlib.util.spec_from_file_location('observable', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        env = dict(os.environ)
        for key in list(env):
            if key.startswith('OPENCODE_'):
                del env[key]
        env.update(COINTOS_VIEW_MODE='afk', XDG_CONFIG_HOME=str(root/'config'), XDG_DATA_HOME=str(root/'data'),
                   XDG_CACHE_HOME=str(root/'cache'), XDG_STATE_HOME=str(root/'state'),
                   OPENCODE_DISABLE_PROJECT_CONFIG='true')
        fd = os.memfd_create('view-test', 0)
        os.write(fd, b'{"enabled_providers":[],"plugin":[],"permission":"deny"}')
        env['OPENCODE_CONFIG'] = f'/proc/self/fd/{fd}'
        record = root/'view.json'
        server = None
        try:
            server, url = module.start_server(str(OPENCODE), root, env, root/'server.log')
            assert url.startswith('http://127.0.0.1:')
            session = module.create_session(url, root, 'view-only-test')
            module.publish_view(record, url, root, session, server.pid)
            saved = json.loads(record.read_text())
            assert saved['session_id'] == session
            assert saved['server_pid'] == server.pid
            assert record.stat().st_mode & 0o777 == 0o600
            with urllib.request.urlopen(url+'/session/'+session, timeout=5) as reply:
                assert json.load(reply)['title'] == 'view-only-test'
            # An independent event viewer connects and disconnects. Neither event
            # subscription nor session creation invokes a provider.
            viewer = urllib.request.urlopen(url+'/event', timeout=5)
            assert viewer.status == 200
            viewer.close()
            assert server.poll() is None
            assert os.getpgid(server.pid) == os.getpgrp()
            # Actual native TUI can attach without becoming the server owner.
            master, slave = pty.openpty()
            tui_env = dict(env, TERM='xterm-256color')
            tui_env.pop('OPENCODE_CONFIG')
            tui = subprocess.Popen([str(OPENCODE), 'attach', url, '--pure',
                '--dir', str(root), '--session', session], env=tui_env,
                stdin=slave, stdout=slave, stderr=slave)
            os.close(slave)
            try:
                time.sleep(2)
                assert tui.poll() is None
                tui.terminate()
                tui.wait(timeout=10)
            finally:
                module.stop_child(tui)
                os.close(master)
            assert server.poll() is None
            with urllib.request.urlopen(url+'/global/health', timeout=5) as reply:
                assert json.load(reply)['healthy'] is True
            with urllib.request.urlopen(url+'/session/'+session+'/message', timeout=5) as reply:
                assert json.load(reply) == []
            # Record replay refuses overwrite rather than silently redirecting UI.
            try:
                module.publish_view(record, url, root, session, server.pid)
            except FileExistsError:
                pass
            else:
                raise AssertionError('view record was overwritten')
        finally:
            if server is not None:
                module.stop_child(server)
                assert server.poll() is not None
            os.close(fd)


def test_supervisor_forwards_client_exit_and_reaps_server():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        env = {key: value for key, value in os.environ.items()
               if not key.startswith('OPENCODE_')}
        env.update(COINTOS_VIEW_MODE='afk', XDG_CONFIG_HOME=str(root/'config'), XDG_DATA_HOME=str(root/'data'),
                   XDG_CACHE_HOME=str(root/'cache'), XDG_STATE_HOME=str(root/'state'),
                   OPENCODE_DISABLE_PROJECT_CONFIG='true',
                   OPENCODE_CONFIG_CONTENT='{"enabled_providers":[],"plugin":[],"permission":"deny"}')
        fixture = Path(__file__).parent/'fixtures/opencode_view_probe.py'
        result = subprocess.run([sys.executable, str(SCRIPT), '--view-record',
            str(root/'view.json'), '--', str(fixture), 'run', '--pure', '--format',
            'json', '--title', 'inert-client', '--dir', str(root)],
            env=env, capture_output=True, text=True, timeout=40)
        assert result.returncode == 17, result.stderr
        view = json.loads((root/'view.json').read_text())
        emitted = json.loads(result.stdout)
        assert emitted['sessionID'] == view['session_id']
        assert not Path('/proc', str(view['server_pid'])).exists()


def load_tests(_loader, _tests, _pattern):
    return unittest.TestSuite(unittest.FunctionTestCase(value)
        for name, value in globals().items()
        if name.startswith('test_') and callable(value))
