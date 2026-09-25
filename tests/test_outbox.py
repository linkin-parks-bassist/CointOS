import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from ecosystem import cli, executor, outbox, watchdog


class OutboxTest(unittest.TestCase):
    def test_result_enqueue_preserves_delivered_or_unknown_record(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(cli, "ROOT", Path(temporary)):
            cli.initialize()
            first, created = outbox.enqueue_result(42, "task-one")
            self.assertTrue(created)
            path = cli.ROOT / "state/jobs" / f"{first}.json"
            saved = json.loads(path.read_text())
            saved["state"] = "delivered"
            cli.atomic_json(path, saved)
            self.assertEqual(outbox.enqueue_result(42, "task-one"), (first, False))
            saved["state"] = "delivery_unknown"
            cli.atomic_json(path, saved)
            self.assertEqual(outbox.enqueue_result(42, "task-one"), (first, False))
            self.assertEqual(len(list((cli.ROOT / "state/jobs").glob("outbox-*.json"))), 1)

    def test_terminal_intent_repairs_missing_outbox_once(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(cli, "ROOT", Path(temporary)):
            cli.initialize()
            cli.atomic_json(cli.ROOT / "state/jobs/task-one.json", {
                "id": "task-one", "kind": "agent-task", "state": "completed",
                "result_notification_recipients": [42, 43],
            })
            self.assertEqual(watchdog.reconcile_result_notifications(), ["task-one", "task-one"])
            self.assertEqual(watchdog.reconcile_result_notifications(), [])
            self.assertEqual(len(list((cli.ROOT / "state/jobs").glob("outbox-*.json"))), 2)

    def test_crash_after_terminal_publication_is_repaired(self):
        with tempfile.TemporaryDirectory() as temporary, \
             patch.object(cli, "ROOT", Path(temporary)), \
             patch.dict("os.environ", {"AGENT_TELEGRAM_ALLOWED_USER_IDS": "42"}):
            cli.initialize()
            path = cli.ROOT / "state/jobs/task-one.json"
            job = {"id": "task-one", "kind": "agent-task", "state": "run_finished",
                   "runner_generation": 1}
            cli.atomic_json(path, job)
            with patch.object(executor, "queue_notifications", side_effect=SystemExit):
                with self.assertRaises(SystemExit):
                    executor._finalize_run_finished(job, path)
            saved = json.loads(path.read_text())
            self.assertEqual(saved["state"], "completed")
            self.assertEqual(saved["result_notification_recipients"], [42])
            self.assertEqual(watchdog.reconcile_result_notifications(), ["task-one"])
            self.assertEqual(watchdog.reconcile_result_notifications(), [])

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
            self.assertIn("work completed", sent[0][1])
            saved = json.loads((cli.ROOT / f"state/jobs/{message_id}.json").read_text())
            self.assertEqual(saved["state"], "delivered")
