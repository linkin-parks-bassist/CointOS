import copy
import unittest
from unittest import mock

from cointos import daemon, state

LIMITS = state.CONFIG["memory"]


class Ladder(unittest.TestCase):
    """Short headroom sheds memory; pressure yields background work without reload thrashing.
    Recovery waits for calm and enough room for the model."""

    def setUp(self):
        previous = copy.deepcopy(state.L)
        self.addCleanup(lambda: (state.L.clear(), state.L.update(previous)))
        state.L.clear()
        state.L.update(state.fresh({}))
        self.clock = 1000.0
        self.available, self.psi = 100.0, 0.0
        self.stopped, self.killed = [], []
        patches = [
            mock.patch.object(state.journal, "write"),
            mock.patch.object(daemon, "now", lambda: self.clock),
            mock.patch.object(state, "now", lambda: self.clock),
            mock.patch.object(daemon.memory, "measure",
                              lambda: {"physical_gb": 137.4, "available_gb": self.available, "swap_gb": 0, "psi": self.psi}),
            mock.patch.object(daemon.BACKEND, "budget", lambda config: None),
            mock.patch.object(daemon.BACKEND, "kill", lambda config, name: self.killed.append(name)),
            mock.patch.object(daemon.snapshots, "make_room", lambda need: False),
            mock.patch.object(daemon.lifecycle, "stop", lambda agent_id, *a, **k: self.stopped.append(agent_id)),
            mock.patch.object(daemon.threading, "Thread", lambda target, args, daemon: mock.Mock(start=lambda: target(*args))),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        state.L["agents"] = {"w": {"class": "background"}}

    def tick(self, seconds=1):
        self.clock += seconds
        daemon.guard()
        return state.L["guard"]

    def test_short_headroom_climbs_one_rung_at_a_time(self):
        self.available = LIMITS["reserve_gb"] - 5
        self.assertEqual(self.tick()["rung"], 2)
        self.assertEqual(self.stopped, ["w"])
        self.assertEqual(self.tick(0.5)["rung"], 2, "each rung's effect shows before the next")
        self.assertEqual(self.tick(LIMITS["shed_step_seconds"])["rung"], 3)
        self.assertEqual(self.killed, [state.CONFIG["work_model"]])

    def test_sustained_pressure_stops_background_without_unloading_a_model_that_fits(self):
        self.psi = LIMITS["max_psi"] + 2
        self.assertEqual(self.tick()["rung"], 0)
        self.assertEqual(self.tick(LIMITS["distress_seconds"])["rung"], 2)
        self.assertEqual(self.stopped, ["w"])
        self.assertEqual(self.tick(LIMITS["calm_seconds"] * 2)["rung"], 2)
        self.assertFalse(state.L["guard"]["killed"])
        self.assertTrue(state.L["guard"]["blocked"])
        self.assertEqual(self.killed, [])

    def test_pressure_does_not_skip_the_effect_of_stopping_background_before_unloading(self):
        self.psi = LIMITS["max_psi"] + 2
        self.tick()
        self.available = LIMITS["reserve_gb"] - 5
        self.assertEqual(self.tick(LIMITS["distress_seconds"])["rung"], 2)
        self.available = LIMITS["reserve_gb"] + 10  # the first shedding step restored headroom
        self.assertEqual(self.tick(LIMITS["shed_step_seconds"])["rung"], 2)
        self.assertEqual(self.killed, [])

    def test_persistent_shortage_still_unloads_under_pressure(self):
        self.psi = LIMITS["max_psi"] + 2
        self.available = LIMITS["reserve_gb"] - 5
        self.tick()
        self.assertEqual(self.tick(LIMITS["distress_seconds"])["rung"], 3)
        self.assertEqual(self.killed, [state.CONFIG["work_model"]])

    def test_positive_machine_headroom_does_not_hide_a_full_server_allowance(self):
        with mock.patch.object(daemon.BACKEND, "budget", return_value={"limit_gb": 77, "used_gb": 80}):
            self.assertEqual(self.tick()["rung"], 2)
            self.assertEqual(self.tick(LIMITS["shed_step_seconds"])["rung"], 3)
        self.assertEqual(self.killed, [state.CONFIG["work_model"]])

    def test_calm_comes_back_only_when_the_model_fits(self):
        self.available = LIMITS["reserve_gb"] - 5
        self.tick(); self.tick(LIMITS["shed_step_seconds"])
        self.available = LIMITS["reserve_gb"] + 10  # calm, but the work model does not fit yet
        self.assertEqual(self.tick(LIMITS["calm_seconds"] + 1)["rung"], 3)
        self.available = LIMITS["reserve_gb"] + 60
        self.tick()
        self.assertEqual(self.tick(LIMITS["calm_seconds"] + 1)["rung"], 2)
        self.assertEqual(self.tick(LIMITS["calm_seconds"] + 1)["rung"], 0, "rung 1 is not a state to wait at")
        self.assertFalse(state.L["guard"]["blocked"])


if __name__ == "__main__":
    unittest.main()
