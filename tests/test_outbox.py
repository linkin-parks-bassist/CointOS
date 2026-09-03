import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from ecosystem import cli, outbox


class OutboxTest(unittest.TestCase):
    def test_waits_for_dependency_then_delivers(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(cli, "ROOT", Path(temporary)):
            cli.initialize()
            dependency = {"id": "task-one", "kind": "agent-task", "state": "running", "role": "worker"}
            cli.atomic_json(cli.ROOT / "state/jobs/task-one.json", dependency)
            message_id = outbox.enqueue(42, depends_on="task-one", result_of="task-one")
            sent = []
            self.assertEqual(outbox.drain(lambda user, text: sent.append((user, text))), 0)
            dependency["state"] = "completed"
            cli.atomic_json(cli.ROOT / "state/jobs/task-one.json", dependency)
            self.assertEqual(outbox.drain(lambda user, text: sent.append((user, text))), 1)
            self.assertEqual(sent[0][0], 42)
            self.assertIn("work passed an independent check", sent[0][1])
            saved = json.loads((cli.ROOT / f"state/jobs/{message_id}.json").read_text())
            self.assertEqual(saved["state"], "delivered")
