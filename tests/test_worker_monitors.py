"""Monitor slots: concurrency, reuse, dead viewers, and AFK without inference."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import worker_monitors as monitors


def assignment(key):
    return {'view_record': key, 'session_id': 'ses_'+key,
            'server': monitors.identity(os.getpid()), 'url': 'http://127.0.0.1:4096',
            'directory': '/tmp', 'opencode': '/usr/bin/false', 'title': key}


def test_busy_slots_are_distinct_and_idle_slot_is_reused():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        first, create = monitors.reserve(root, assignment('one'))
        assert create
        assert monitors.register(root, first)
        same, create = monitors.reserve(root, assignment('one'))
        assert same == first and not create
        second, create = monitors.reserve(root, assignment('two'))
        assert second != first and create
        monitors.finish(root, first, 'one')
        reused, create = monitors.reserve(root, assignment('three'))
        assert reused == first and not create
        # A late completion must not clear its successor assignment.
        monitors.finish(root, first, 'one')
        assert monitors.current(root, first)['view_record'] == 'three'


def test_closed_window_is_retired_without_touching_agent():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        slot, _ = monitors.reserve(root, assignment('one'))
        assert monitors.register(root, slot)
        monitors.retire(root, slot)
        replacement, create = monitors.reserve(root, assignment('two'))
        assert replacement != slot and create
        assert monitors.alive(assignment('one')['server'])


def test_afk_creates_no_registry_or_window():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)/'absent'
        assert monitors.show(root, assignment('one'), 'afk', {}) is None
        assert not root.exists()


def test_concurrent_reservations_do_not_share_a_busy_slot():
    with tempfile.TemporaryDirectory() as temporary:
        code = ('import sys; import worker_monitors as m; '
                'print(m.reserve(sys.argv[1], {"view_record":sys.argv[2],'
                '"server":m.identity(int(sys.argv[3]))})[0])')
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]/'scripts'))
        children = [subprocess.Popen([sys.executable, '-c', code, temporary, key,
                                     str(os.getpid())], env=env, stdout=subprocess.PIPE,
                                    text=True) for key in ('one', 'two')]
        results = [child.communicate(timeout=5)[0].strip() for child in children]
        assert all(child.returncode == 0 for child in children)
        assert results[0] and results[1] and results[0] != results[1]


def test_monitor_process_reinhabits_same_slot_for_second_run():
    def until(predicate):
        deadline = time.monotonic()+5
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.05)
        raise AssertionError('monitor handover did not reach expected state')
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        servers = [subprocess.Popen(['sleep', '30']) for _ in range(2)]
        monitor = None
        try:
            first = assignment('first')
            first['server'] = monitors.identity(servers[0].pid)
            first['opencode'] = str(Path(__file__).parent/'fixtures/monitor_probe_viewer.py')
            key, create = monitors.reserve(root, first)
            assert create
            with (root/'output').open('w') as output:
                monitor = subprocess.Popen([sys.executable, monitors.__file__, str(root), key],
                    stdout=output, stderr=output, stdin=subprocess.DEVNULL)
            until(lambda: 'ATTACHED ses_first' in (root/'output').read_text())
            servers[0].terminate()
            servers[0].wait(timeout=3)
            until(lambda: monitors.current(root, key) is None)
            second = {**first, 'view_record': 'second', 'session_id': 'ses_second',
                      'server': monitors.identity(servers[1].pid), 'title': 'second'}
            same, create = monitors.reserve(root, second)
            assert same == key and not create
            until(lambda: 'ATTACHED ses_second' in (root/'output').read_text())
            assert monitor.poll() is None
            monitor.terminate()
            monitor.wait(timeout=5)
            assert servers[1].poll() is None  # closing monitor never kills agent
        finally:
            if monitor is not None:
                monitors.stop_viewer(monitor)
            for server in servers:
                monitors.stop_viewer(server)


def load_tests(_loader, _tests, _pattern):
    return unittest.TestSuite(unittest.FunctionTestCase(value)
        for name, value in globals().items()
        if name.startswith('test_') and callable(value))
