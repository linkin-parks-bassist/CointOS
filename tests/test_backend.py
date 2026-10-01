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
                                      {"tokens": [], "stop": True, "stop_type": "limit", "tokens_cached": 101})
        seen = []
        terminal = {"tokens": [7, 8, 9], "tokens_predicted": 3, "tokens_cached": 103,
                    "stop": True, "stop_type": "limit"}
        with patch.object(backend, '_server', return_value=terminal) as request:
            result = backend.think(CONFIG, "m", 0, list(range(101)), 100, 3, {}, seen.extend)
        body = request.call_args.args[2]
        self.assertFalse(body['stream'])
        self.assertNotIn('content', body['response_fields'])
        self.assertEqual(json.loads(body['chat_parser'])['parsers'], [{'type': 'epsilon'}])
        self.assertEqual(result["tokens"], [7, 8, 9])
        self.assertEqual(seen, [7, 8, 9])
        self.assertFalse(result["done"])

    def test_utf8_byte_tokens_come_from_the_complete_token_step(self):
        FakeConnection.lines = events({'stop': True, 'stop_type': 'limit', 'tokens': [], 'tokens_cached': 2})
        terminal = {'tokens': [9008], 'tokens_predicted': 1, 'tokens_cached': 2,
                    'stop': True, 'stop_type': 'limit'}
        seen = []
        with patch.object(backend, '_server', return_value=terminal):
            result = backend.think(CONFIG, 'm', 0, [100, 101], 1, 1, {}, seen.extend)
        self.assertEqual(result['tokens'], [9008])
        self.assertEqual(seen, [9008])

    def test_incomplete_utf8_text_is_withheld_until_it_can_be_streamed_exactly(self):
        reader = {'thinking': False, 'tools': []}
        with patch.object(backend, '_server', return_value={'content': 'hello \ufffd'}):
            self.assertEqual(backend.read(CONFIG, 'm', reader, [1], False)['content'], 'hello ')
        with patch.object(backend, '_server', return_value={'content': 'hello 🦦'}):
            self.assertEqual(backend.read(CONFIG, 'm', reader, [1, 2], True)['content'], 'hello 🦦')

    def test_truncated_and_error_prefill_streams_fail_instead_of_becoming_known_state(self):
        for lines in (events({'prompt_progress': {'cache': 0}}), events({'error': {'message': 'broken stream'}})):
            with self.subTest(lines=lines):
                FakeConnection.lines = lines
                with self.assertRaises(RuntimeError):
                    backend.prefill(CONFIG, 'm', 0, [1, 2], 0)

    def test_missing_tokens_and_unknown_cached_state_fail_instead_of_replaying_the_step(self):
        FakeConnection.lines = events({'stop': True, 'stop_type': 'limit', 'tokens': [], 'tokens_cached': 2})
        valid = {'stop': True, 'stop_type': 'limit', 'tokens': [3], 'tokens_predicted': 1, 'tokens_cached': 2}
        for changes in ({'tokens': []}, {'tokens_cached': -1}, {'stop': False}, {'tokens': [], 'tokens_predicted': 0}):
            with self.subTest(changes=changes), patch.object(backend, '_server', return_value={**valid, **changes}):
                with self.assertRaises(RuntimeError):
                    backend.think(CONFIG, 'm', 0, [1, 2], 1, 1, {}, lambda _: None)

    def test_speculative_tail_is_cold_without_discarding_the_valid_reply(self):
        FakeConnection.lines = events({'stop': True, 'tokens_cached': 2})
        terminal = {'tokens': [3, 4], 'tokens_predicted': 2, 'tokens_cached': 7,
                    'stop': True, 'stop_type': 'eos'}
        with patch.object(backend, '_server', return_value=terminal):
            result = backend.think(CONFIG, 'm', 0, [1, 2], 1, 8, {}, lambda _: None)
        self.assertEqual(result['tokens'], [3, 4])
        self.assertTrue(result['done'])
        self.assertEqual(result['held'], [])

    def test_preparing_the_prefix_does_not_spend_generation_time(self):
        clock = [0]
        def prepare(*args):
            clock[0] = 50
        def generate(*args):
            clock[0] = 52
            return {'tokens': [3], 'tokens_predicted': 1, 'tokens_cached': 2,
                    'stop': True, 'stop_type': 'limit'}
        with patch.object(backend, 'prefill', side_effect=prepare), \
             patch.object(backend, '_server', side_effect=generate), \
             patch.object(backend.time, 'monotonic', side_effect=lambda: clock[0]):
            result = backend.think(CONFIG, 'm', 0, [1, 2], 1, 1, {}, lambda _: None)
        self.assertEqual(result['generation_seconds'], 2)

    def test_cache_check_extends_a_restored_hybrid_prefix(self):
        held = 2063
        class RestoredConnection(FakeConnection):
            def request(self, method, path, body, headers):
                self.total = len(json.loads(body)['prompt'])

            def __iter__(self):
                # Restored recurrent state has no earlier in-memory checkpoint.
                # An equal-length prompt must rewind and therefore loses its cache.
                cache = held if self.total > held else 0
                return iter(events({'prompt_progress': {'cache': cache}},
                                   {'stop': True, 'tokens_cached': self.total}))

        terminal = {'tokens': [7], 'tokens_predicted': 1, 'tokens_cached': held + 1,
                    'stop': True, 'stop_type': 'limit'}
        with patch.object(backend.http.client, 'HTTPConnection', RestoredConnection), \
                patch.object(backend, '_server', return_value=terminal):
            result = backend.think(CONFIG, 'm', 0, list(range(held + 1)), held, 1, {}, lambda _: None)
        self.assertEqual(result['tokens'], [7])

    def test_stepping_back_less_than_a_read_chunk_is_allowed(self):
        held = 5000
        FakeConnection.lines = events(
            {"tokens": [0], "prompt_progress": {"total": 6000, "cache": held - CONFIG["scheduler"]["read_chunk_tokens"],
                                                "processed": 0}},
            {"tokens": [], "stop": True, "stop_type": "limit", "tokens_cached": 6000})
        backend.prefill(CONFIG, "m", 0, list(range(6000)), held)


if __name__ == "__main__":
    unittest.main()
