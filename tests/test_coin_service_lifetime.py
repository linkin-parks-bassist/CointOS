"""Permanent Coin thread failure ends a blocked polling process, preserving wakes."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from cointos import wakeups


CHILD = r'''
import os,sys,threading
from pathlib import Path
from types import SimpleNamespace
from cointos import coin,wakeups
mode=sys.argv[1]
root=coin.COIN_STATE
coin.ensure_state()
entered=threading.Event(); finished=threading.Event()
def idle(*args): threading.Event().wait()
coin.observe_attachments=idle
coin.observe_notifications=idle
if mode in ('notification_fatal', 'notification_return'):
    def notifications(*args):
        assert entered.wait(5)
        if mode == 'notification_fatal': raise SystemExit(0)
    coin.observe_notifications=notifications
if mode in ('attachment_fatal', 'attachment_return'):
    def attachments(*args):
        assert entered.wait(5)
        if mode == 'attachment_fatal': raise SystemExit(0)
    coin.observe_attachments=attachments
def fatal(message):
    assert entered.wait(5), 'fixture polling did not start'
    raise RuntimeError(message)
def opener(*args):
    if mode == 'worker_startup': return fatal('fixture KT startup failed')
    opener.calls += 1
    if mode == 'worker_reopen' and opener.calls > 1:
        return fatal('fixture KT reopen failed')
    return {'process':SimpleNamespace(poll=lambda: 1 if mode == 'worker_reopen' else None)}
opener.calls=0
coin.kt_mcp.open_session=opener
coin.credentials=lambda:('fixture-opaque-token',{7})
coin.remember=lambda *args:None
coin.send=lambda *args:{'message_id':101}
coin.report=lambda busy:finished.set() if not busy and mode in ('routine_worker','replay') and (
    (root/'caught-turn-failure').exists() or (root/'delivered-wake').exists()) else None
def turn(*args,**options):
    if mode == 'replay':
        (root/'delivered-wake').write_text(options['wake']['id'])
        return
    (root/'caught-turn-failure').write_text('routine failure reached worker')
    raise ValueError('fixture routine model error')
coin.turn=turn
if mode not in ('observer_fatal','observer_return','routine_observer'):
    coin.observe_wakes=idle
else:
    if mode == 'observer_fatal':
        def observer(*args):
            assert entered.wait(5)
            raise SystemExit(0)
        coin.observe_wakes=observer
    elif mode == 'observer_return':
        def observer(*args): assert entered.wait(5)
        coin.observe_wakes=observer
    else:
        def ready(*args):
            ready.calls += 1
            if ready.calls == 1: raise ValueError('fixture routine observer error')
            (root/'observer-retried').write_text(str(ready.calls))
            finished.set()
            idle()
        ready.calls=0
        coin.wakeups.ready=ready
        coin.time.sleep=lambda *args:None
if mode in ('observer_fatal','observer_return','routine_observer'):
    coin.worker=idle
elif mode == 'worker_return':
    def worker(*args): assert entered.wait(5)
    coin.worker=worker

def poll(*args):
    poll.calls += 1
    if mode in ('worker_reopen','routine_worker') and poll.calls == 1:
        return [{'update_id':1,'message':{'from':{'id':7},'chat':{'id':7},'text':'fixture'}}]
    (root/'polling-blocked').write_text('polling reached a blocking fixture boundary')
    entered.set()
    if mode in ('routine_worker','routine_observer','replay'):
        assert finished.wait(5), 'fixture routine retry/replay did not finish'
        os._exit(0)
    idle()
poll.calls=0
coin.telegram=poll
coin.main()
'''


class ServiceLifetime(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory(prefix='cointos-coin-lifetime-')))
        self.environment = {**os.environ, 'COINTOS_STATE': str(self.root), 'PYTHONDONTWRITEBYTECODE': '1'}
        self.store = self.root / 'coin/wakes'
        self.wake = wakeups.create(self.store, 7, 7, 'Check retained fixture work',
                                   {'kind': 'deadline', 'after_seconds': 0})
        self.assertEqual([event['id'] for event in wakeups.ready(self.store)], [self.wake['id']])

    def run_child(self, mode):
        return subprocess.run([sys.executable, '-c', CHILD, mode], env=self.environment,
                              capture_output=True, text=True, timeout=8)

    def test_unexpected_worker_and_observer_exit_fails_a_blocked_polling_process(self):
        for mode in ('worker_startup', 'worker_reopen', 'worker_return', 'observer_fatal', 'observer_return',
                     'attachment_fatal', 'attachment_return', 'notification_fatal', 'notification_return'):
            with self.subTest(mode=mode):
                result = self.run_child(mode)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertTrue((self.root / 'coin/polling-blocked').exists())
                self.assertTrue(wakeups.pending(self.store, self.wake['id']))

    def test_a_fresh_process_replays_and_acknowledges_the_retained_wake(self):
        failed = self.run_child('worker_startup')
        self.assertEqual(failed.returncode, 1, failed.stderr)
        self.assertTrue(wakeups.pending(self.store, self.wake['id']))
        restarted = self.run_child('replay')
        self.assertEqual(restarted.returncode, 0, restarted.stderr)
        self.assertEqual((self.root / 'coin/delivered-wake').read_text(), self.wake['id'])
        self.assertFalse(wakeups.pending(self.store, self.wake['id']))
        self.assertEqual(wakeups.list(self.store, 7), [])

    def test_routine_worker_and_observer_errors_remain_retryable(self):
        for mode, marker in [('routine_worker', 'caught-turn-failure'), ('routine_observer', 'observer-retried')]:
            with self.subTest(mode=mode):
                result = self.run_child(mode)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue((self.root / 'coin' / marker).exists())
        self.assertTrue(wakeups.pending(self.store, self.wake['id']))


class NativeCoinPolicy(unittest.TestCase):
    def test_failed_coin_process_has_uncapped_native_restart_using_shared_interval(self):
        import configparser
        source = Path(__file__).resolve().parents[1]
        policy = configparser.ConfigParser(interpolation=None, strict=False)
        policy.read(source / 'systemd/cointos-coin.service')
        self.assertEqual(policy['Unit']['StartLimitIntervalSec'], '0')
        self.assertEqual(policy['Service']['Restart'], 'always')
        self.assertEqual(policy['Service']['RestartSec'], '@SERVICE_RESTART_SECONDS@')
        self.assertEqual(policy['Service']['ExecStart'], '/usr/bin/python3 -m cointos.coin')



if __name__ == '__main__':
    unittest.main()
