import io
import json
import unittest
from unittest.mock import patch
from ecosystem.local_intent import interpret


class FakeResponse:
    def __init__(self, content):
        self.payload = {"choices": [{"message": {"content": content}}]}
    def __enter__(self): return io.BytesIO(json.dumps(self.payload).encode())
    def __exit__(self, *args): return False


class IntentTest(unittest.TestCase):
    @patch("urllib.request.urlopen")
    def test_valid_spawn(self, opened):
        opened.return_value = FakeResponse('{"action":"spawn","role":"worker","task":"fix it","model":"model-a","model_reason":"small enough","reply":""}')
        result = interpret("please fix it", ["worker"], inventory={"memory_available_gb": 10, "load_average": [1,1,1], "models": [{"id":"model-a"}]})
        self.assertEqual(result["action"], "spawn")

    @patch("urllib.request.urlopen")
    def test_unknown_role_is_rejected(self, opened):
        opened.return_value = FakeResponse('{"action":"spawn","role":"root","task":"do it","model":"model-a","model_reason":"fast","reply":""}')
        with self.assertRaises(ValueError): interpret("do it", ["worker"], inventory={"memory_available_gb": 10, "load_average": [], "models": [{"id":"model-a"}]})
