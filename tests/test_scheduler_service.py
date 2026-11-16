"""Local allocation must ignore historical usage and retain weighted odds."""
import copy
import unittest
from cointos import scheduler, state, config
from tests.test_scheduler import lane, waiting, holding, CONFIG


class LocalAllocation(unittest.TestCase):
    def test_restart_discards_legacy_accounts(self):
        self.assertNotIn('scheduler_service', state.fresh({'scheduler_service': {'work': {'coin': 20969}}}))

    def test_history_cannot_change_a_current_decision(self):
        thoughts = [dict(waiting('worker', 'background', 0), weight=2),
                    dict(waiting('operator', 'user', 0), weight=100)]
        for now in range(30, 3030, 30):
            expected = scheduler.assign(CONFIG, [lane('work', 0)], thoughts, now)
            historical = copy.deepcopy(thoughts)
            historical[0]['service'] = 10**12
            historical[1]['service'] = 0
            self.assertEqual(scheduler.assign(CONFIG, [lane('work', 0)], historical, now), expected)
            self.assertEqual(thoughts[0].get('service'), None)

    def test_weighted_draw_approximates_priority_without_bookkeeping(self):
        thoughts = [dict(waiting('a', 'background', 0), weight=1),
                    dict(waiting('b', 'background', 0), weight=3)]
        before = copy.deepcopy(thoughts)
        wins = sum(scheduler.assign(CONFIG, [lane('work', 0)], thoughts, now)[0] == 'b'
                   for now in range(0, 120000, 30))
        self.assertTrue(2800 < wins < 3200, wins)
        self.assertEqual(thoughts, before)

    def test_coin_preempts_background_for_every_draw_despite_old_score(self):
        bg = dict(holding('worker', 'background', 0, 99, reading=True), weight=2, service=3715)
        coin = dict(waiting('coin', 'coin', 100), weight=1000, service=20969)
        for now in range(100, 400, 30):
            self.assertEqual(scheduler.assign(CONFIG, [lane('work', 0, holder='worker')], [bg, coin], now), {0: 'coin'})
