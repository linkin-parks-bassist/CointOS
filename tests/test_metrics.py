"""Pipeline metrics summarize the journal's landings, gate returns and recoveries."""
import unittest

from cointos import metrics


class Summary(unittest.TestCase):
    def test_counts_landings_gates_and_recoveries(self):
        entries = [
            {"at": 1, "event": "task created", "task": "p:item-a"},
            {"at": 2, "event": "task created", "task": "p:decompose-item-a"},
            {"at": 3, "event": "task created", "task": "p:integrate-item-b-1"},
            {"at": 4, "event": "verified landing", "stage": "test-contract"},
            {"at": 4.5, "event": "packet tests failed", "task": "p:item-a"},
            {"at": 5, "event": "verified landing", "stage": "implementation"},
            {"at": 6, "event": "landing gate rejected", "stage": "test-contract"},
            {"at": 7, "event": "brief infeasible", "task": "p:c", "missing": ["a.h::f"]},
            {"at": 8, "event": "receipt", "task": "p:item-a", "disposition": "blocked"},
            {"at": 9, "event": "task created", "task": "p:plan", "kind": "breakdown"},
            {"at": 10, "event": "task created", "task": "p:operator-repair-a-1", "kind": "operator",
             "repair_origin": {"task": "p:item-a", "version": 1}},
            {"at": 11, "event": "agent ended", "role": "operator", "generation_seconds": 75,
             "generation_tokens": 1300},
        ]
        text = metrics.summary(entries, 24)
        for line in ("implementation 1, test-contract 1", "Gate returns:         test-contract 1",
                     "Infeasible briefs:    1", "Worker items started: 1", "Legacy manager passes: 1",
                     "Recovery controllers: 1", "Planning assignments: 1", "Recorded operator generation: 75s / 1300 tokens",
                     "0 complete, 1 blocked", "Packet test failures: 1", "Recoveries per landing: 1.00",
                     "Implementation share of landings: 50%", "infeasible p:c: a.h::f"):
            self.assertIn(line, text)
