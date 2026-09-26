import copy
import queue
import unittest

from cointos import lanes, state

WORK = state.CONFIG["work_model"]


class Turns(unittest.TestCase):
    """The slice clock belongs to the turn: it starts when the turn's opening read is done and
    runs on through quick tool calls, so a burst of tool calls cannot hold a lane indefinitely."""

    def setUp(self):
        previous = copy.deepcopy(state.L)
        self.addCleanup(lambda: (state.L.clear(), state.L.update(previous)))
        for table in (lanes.RUNS, lanes.BUSY, lanes.HELD):
            saved = dict(table)
            self.addCleanup(lambda table=table, saved=saved: (table.clear(), table.update(saved)))
            table.clear()
        state.L.clear()
        state.L.update(state.fresh({}))
        state.L["lanes"] = [lane for lane in state.L["lanes"] if lane["model"] == WORK][:1]
        state.L["lanes"][0]["up"] = True
        self.slice = state.CONFIG["scheduler"]["slice_seconds"]
        state.LOCK.acquire()  # the scheduler's callers hold the ledger lock
        self.addCleanup(state.LOCK.release)

    def thought(self, agent, tokens):
        state.L["thoughts"][agent] = {
            "id": agent, "agent": agent, "class": "background", "owner": agent, "model": WORK, "lane": None,
            "since": None, "waiting_since": state.now(), "warm": [], "reading": True, "opens_turn": False,
            "started_at": state.now(), "generated": 0, "prompt": len(tokens)}
        lanes.RUNS[agent] = {"prompt": tokens, "generated": [], "queue": queue.Queue(), "cancelled": False}

    def read_done(self, agent):
        lanes.HELD[0] = lanes.tokens_of(agent)[:-1]
        lanes.schedule()

    def test_a_tool_call_does_not_restart_the_slice(self):
        lane = state.L["lanes"][0]
        turn_began = state.now() - self.slice - 5
        # Agent a's previous thought ended with a tool call; the lane is kept for it.
        lane.update(turn_agent="a", turn_since=turn_began, held_for="a", held_class="background",
                    held_until=state.now() + 10)
        lanes.HELD[0] = [1, 2, 3]
        self.thought("a", [1, 2, 3, 4, 5])  # its context plus the tool's result
        lanes.schedule()
        self.assertEqual(lane["holder"], "a")
        self.read_done("a")
        self.assertEqual(state.L["thoughts"]["a"]["since"], turn_began)
        self.thought("b", [9, 9, 9])  # an equal starts waiting
        lanes.schedule()
        self.assertEqual(lane["holder"], "b", "a's turn is past its slice, so the waiting equal gets the lane")

    def test_a_new_turn_starts_its_slice_when_its_read_is_done(self):
        lane = state.L["lanes"][0]
        self.thought("a", [1, 2, 3, 4, 5])
        lanes.schedule()
        self.assertEqual(lane["holder"], "a")
        state.L["thoughts"]["a"]["since"] = lane["turn_since"] = state.now() - self.slice - 5  # a long cold read
        self.read_done("a")
        self.thought("b", [9, 9, 9])
        lanes.schedule()
        self.assertEqual(lane["holder"], "a", "a cold agent is not pre-empted the moment it finishes reading")

    def finish_on_lane(self, agent, turn_began):
        lane = state.L["lanes"][0]
        lane.update(turn_agent=agent, turn_since=turn_began)
        self.thought(agent, [1, 2, 3])
        lanes.schedule()
        lane["turn_since"] = turn_began
        lanes.finish(agent, "done")  # its thought ended with a tool call
        return lane

    def test_past_its_slice_a_tool_call_is_a_plain_yield(self):
        lane = self.finish_on_lane("a", state.now() - self.slice - 5)
        self.assertIsNone(lane["held_for"], "the cooldown is over: the lane is not kept for a")

    def test_inside_its_slice_a_tool_call_keeps_the_lane_but_never_past_the_slice(self):
        turn_began = state.now() - self.slice + 3
        lane = self.finish_on_lane("a", turn_began)
        self.assertEqual(lane["held_for"], "a")
        self.assertLessEqual(lane["held_until"], turn_began + self.slice)

    def test_the_end_of_a_thought_restarts_the_silence_clock(self):
        state.L["agents"]["a"] = {"last_activity": state.now() - 2400, "repeats": 0, "last_thought": None,
                                  "thoughts": 0}
        self.thought("a", [1, 2, 3])
        lanes.finish("a", "failed")  # e.g. its model went away after a long thought
        self.assertLess(state.now() - state.L["agents"]["a"]["last_activity"], 1)


if __name__ == "__main__":
    unittest.main()
