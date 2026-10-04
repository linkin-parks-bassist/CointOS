import unittest

from cointos import checks, config, memory

CONFIG = {
    "classes": ["coin", "user", "background"],
    "reserved_lanes": [],
    "memory": {"reserve_gb": 24, "max_psi": 1.0},
    "scheduler": {"slice_seconds": 30},
    "checks": {"idle_lane_seconds": 5, "preempt_seconds": 15, "starve_seconds": 120,
               "thought_stalled_seconds": 60, "alert_recovery_seconds": 30,
               "agent_silent_seconds": config.load()["checks"]["agent_silent_seconds"],
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

    def test_short_snapshot_keeps_measured_hybrid_state_overhead(self):
        # Measured b10723 Qwen3.8 disk saves: a fixed recurrent state dominates
        # short contexts, so scaling a long file downward severely underestimates.
        long = {"a": snap(.292743392, 1, tokens=2072)}
        self.assertEqual(memory.snapshot_gb(long, "work", 88), .30)
        long["b"] = snap(.162664416, 2, tokens=88)
        self.assertEqual(memory.snapshot_gb(long, "work", 88), .17)
        self.assertEqual(memory.snapshot_gb(long, "work", 1000), .30)
        self.assertGreaterEqual(memory.snapshot_gb(long, "work", 3000), .292743392 * 3000 / 2072)

    def test_estimate_does_not_undercut_a_larger_smaller_context_sample(self):
        snapshots = {"a": snap(2, 1, tokens=1000), "b": snap(1, 1, tokens=2000)}
        self.assertEqual(memory.snapshot_gb(snapshots, "work", 1500), 2)

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
            "since": since, "reading": reading, "progress_at": 1000}


def ledger(lanes, thoughts, agents=None, exiting=None, headroom=10.0):
    return {"lanes": lanes, "thoughts": {t["id"]: t for t in thoughts}, "agents": agents or {},
            "exiting": exiting or {}, "memory": {"headroom_gb": headroom, "psi": 0.0, "swap_gb": 0.0}}


class Checks(unittest.TestCase):
    def failing(self, state, now=100, processes=None):
        return {c["name"] for c in checks.evaluate(CONFIG, state, now, processes or {}) if not c["ok"]}

    def test_green(self):
        self.assertEqual(self.failing(ledger([lane()], [])), set())

    def test_stalled_coin_is_detected_even_while_it_claims_to_be_reading(self):
        stuck = {**thought('c', 'coin', lane=0, reading=True), 'progress_at': 10}
        state = ledger([lane(holder='c')], [stuck])
        self.assertIn('no stalled thought', self.failing(state, now=71))
        state['thoughts']['c']['lane'] = None
        state['thoughts']['c']['waiting_since'] = 10
        self.assertNotIn('no stalled thought', self.failing(state, now=1000))

    def test_flapping_check_notifies_once_until_sustained_recovery(self):
        incidents = {}
        bad = [{'name': 'starves', 'ok': False, 'detail': 'waiting 150s'}]
        good = [{'name': 'starves', 'ok': True, 'detail': ''}]
        self.assertEqual(len(checks.notifications(CONFIG, incidents, bad, 0)), 1)
        for at in range(1, 100):
            self.assertEqual(checks.notifications(CONFIG, incidents, good if at % 2 else bad, at), [])
        self.assertEqual(checks.notifications(CONFIG, incidents, good, 100), [])
        self.assertEqual(checks.notifications(CONFIG, incidents, good, 131), [])
        self.assertEqual(len(checks.notifications(CONFIG, incidents, bad, 132)), 1)

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

    def test_silence_boundary_applies_to_starting_and_running_agents(self):
        limit = CONFIG["checks"]["agent_silent_seconds"]
        for phase in ("starting", "running"):
            with self.subTest(phase=phase):
                state = ledger([], [], {"x": {"state": phase, "last_activity": 10, "repeats": 0}})
                self.assertEqual(checks.silent_agents(CONFIG, state, 10 + limit), [])
                self.assertEqual(checks.silent_agents(CONFIG, state, 10 + limit + .01), ["x"])
                state["agents"]["x"]["last_activity"] = 10 + limit
                self.assertEqual(checks.silent_agents(CONFIG, state, 10 + limit + .01), [])

    def test_a_waiting_or_reading_thought_is_not_tool_silence(self):
        for lane_id, reading in ((None, True), (0, True), (0, False)):
            with self.subTest(lane=lane_id, reading=reading):
                state = ledger([], [thought("t", "background", lane=lane_id, agent="x", reading=reading)],
                               {"x": {"state": "starting", "last_activity": 0, "repeats": 0}})
                self.assertEqual(checks.silent_agents(CONFIG, state, 1000), [])

    def test_agents_and_processes(self):
        agent = {"state": "running", "last_activity": 99, "repeats": 1}
        # Normal exit precedes asynchronous supervisor settlement. It is not a failure.
        self.assertEqual(self.failing(ledger([], [], {"a": agent})), set())
        self.assertEqual(self.failing(ledger([], [], {"a": {**agent, "state": "starting"}})), set())
        self.assertEqual(self.failing(ledger([], [], exiting={"b": 95}), processes={"b": [1]}), set())
        self.assertEqual(self.failing(ledger([], []), processes={"b": [1]}), {"no stray agent processes"})

    def test_memory(self):
        self.assertEqual(self.failing(ledger([], [], headroom=-1)), {"memory within bounds"})


if __name__ == "__main__":
    unittest.main()
