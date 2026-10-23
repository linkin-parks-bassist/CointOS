"""Exercise real kt publication and priority persistence without touching live roots."""
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch
from cointos import queues, state


class RuntimeQueue(unittest.TestCase):
    def setUp(self):
        previous = copy.deepcopy(state.L)
        self.addCleanup(lambda: (state.L.clear(), state.L.update(previous)))
        state.L.clear()
        state.L.update(state.fresh({}))

    def test_slow_projection_write_does_not_hold_state_lock_and_newer_publish_follows(self):
        writing, release, updated = threading.Event(), threading.Event(), threading.Event()
        written = []
        queues.add({'name':'p'}, 'command', 'first', 'First fixture')
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        def write(path, question, body):
            self.assertFalse(state.LOCK._is_owned())
            if not written:
                writing.set()
                if not release.wait(3): raise TimeoutError('fixture projection remained blocked')
            written.append((question,body))
        def newer():
            with state.LOCK:
                queues.add({'name':'p'}, 'command', 'second', 'Second fixture')
                updated.set()
            queues.publish()
        first = threading.Thread(target=queues.publish)
        second = threading.Thread(target=newer)
        try:
            with patch.object(queues,'ROOT',root), patch.object(queues.kt,'write',side_effect=write):
                first.start(); self.assertTrue(writing.wait(1)); second.start()
                self.assertTrue(updated.wait(1)); release.set(); first.join(2); second.join(2)
            self.assertFalse(first.is_alive()); self.assertFalse(second.is_alive())
            commands = [b for q,b in written if q=='what is the command queue']
            self.assertNotIn('Second fixture',commands[0])
            self.assertIn('Second fixture',commands[-1])
        finally:
            release.set()
            if first.ident is not None: first.join(2)
            if second.ident is not None: second.join(2)

    def test_priority_survives_sorted_json(self):
        p = {"name": "p"}
        queues.add(p, "queued", "z-first", "first")
        queues.add(p, "queued", "a-second", "second")
        queues.add(p, "urgent", "u-urgent", "urgent")
        persisted = json.loads(json.dumps(state.L, sort_keys=True))
        state.L.clear()
        state.L.update(state.fresh(persisted))
        self.assertEqual([r["item"] for r in queues.live("p")], ["u-urgent", "z-first", "a-second"])

    def test_real_kt_creation_update_and_noop(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(os.environ, KT_CONFIG=str(root / 'roots.json')), patch.object(queues, 'ROOT', root):
                subprocess.run(['kt', 'init', 'Isolated runtime queue test.'], cwd=root, check=True, capture_output=True)
                queues.publish()
                queues.add({'name': 'p'}, 'command', 'plan', 'Plan the next stage')
                queues.publish()
                result = subprocess.run(['kt', '--lean', 'open', 'local:what/is/the/command/queue.md'],
                                        cwd=root, check=True, capture_output=True, text=True)
                self.assertIn('p:plan', result.stdout)
                self.assertIn('Plan the next stage', result.stdout)
                revision = result.stderr
                queues.publish()
                after = subprocess.run(['kt', '--lean', 'open', 'local:what/is/the/command/queue.md'],
                                       cwd=root, check=True, capture_output=True, text=True)
                self.assertEqual(after.stderr, revision)
                queues.finish(queues.records()['p:plan'])
                queues.publish()
                done = subprocess.run(['kt', '--lean', 'open', 'local:what/is/the/command/queue.md'],
                                      cwd=root, check=True, capture_output=True, text=True)
                self.assertIn('The queue is empty.', done.stdout)
