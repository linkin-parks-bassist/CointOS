import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from ecosystem import cli, conversation
from ecosystem.telegram import status_text


class ConversationTest(unittest.TestCase):
    def test_recent_and_forget(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(cli, "ROOT", Path(temporary)):
            conversation.append(42, "user", "first")
            conversation.append(42, "assistant", "second")
            self.assertEqual([item["content"] for item in conversation.recent(42)], ["first", "second"])
            self.assertEqual(oct(conversation.path_for(42).stat().st_mode & 0o777), "0o600")
            conversation.forget(42)
            self.assertEqual(conversation.recent(42), [])

    def test_status_describes_running_work_and_stall(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(cli, "ROOT", Path(temporary)):
            cli.initialize()
            job = {"id":"task-x", "kind":"agent-task", "state":"running", "role":"worker", "model":"model-x", "updated_at":"2026-01-01T00:00:00+00:00", "output":"logs/x.log"}
            cli.atomic_json(cli.ROOT / "state/jobs/task-x.json", job)
            output = cli.ROOT / "logs/x.log"; output.parent.mkdir(exist_ok=True); output.write_text("working")
            self.assertIn("task-x: running / worker / model-x", status_text())
