"""Exercise real kt publication and priority persistence without touching live roots."""
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from cointos import queues, state


class RuntimeQueue(unittest.TestCase):
    def setUp(self):
        previous = copy.deepcopy(state.L)
        self.addCleanup(lambda: (state.L.clear(), state.L.update(previous)))
        state.L.clear()
        state.L.update(state.fresh({}))

    def test_priority_survives_sorted_json(self):
        p = {"name": "p"}
        queues.add(p, "queued", "z-first", "first")
        queues.add(p, "queued", "a-second", "second")
        queues.add(p, "urgent", "u-urgent", "urgent")
        persisted = json.loads(json.dumps(state.L, sort_keys=True))
        state.L.clear()
        state.L.update(state.fresh(persisted))
        self.assertEqual([r["item"] for r in queues.scan(p)], ["u-urgent", "z-first", "a-second"])

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
                queues.update('p', 'plan', 'done')
                queues.publish()
                done = subprocess.run(['kt', '--lean', 'open', 'local:what/is/the/command/queue.md'],
                                      cwd=root, check=True, capture_output=True, text=True)
                self.assertIn('The queue is empty.', done.stdout)
