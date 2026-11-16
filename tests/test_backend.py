import json
import unittest
from unittest.mock import patch

from cointos import backend_llama as backend
from cointos.state import CONFIG


class Rendering(unittest.TestCase):
    def test_native_snapshot_size_requires_matching_idle_slot_and_concrete_byte_count(self):
        with patch.object(backend, '_server', return_value=[
                {'id': 0, 'is_processing': True, 'state_size_bytes': 900, 'n_prompt_tokens': 10}]):
            self.assertIsNone(backend.snapshot_size(CONFIG, 'm', 0))
        with patch.object(backend, '_server', return_value=[
                {'id': 0, 'is_processing': False, 'state_size_bytes': 600000000, 'n_prompt_tokens': 33842}]):
            self.assertEqual(backend.snapshot_size(CONFIG, 'm', 0), {'tokens': 33842, 'bytes': 600000000})
        with patch.object(backend, '_server', return_value=[{'id': 0, 'is_processing': False}]):
            self.assertIsNone(backend.snapshot_size(CONFIG, 'm', 0))

    def test_leading_instruction_messages_render_as_one_without_mutating_history(self):
        messages = [{'role': 'system', 'content': 'System instructions'},
                    {'role': 'developer', 'content': 'Developer instructions'},
                    {'role': 'system', 'content': 'Project orientation'},
                    {'role': 'user', 'content': 'Work'}, {'role': 'assistant', 'content': 'Partial'}]
        def request(model, path, body, timeout):
            if path == '/apply-template':
                self.assertEqual(body['messages'], [
                    {'role': 'system', 'content': 'System instructions\n\nDeveloper instructions\n\nProject orientation'},
                    *messages[3:]])
                return {'prompt': 'rendered'}
            return {'tokens': [1, 2]}
        with patch.object(backend, '_server', side_effect=request):
            backend.render(CONFIG, 'm', {'messages': messages})
        self.assertEqual(len(messages), 5)
        self.assertEqual(messages[1]['role'], 'developer')
    def test_native_boolean_tool_parameters_keep_their_schema_types(self):
        native = ('<tool_call>\n<function=jobs>\n'
                  '<parameter=project>\nFalse\n</parameter>\n'
                  '<parameter=all>\nFalse\n</parameter>\n'
                  '</function>\n</tool_call>')
        reader = {'thinking': False, 'tools': [{'type': 'function', 'function': {
            'name': 'jobs', 'parameters': {'type': 'object', 'properties': {
                'project': {'type': 'string'}, 'all': {'type': 'boolean'}}}}}]}
        with patch.object(backend, '_server', return_value={'content': native}):
            self.assertEqual(backend.read(CONFIG, 'm', reader, [1], False)['tool_calls'], [])
            result = backend.read(CONFIG, 'm', reader, [1], True)
        arguments = json.loads(result['tool_calls'][0]['function']['arguments'])
        self.assertEqual(arguments, {'project': 'False', 'all': False})
        self.assertIs(arguments['all'], False)

    def test_empty_resume_step_opens_an_assistant_without_rewriting_history(self):
        messages = [{'role': 'user', 'content': 'Work'},
                    {'role': 'assistant', 'reasoning_content': 'Partial reasoning', 'content': ''},
                    {'role': 'assistant', 'content': None}]
        def request(model, path, body, timeout):
            if path == '/apply-template':
                self.assertEqual(body['messages'], messages)
                self.assertIs(body['continue_final_message'], False)
                self.assertIs(body['add_generation_prompt'], True)
                return {'prompt': '<|im_start|>assistant\n<think>\n'}
            return {'tokens': [1, 2]}
        with patch.object(backend, '_server', side_effect=request):
            self.assertTrue(backend.render(CONFIG, 'm', {'messages': messages})['reader']['thinking'])

    def test_resumed_reasoning_is_hidden_and_charged_to_its_existing_budget(self):
        opening = '<think>\n'
        assistant = opening + 'Partial reasoning'
        prompt = '<|im_start|>assistant\n<think>\nDone</think>\nEarlier answer<|im_end|>\n<|im_start|>assistant\n' + assistant
        tokenized = {prompt: [1, 2, 3], '</think>': [99],
                     '\n</think>\n\n': [10, 99, 10], opening: [98, 10],
                     assistant: [98, 10, 4, 5, 6]}
        def request(model, path, body, timeout):
            return {'prompt': prompt} if path == '/apply-template' else {'tokens': tokenized[body['content']]}
        with patch.object(backend, '_server', side_effect=request):
            reader = backend.render(CONFIG, 'm', {'messages': [], 'reasoning_budget': 4})['reader']
        self.assertTrue(reader['thinking'])
        self.assertEqual(reader['reasoning_used'], 3)
        with patch.object(backend, '_server', return_value={'content': 'More reasoning'}):
            result = backend.read(CONFIG, 'm', reader, [4], False)
        self.assertEqual(result['phase'], 'reasoning')
        self.assertEqual(result['content'], '')

    def test_completed_reasoning_does_not_reopen_on_literal_marker_in_answer(self):
        prompt = '<|im_start|>assistant\n<think>\nDone</think>\nThe literal marker is <think>\n'
        with patch.object(backend, '_server', side_effect=[{'prompt': prompt}, {'tokens': [1, 2]}]):
            reader = backend.render(CONFIG, 'm', {'messages': [], 'reasoning_budget': 4})['reader']
        self.assertFalse(reader['thinking'])
        self.assertNotIn('reasoning_budget', reader)

    def test_interrupted_assistant_continuation_preserves_history(self):
        messages = [{'role': 'user', 'content': 'Work'},
                    {'role': 'assistant', 'content': 'Completed step'},
                    {'role': 'assistant', 'content': 'Partial next step'}]
        def request(model, path, body, timeout):
            if path == '/apply-template':
                self.assertEqual(body['messages'], messages)
                self.assertTrue(body['continue_final_message'])
                self.assertFalse(body['add_generation_prompt'])
                return {'prompt': 'continued'}
            return {'tokens': [1, 2]}
        with patch.object(backend, '_server', side_effect=request):
            self.assertEqual(backend.render(CONFIG, 'm', {'messages': messages})['tokens'], [1, 2])


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

    def test_read_decode_and_request_time_remain_distinct(self):
        event = {'tokens': [3] * 32, 'tokens_predicted': 32, 'tokens_cached': 33,
                 'stop': True, 'stop_type': 'limit', 'timings': {
                     'predicted_n': 32, 'predicted_ms': 2000, 'prompt_n': 1,
                     'prompt_ms': 300, 'draft_n': 40, 'draft_n_accepted': 24}}
        with patch.object(backend, 'prefill', return_value={'prefill_tokens': 1, 'prefill_seconds': .2}), \
             patch.object(backend, '_server', return_value=event), \
             patch.object(backend.time, 'monotonic', side_effect=[0, .5, 4.5, 4.5]):
            result = backend.think(CONFIG, 'm', 0, [1, 2], 1, 32, {}, lambda _: None)
        self.assertEqual(result['decode_seconds'], 2)
        self.assertEqual(result['prefill_seconds'], .5)
        self.assertEqual(result['prefill_tokens'], 2)
        self.assertEqual(result['call_seconds'], 4.5)
        self.assertEqual(result['generation_seconds'], 4)  # Existing budget accounting is preserved.
        self.assertEqual(result['draft_tokens'], 40)
        self.assertEqual(result['draft_accepted_tokens'], 24)

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


