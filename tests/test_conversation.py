import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from ecosystem import cli, conversation


class ConversationTest(unittest.TestCase):
    def test_recent_and_forget(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(cli, "ROOT", Path(temporary)):
            conversation.append(42, "user", "first")
            conversation.append(42, "assistant", "second")
            self.assertEqual([item["content"] for item in conversation.recent(42)], ["first", "second"])
            self.assertEqual(oct(conversation.path_for(42).stat().st_mode & 0o777), "0o600")
            conversation.forget(42)
            self.assertEqual(conversation.recent(42), [])
