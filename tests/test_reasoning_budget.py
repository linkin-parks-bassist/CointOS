import queue
import unittest
from unittest.mock import patch

from cointos import lanes, backend_llama as backend
from cointos.state import CONFIG


class ReasoningBudget(unittest.TestCase):
    def run_state(self, generated=(), budget=4, maximum=32):
        return {'reader': {'reasoning_budget': budget, 'think_end': 99, 'think_close': [10, 99, 10]},
                'generated': list(generated), 'max': maximum, 'queue': queue.Queue()}

    def step(self, run, chunk=96):
        thought = {'agent': 'budget-test', 'generated': len(run['generated'])}
        with patch.object(lanes, 'log'), patch.dict(lanes.L, {'agents': {}}):
            count = lanes.reasoning_step(thought, run, chunk)
        return count, thought

    def test_exact_boundary_closes_then_keeps_answer_capacity(self):
        run = self.run_state([1, 2, 3])
        self.assertEqual(self.step(run)[0], 1)
        run['generated'].append(4)
        count, thought = self.step(run)
        self.assertEqual(run['generated'], [1, 2, 3, 4, 10, 99, 10])
        self.assertEqual(run['queue'].get_nowait(), [10, 99, 10])
        self.assertTrue(thought['reasoning_budget_reached'])
        self.assertEqual(count, 25)
        self.step(run)
        self.assertTrue(run['queue'].empty(), 'Never inject a second closure')

    def test_natural_close_does_not_limit_answer_or_tool_tokens(self):
        run = self.run_state([1, 99, 2, 3, 4, 5])
        self.assertEqual(self.step(run)[0], 26)
        self.assertTrue(run['queue'].empty())

    def test_short_total_limit_reserves_closure_and_output(self):
        run = self.run_state([1, 2], budget=1024, maximum=6)
        self.assertEqual(self.step(run)[0], 1)
        self.assertEqual(run['generated'], [1, 2, 10, 99, 10])

    def test_unbudgeted_reply_unchanged(self):
        run = self.run_state([1, 2])
        run['reader'] = {'thinking': False}
        self.assertEqual(self.step(run)[0], 30)
        self.assertTrue(run['queue'].empty())

    def test_reader_recovers_tool_call_after_forced_close(self):
        text = 'Let me reconsider.\n</think>\n\n<tool_call>\n<function=bash>\n<parameter=command>\ntrue\n</parameter>\n</function>\n</tool_call>'
        with patch.object(backend, '_server', return_value={'content': text}):
            result = backend.read(CONFIG, 'm', {'thinking': True, 'tools': []}, [1], True)
        self.assertEqual(result['phase'], 'writing')
        self.assertEqual(result['reasoning'], 'Let me reconsider.')
        self.assertEqual(result['tool_calls'][0]['function']['name'], 'bash')