class ResidentSlots(unittest.TestCase):
    def setUp(self):
        backend._SLOT_OF.clear()
        backend._SLOT_TOKENS.clear()
        backend._SLOT_TOUCH.clear()
        backend._ACTIVE_SLOT.clear()
        self.config = {"models": {"m": {"lanes": 1, "slots": 3, "resident": True}},
                       "snapshots": "/tmp", "timeouts": {"snapshot_seconds": 1}}

    def test_owner_slots_are_distinct_and_released(self):
        self.assertEqual(backend.select(self.config, "m", 0, "A"), [])
        backend._note_slot("m", 0, [1, 2, 3])
        self.assertEqual(backend.select(self.config, "m", 0, "A"), [1, 2, 3])
        backend.select(self.config, "m", 0, "B")
        self.assertEqual(sorted(backend.residents(self.config, "m")), ["A", "B"])
        self.assertNotEqual(backend._SLOT_OF[("m", "A")], backend._SLOT_OF[("m", "B")])
        backend.release_residents(self.config, "m", ["A"])
        self.assertEqual(backend.residents(self.config, "m"), ["B"])

    def test_full_slots_evict_the_least_recently_used_owner(self):
        config = {"models": {"m": {"lanes": 1, "slots": 2, "resident": True}},
                  "snapshots": "/tmp", "timeouts": {"snapshot_seconds": 1}}
        backend.select(config, "m", 0, "A")
        slot_a = backend._SLOT_OF[("m", "A")]
        backend.select(config, "m", 0, "B")
        slot_b = backend._SLOT_OF[("m", "B")]
        backend._SLOT_TOUCH[("m", slot_a)] = 2.0
        backend._SLOT_TOUCH[("m", slot_b)] = 1.0
        self.assertEqual(backend.eviction(config, "m", "C"), "B")
        self.assertIsNone(backend.eviction(config, "m", "A"))
        backend.select(config, "m", 0, "C")
        self.assertIn(("m", "A"), backend._SLOT_OF)
        self.assertNotIn(("m", "B"), backend._SLOT_OF)
        self.assertEqual(backend._SLOT_OF[("m", "C")], slot_b)

    def test_save_and_restore_use_the_selected_slot(self):
        paths = []
        def server(model, path, body, timeout):
            paths.append(path)
            return {"n_saved": 1, "n_restored": 1}
        backend.select(self.config, "m", 0, "A")
        backend.select(self.config, "m", 0, "B")
        backend.select(self.config, "m", 0, "A")
        with patch.object(backend, "_server", side_effect=server), \
                patch.object(backend.os.path, "getsize", return_value=10):
            backend.save(self.config, "m", 0, "x")
        self.assertEqual(paths[-1], "/slots/0?action=save")
        backend.select(self.config, "m", 0, "B")
        with patch.object(backend, "_server", side_effect=server):
            backend.restore(self.config, "m", 0, "x")
        self.assertEqual(paths[-1], "/slots/1?action=restore")

    def test_launch_flags_request_configured_slots(self):
        args = backend._wanted_args({"snapshots": "/tmp"},
                                    {"lanes": 1, "slots": 3, "args": "--x"})
        self.assertIn("--parallel 3", args)

    def test_resident_shape_reports_zero_extra_state(self):
        config = {"lemonade": "http://x", "snapshots": "/tmp",
                  "models": {"m": {"lanes": 1, "slots": 3, "resident": True,
                                   "ctx_size": 393216, "args": "--x"}},
                  "timeouts": {"lemonade_health_seconds": 1}}
        health = {"all_models_loaded": [{
            "model_name": "m", "loaded": True, "backend_url": "http://127.0.0.1:9/v1",
            "launch_command": ["--ctx-size", "393216", "--parallel", "3", "--x",
                               "--slot-save-path", "/tmp"]}]}
        with patch.object(backend, "_call", return_value=health):
            found = backend.models(config)
        self.assertEqual(found["m"].get("resident_state_bytes"), 0)


if __name__ == "__main__":
    unittest.main()
