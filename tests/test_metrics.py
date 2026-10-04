"""Pipeline metrics summarize the journal's landings, gate returns and recoveries."""
import unittest

from cointos import metrics


class Summary(unittest.TestCase):
    def test_counts_landings_gates_and_recoveries(self):
        entries = [
            {"at": 1, "event": "task created", "task": "p:item-a"},
            {"at": 2, "event": "task created", "task": "p:decompose-item-a"},
            {"at": 3, "event": "task created", "task": "p:integrate-item-b-1"},
            {"at": 4, "event": "verified landing", "stage": "test-contract",
             "red_gate": {"expected_red": 2, "contracts_run": 5, "red_on_main": 1}},
            {"at": 5, "event": "verified landing", "stage": "implementation"},
            {"at": 6, "event": "landing gate rejected", "stage": "test-contract"},
            {"at": 7, "event": "brief infeasible", "task": "p:c", "missing": ["a.h::f"]},
            {"at": 8, "event": "receipt", "task": "p:item-a", "disposition": "blocked"},
        ]
        text = metrics.summary(entries, 24)
        for line in ("implementation 1, test-contract 1", "Gate returns:         test-contract 1",
                     "Infeasible briefs:    1", "Worker items started: 1", "Manager recoveries:   1",
                     "0 complete, 1 blocked", "2 declared reds verified", "Recoveries per landing: 0.50",
                     "Implementation share of landings: 50%", "infeasible p:c: a.h::f"):
            self.assertIn(line, text)
