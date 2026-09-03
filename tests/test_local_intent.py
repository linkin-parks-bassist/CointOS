import io
import json
import unittest
from unittest.mock import patch
from ecosystem.local_intent import interpret, sanitize_notification


class FakeResponse:
    def __init__(self, content):
        self.payload = {"choices": [{"message": {"content": content}}]}
    def __enter__(self): return io.BytesIO(json.dumps(self.payload).encode())
    def __exit__(self, *args): return False


class IntentTest(unittest.TestCase):
    def test_removes_generic_chatbot_tail(self):
        raw = "Cyrus updated the system map. Want to dive into it or should we chat about something else?"
        self.assertEqual(sanitize_notification(raw), "Cyrus updated the system map.")

    @patch("urllib.request.urlopen")
    def test_valid_spawn(self, opened):
        opened.return_value = FakeResponse('{"action":"spawn","role":"worker","task":"fix it","model":"model-a","model_reason":"small enough","agent_name":"Rob","reply":""}')
        result = interpret("please fix it", ["worker"], inventory={"memory_available_gb": 10, "load_average": [1,1,1], "models": [{"id":"model-a"}]})
        self.assertEqual(result["action"], "spawn")

    @patch("urllib.request.urlopen")
    def test_unknown_role_is_rejected(self, opened):
        opened.return_value = FakeResponse('{"action":"spawn","role":"root","task":"do it","model":"model-a","model_reason":"fast","agent_name":"Bort","reply":""}')
        with self.assertRaises(ValueError): interpret("do it", ["worker"], inventory={"memory_available_gb": 10, "load_average": [], "models": [{"id":"model-a"}]})
