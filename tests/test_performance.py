import unittest
import math
import subprocess
from pathlib import Path
from unittest.mock import patch
from cointos import performance, gateway, state


class RunningPerformance(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(performance, 'FILTERS', {}))

    def test_one_pole_uses_active_duration_not_wall_time(self):
        performance.record('generation', 100, 2, draft_tokens=200, accepted_tokens=100)
        initial = performance.snapshot()
        performance.record('prefill', 4000, 2)
        for _ in range(100):
            self.assertEqual(performance.snapshot()['generation_tps'], initial['generation_tps'])
            self.assertEqual(performance.snapshot()['mtp_acceptance'], initial['mtp_acceptance'])
        performance.record('generation', 900, 3, draft_tokens=800, accepted_tokens=600)
        alpha = 1 - math.exp(-3 / 10)
        result = performance.snapshot()
        self.assertAlmostEqual(result['generation_tps'], 50 + alpha * (300 - 50))
        self.assertEqual(result['prefill_tps'], 2000)
        drafted = 100 + alpha * (800 / 3 - 100)
        accepted = 50 + alpha * (600 / 3 - 50)
        self.assertAlmostEqual(result['mtp_acceptance'], 100 * accepted / drafted)
        self.assertNotIn('output_tps', result)

    def test_prefill_holds_during_generation_and_idle(self):
        performance.record('prefill', 1000, 1)
        performance.record('generation', 1000, 30)
        self.assertEqual(performance.snapshot()['prefill_tps'], 1000)
        performance.record('prefill', 3000, 1)
        self.assertAlmostEqual(performance.snapshot()['prefill_tps'],
                               1000 + (1 - math.exp(-.1)) * 2000)

    def test_constant_signal_is_invariant_to_step_partitioning(self):
        performance.record('generation', 10, 1)
        performance.record('generation', 200, 10)
        whole = performance.snapshot()['generation_tps']
        performance.FILTERS.clear()
        performance.record('generation', 10, 1)
        for _ in range(10):
            performance.record('generation', 20, 1)
        self.assertAlmostEqual(performance.snapshot()['generation_tps'], whole)

    def test_unmeasured_phase_is_unknown_and_zero_acceptance_is_real_zero(self):
        self.assertTrue(all(performance.snapshot()[key] is None for key in
                            ('generation_tps', 'prefill_tps', 'mtp_acceptance')))
        performance.record('generation', 10, 1, draft_tokens=20, accepted_tokens=0)
        self.assertEqual(performance.snapshot()['mtp_acceptance'], 0)

    def test_stopped_or_reused_coin_pid_does_not_leave_a_busy_card(self):
        identity = {'pid': 123, 'start_ticks': 10, 'boot_id': 'boot'}
        with patch.dict(state.L, coin={'busy': True, 'process': identity}), \
                patch.object(gateway.wakeups, 'boot_id', return_value='boot'):
            for process in [None, {'state': 'Z', 'start_ticks': 10}, {'state': 'S', 'start_ticks': 11}]:
                with patch.object(gateway.wakeups, 'process', return_value=process):
                    self.assertFalse(gateway.coin_view()['busy'])
            with patch.object(gateway.wakeups, 'process', return_value={'state': 'S', 'start_ticks': 10}):
                self.assertTrue(gateway.coin_view()['busy'])
            self.assertTrue(state.L['coin']['busy'])

    def test_top_row_formats_real_zero_and_missing_samples(self):
        script = r"""
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const html = fs.readFileSync('web/dashboard.html', 'utf8');
const elements = {performance: {children: []}};
for (const name of ['generation','prefill','mtp']) {
  const parts = {span: {}, b: {}, small: {}};
  elements['perf-'+name] = {querySelector: key => parts[key]};
}
const context = {$: id => elements[id], setText: (el, text) => el.textContent = text};
vm.createContext(context);
vm.runInContext(html.slice(html.indexOf('function renderPerformance('), html.indexOf('function render(L)')), context);
context.renderPerformance({performance: {generation_tps: 123.45, prefill_tps: 2000, mtp_acceptance: 0}});
assert.equal(elements['perf-generation'].querySelector('b').textContent, '123.5 tok/s');
assert.equal(elements['perf-mtp'].querySelector('b').textContent, '0%');
context.renderPerformance({});
assert.equal(elements['perf-mtp'].querySelector('b').textContent, '—');
assert.ok(elements['perf-mtp'].querySelector('small').textContent.includes('Waiting for phase'));
"""
        subprocess.run(['node', '-e', script], cwd=Path(__file__).resolve().parents[1],
                       capture_output=True, text=True, check=True, timeout=10)
