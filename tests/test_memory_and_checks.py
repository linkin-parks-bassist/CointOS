import unittest

from cointos import checks, memory

CONFIG = {
    "classes": ["survivor", "coin", "user", "background"],
    "reserved_lanes": [],
    "memory": {"reserve_gb": 24, "max_psi": 1.0},
    "scheduler": {"slice_seconds": 30},
    "checks": {"idle_lane_seconds": 5, "preempt_seconds": 15, "starve_seconds": 120, "agent_silent_seconds": 900,
               "max_identical_thoughts": 3},
}


def snap(bytes_gb, last_run, model="work", tokens=10_000):
    return {"model": model, "tokens": tokens, "bytes": bytes_gb * 1e9, "last_run": last_run}


class Memory(unittest.TestCase):
    def test_nothing_forgotten_when_it_fits(self):
        self.assertEqual(memory.to_forget({"a": snap(2, 1)}, need_gb=1, headroom=5), [])

    def test_least_recently_run_forgotten_first(self):
        snapshots = {"new": snap(2, 50), "old": snap(2, 10), "mid": snap(2, 30)}
        self.assertEqual(memory.to_forget(snapshots, need_gb=3, headroom=0), ["old", "mid"])

    def test_negative_headroom_is_restored_by_forgetting(self):
        self.assertEqual(memory.to_forget({"a": snap(3, 1), "b": snap(3, 2)}, need_gb=0, headroom=-2), ["a"])

    def test_none_when_even_forgetting_everything_is_not_enough(self):
        self.assertIsNone(memory.to_forget({"a": snap(1, 1)}, need_gb=10, headroom=2))

    def test_snapshot_size_estimated_per_model(self):
        snapshots = {"a": snap(1, 1, tokens=10_000), "b": snap(4, 1, model="other")}
        self.assertEqual(memory.snapshot_gb(snapshots, "work", 30_000), 3.0)
        self.assertEqual(memory.snapshot_gb(snapshots, "unseen", 30_000), 0.0)

    def test_distress_is_pressure_not_swap_in_use(self):
        self.assertEqual(memory.distressed(CONFIG, {"psi": 0.2, "swap_gb": 5}), [])
        self.assertEqual(len(memory.distressed(CONFIG, {"psi": 3.0, "swap_gb": 0})), 1)

    def test_headroom_is_the_tighter_limit(self):
        measured = {"available_gb": 80}
        self.assertEqual(memory.headroom_gb(CONFIG, measured, None), 56)
        self.assertEqual(memory.headroom_gb(CONFIG, measured, {"limit_gb": 77, "used_gb": 60}), 17)


def lane(holder=None, free_since=0, model="work", index=0):
    return {"model": model, "index": index, "up": True, "holder": holder, "free_since": free_since}


def thought(id, klass, lane=None, waiting_since=None, agent=None, model="work", since=0, reading=False):
    return {"id": id, "agent": agent or id, "class": klass, "model": model, "lane": lane, "waiting_since": waiting_since,
            "since": since, "reading": reading}


def ledger(lanes, thoughts, agents=None, exiting=None, headroom=10.0):
    return {"lanes": lanes, "thoughts": {t["id"]: t for t in thoughts}, "agents": agents or {},
            "exiting": exiting or {}, "memory": {"headroom_gb": headroom, "psi": 0.0, "swap_gb": 0.0}}


class Checks(unittest.TestCase):
    def failing(self, state, now=100, processes=None):
        return {c["name"] for c in checks.evaluate(CONFIG, state, now, processes or {}) if not c["ok"]}

    def test_green(self):
        self.assertEqual(self.failing(ledger([lane()], [])), set())

    def test_idle_lane_while_an_agent_waits(self):
        self.assertEqual(self.failing(ledger([lane()], [thought("a", "background", waiting_since=90)])),
                         {"no lane idle while an agent waits"})

    def test_higher_class_kept_waiting_behind_a_lower_one(self):
        state = ledger([lane(holder="bg")], [thought("bg", "background", lane=0), thought("c", "coin", waiting_since=50)])
        self.assertIn("higher classes pre-empt", self.failing(state))

    def test_starving_behind_an_equal_past_its_slice(self):
        state = ledger([lane(holder="a")], [thought("a", "background", lane=0), thought("b", "background", waiting_since=0)])
        self.assertIn("no agent starves", self.failing(state, now=500))

    def test_waiting_long_behind_reads_is_not_starving_the_moment_a_slice_ends(self):
        state = ledger([lane(holder="a")], [thought("a", "background", lane=0, since=460),
                                            thought("b", "background", waiting_since=0)])
        self.assertNotIn("no agent starves", self.failing(state, now=500))

    def test_waiting_behind_a_cold_read_is_not_starving(self):
        state = ledger([lane(holder="a")], [thought("a", "background", lane=0, reading=True),
                                            thought("b", "background", waiting_since=0)])
        self.assertNotIn("no agent starves", self.failing(state, now=500))

    def test_a_lane_kept_for_an_agent_is_not_idle(self):
        kept = {**lane(), "held_for": "x", "held_class": "background", "held_until": 110}
        self.assertEqual(self.failing(ledger([kept], [thought("a", "background", waiting_since=90)])), set())

    def test_silent_only_while_running_tools(self):
        agent = {"state": "running", "last_activity": 0, "repeats": 1}
        self.assertIn("no silent agent", self.failing(ledger([], [], {"x": agent}), now=1000, processes={"x": [1]}))
        state = ledger([lane(holder="t")], [thought("t", "background", lane=0, agent="x")], {"x": agent})
        self.assertNotIn("no silent agent", self.failing(state, now=1000, processes={"x": [1]}))

    def test_agents_and_processes(self):
        agent = {"state": "running", "last_activity": 99, "repeats": 1}
        self.assertEqual(self.failing(ledger([], [], {"a": agent})), {"agents match processes"})
        self.assertEqual(self.failing(ledger([], [], {"a": {**agent, "state": "starting"}})), set())
        self.assertEqual(self.failing(ledger([], [], exiting={"b": 95}), processes={"b": [1]}), set())
        self.assertEqual(self.failing(ledger([], []), processes={"b": [1]}), {"agents match processes"})

    def test_memory(self):
        self.assertEqual(self.failing(ledger([], [], headroom=-1)), {"memory within bounds"})


if __name__ == "__main__":
    unittest.main()
