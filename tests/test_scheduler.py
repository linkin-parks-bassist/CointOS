import unittest

from cointos import checks, scheduler

CONFIG = {
    "priorities": ["survivor", "coin", "user", "background"],
    "reserved_lanes": [{"model": "front", "lane": 1, "classes": ["survivor", "coin"]}],
    "warm_lane_grace_seconds": 30,
    "checks": {"lane_idle_seconds": 5, "coin_wait_seconds": 10, "agent_silent_seconds": 900,
               "max_identical_requests": 3},
    "limits": {"min_mem_available_gb": 24, "max_psi_full_avg10": 1.0, "max_swap_used_gb": 2},
}


def lane(model, index, occupant=None, last=None):
    return {"model": model, "index": index, "up": True, "occupant": occupant, "caller": occupant,
            "free_since": 0, "last_caller": last}


def request(id, klass, at, model="work", caller=None):
    return {"id": id, "caller": caller or id, "class": klass, "model": model, "queued_at": at, "lane": None}


class Assign(unittest.TestCase):
    def test_priority_then_age(self):
        lanes = [lane("work", 0)]
        waiting = [request("bg", "background", 1), request("user", "user", 5), request("coin", "coin", 9)]
        self.assertEqual(scheduler.assign(CONFIG, lanes, waiting, 10), [("coin", 0)])

    def test_oldest_first_within_class(self):
        lanes = [lane("work", 0), lane("work", 1, occupant="x")]
        waiting = [request("b", "background", 2), request("a", "background", 1)]
        self.assertEqual(scheduler.assign(CONFIG, lanes, waiting, 10), [("a", 0)])

    def test_reserved_lane_only_for_its_classes(self):
        lanes = [lane("front", 0, occupant="x"), lane("front", 1)]
        self.assertEqual(scheduler.assign(CONFIG, lanes, [request("u", "user", 1, "front")], 10), [])
        self.assertEqual(scheduler.assign(CONFIG, lanes, [request("c", "coin", 1, "front")], 10), [("c", 1)])

    def test_coin_prefers_unreserved_lane(self):
        lanes = [lane("front", 0), lane("front", 1)]
        self.assertEqual(scheduler.assign(CONFIG, lanes, [request("c", "coin", 1, "front")], 10), [("c", 0)])

    def test_warm_lane_preferred_within_grace(self):
        lanes = [lane("work", 0, last="agent-b"), lane("work", 1, occupant="x")]
        waiting = [request("r1", "background", 1, caller="agent-a"), request("r2", "background", 2, caller="agent-b")]
        self.assertEqual(scheduler.assign(CONFIG, lanes, waiting, 10), [("r2", 0)])
        self.assertEqual(scheduler.assign(CONFIG, lanes, waiting, 100), [("r1", 0)])

    def test_blocked_class_waits(self):
        lanes = [lane("work", 0)]
        waiting = [request("bg", "background", 1)]
        self.assertEqual(scheduler.assign(CONFIG, lanes, waiting, 10, frozenset({"background"})), [])

    def test_two_lanes_two_requests(self):
        lanes = [lane("work", 0), lane("work", 1)]
        waiting = [request("a", "background", 1), request("b", "background", 2), request("c", "background", 3)]
        self.assertEqual(sorted(scheduler.assign(CONFIG, lanes, waiting, 10)), [("a", 0), ("b", 1)])


class Checks(unittest.TestCase):
    def ledger(self, lanes, requests, agents=None):
        return {"lanes": lanes, "requests": {r["id"]: r for r in requests}, "agents": agents or {},
                "machine": {"mem_available_gb": 50, "psi_full_avg10": 0, "swap_used_gb": 0}}

    def failing(self, ledger, now=100, processes=None):
        return {c["name"] for c in checks.evaluate(CONFIG, ledger, now, processes or {}) if not c["ok"]}

    def test_green(self):
        self.assertEqual(self.failing(self.ledger([lane("work", 0)], [])), set())

    def test_idle_lane_with_waiting_work(self):
        self.assertEqual(self.failing(self.ledger([lane("work", 0)], [request("a", "background", 90)])),
                         {"lanes busy when work waits"})

    def test_coin_waits_too_long(self):
        found = self.failing(self.ledger([lane("front", 0, "x"), lane("front", 1, "y")], [request("c", "coin", 80, "front")]))
        self.assertIn("reserved lane serves within limit", found)

    def test_agents_and_processes(self):
        agent = {"last_activity": 99, "repeats": 1}
        self.assertEqual(self.failing(self.ledger([], [], {"a": agent})), {"agents match processes"})
        self.assertEqual(self.failing(self.ledger([], [], {"a": agent}), processes={"a": [1]}), set())
        self.assertEqual(self.failing(self.ledger([], []), processes={"b": [1]}), {"agents match processes"})


if __name__ == "__main__":
    unittest.main()
