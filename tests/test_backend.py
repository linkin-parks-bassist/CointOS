import json
import unittest
from unittest.mock import patch

from cointos import backend_llama as backend
from cointos.state import CONFIG


class FakeConnection:
    """Streams the given events as llama-server would, and records whether it was closed."""
    lines: list[bytes] = []
    closed = False

    def __init__(self, *args, **kwargs):
        pass

    def request(self, *args, **kwargs):
        pass

    def getresponse(self):
        return self

    status = 200

    def __iter__(self):
        return iter(FakeConnection.lines)

    def close(self):
        FakeConnection.closed = True


def events(*items):
    return [b"data: " + json.dumps(item).encode() + b"\n" for item in items]


class BoundedSteps(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(backend._urls, {"m": "http://127.0.0.1:1"}))
        self.enterContext(patch.object(backend.http.client, "HTTPConnection", FakeConnection))
        FakeConnection.closed = False

    def test_a_lane_whose_state_the_server_dropped_is_lost_before_it_reads(self):
        FakeConnection.lines = events({"tokens": [0], "prompt_progress": {"total": 25584, "cache": 0, "processed": 0}},
                                      {"tokens": [0], "prompt_progress": {"total": 25584, "cache": 0, "processed": 1016}})
        with self.assertRaises(backend.Lost):
            backend.think(CONFIG, "m", 1, list(range(25584)), 25583, 96, {}, lambda new: None)
        self.assertTrue(FakeConnection.closed)

    def test_progress_placeholders_are_not_generated_tokens(self):
        FakeConnection.lines = events({"tokens": [0], "prompt_progress": {"total": 101, "cache": 100, "processed": 100}},
                                      {"tokens": [7, 8]}, {"tokens": [9], "stop": True, "stop_type": "limit"})
        seen = []
        result = backend.think(CONFIG, "m", 0, list(range(101)), 100, 3, {}, seen.extend)
        self.assertEqual(result["tokens"], [7, 8, 9])
        self.assertEqual(seen, [7, 8, 9])
        self.assertFalse(result["done"])

    def test_stepping_back_less_than_a_read_chunk_is_allowed(self):
        held = 5000
        FakeConnection.lines = events(
            {"tokens": [0], "prompt_progress": {"total": 6000, "cache": held - CONFIG["scheduler"]["read_chunk_tokens"],
                                                "processed": 0}},
            {"tokens": [], "stop": True, "stop_type": "limit"})
        backend.prefill(CONFIG, "m", 0, list(range(6000)), held)


if __name__ == "__main__":
    unittest.main()
