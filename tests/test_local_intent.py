import io
import json
import unittest
from unittest.mock import patch
from ecosystem.presentation import sanitize_notification
from ecosystem.control_agent import respond


class FakeResponse:
    def __init__(self, content):
        message = content if isinstance(content, dict) else {"content": content}
        self.payload = {"choices": [{"message": message}]}
    def __enter__(self): return io.BytesIO(json.dumps(self.payload).encode())
    def __exit__(self, *args): return False


class IntentTest(unittest.TestCase):
    @patch("urllib.request.urlopen")
    def test_control_agent_uses_tool_then_speaks(self, opened):
        tool_call = {"id": "call-one", "type": "function", "function": {"name": "inspect_status", "arguments": "{}"}}
        opened.side_effect = [FakeResponse({"content": None, "tool_calls": [tool_call]}),
                              FakeResponse({"content": "Qwen is loaded.", "tool_calls": []})]
        calls = []
        result = respond("Is Qwen loaded?", [], {"models": []},
                         lambda name, arguments: calls.append((name, arguments)) or {"ok": True})
        self.assertEqual(result, "Qwen is loaded.")
        self.assertEqual(calls, [("inspect_status", {})])

    def test_removes_generic_chatbot_tail(self):
        raw = "Cyrus updated the system map. Want to dive into it or should we chat about something else?"
        self.assertEqual(sanitize_notification(raw), "Cyrus updated the system map.")
