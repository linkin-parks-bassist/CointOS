import copy
import unittest
from unittest import mock

from cointos import lanes, state

WORK = state.CONFIG["work_model"]


class Snapshots(unittest.TestCase):
    """Only a conversation that can go on keeps saved contexts, and only ones it can go on from."""

    def setUp(self):
        previous = copy.deepcopy(state.L)
        self.addCleanup(lambda: (state.L.clear(), state.L.update(previous)))
        saved = dict(lanes.HELD)
        self.addCleanup(lambda: (lanes.HELD.clear(), lanes.HELD.update(saved)))
        state.L.clear()
        state.L.update(state.fresh({}))
        state.L["lanes"] = [lane for lane in state.L["lanes"] if lane["model"] == WORK][:1]
        state.L["tasks"]["t"] = {"id": "t", "status": "running"}
        self.forgotten = []
        self.enterContext(mock.patch.object(lanes.BACKEND, "save", self.save))
        self.enterContext(mock.patch.object(lanes.BACKEND, "forget", lambda config, name: self.forgotten.append(name)))
        self.enterContext(mock.patch.object(lanes.BACKEND, "restore", lambda config, model, index, name: True))
        self.enterContext(mock.patch.object(lanes, "make_room", lambda need: True))
        self.while_saving = lambda: None

    def save(self, config, model, index, name):
        self.while_saving()  # a save takes seconds, outside the lock
        return {"bytes": 1}

    def test_a_state_saved_as_its_task_ends_is_not_kept(self):
        self.while_saving = lambda: state.L["tasks"]["t"].update(status="done")
        self.assertFalse(lanes.keep(0, [1, 2, 3], "t", "suspended"))
        self.assertEqual(state.L["snapshots"], {})
        self.assertEqual(len(self.forgotten), 1)

    def test_a_task_does_not_save_the_state_its_next_thought_has_left_behind(self):
        # The lane holds the end of t's last thought, which the conversation, as rendered
        # again for its next thought, does not go on from.
        state.L["lanes"][0]["resident"] = "t"
        lanes.HELD[0] = [1, 2, 3, 40, 41]
        lanes.switch(0, [1, 2, 3, 50, 51, 52], "t")
        self.assertEqual(state.L["snapshots"], {})

    def test_another_conversation_is_saved_when_switched_out(self):
        state.L["tasks"]["u"] = {"id": "u", "status": "running"}
        state.L["lanes"][0]["resident"] = "u"
        lanes.HELD[0] = [7, 8, 9]
        lanes.switch(0, [1, 2, 3], "t")
        self.assertEqual([s["owner"] for s in state.L["snapshots"].values()], ["u"])


if __name__ == "__main__":
    unittest.main()
