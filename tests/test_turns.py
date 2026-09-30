import copy
import queue
import unittest
from unittest.mock import patch

from cointos import lanes, state, settings

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

    def test_shorter_live_slice_yields_only_after_current_gpu_step(self):
        original = state.CONFIG["scheduler"]["slice_seconds"]
        self.addCleanup(lambda: state.CONFIG["scheduler"].update(slice_seconds=original))
        self.thought("a", [1, 2, 3, 4])
        lanes.schedule()
        self.read_done("a")
        lane = state.L["lanes"][0]
        began = state.now() - 10
        lane["turn_since"] = state.L["thoughts"]["a"]["since"] = began
        self.thought("b", [9, 9, 9])
        lanes.BUSY[0] = "a"
        settings.apply(5)
        self.assertEqual(lane["holder"], "a")
        self.assertEqual(lane["turn_since"], began)
        lanes.BUSY.clear()
        lanes.schedule()
        self.assertEqual(lane["holder"], "b")

    def test_longer_live_slice_keeps_elapsed_turn_and_reading_protection(self):
        original = state.CONFIG["scheduler"]["slice_seconds"]
        self.addCleanup(lambda: state.CONFIG["scheduler"].update(slice_seconds=original))
        self.thought("a", [1, 2, 3, 4])
        lanes.schedule()
        lane = state.L["lanes"][0]
        began = state.now() - 100
        lane["turn_since"] = state.L["thoughts"]["a"]["since"] = began
        self.thought("b", [9, 9, 9])
        settings.apply(1)
        self.assertEqual(lane["holder"], "a", "cold reading remains protected")
        self.read_done("a")
        began = state.now() - 10
        lane["turn_since"] = state.L["thoughts"]["a"]["since"] = began
        settings.apply(60)
        self.assertEqual(lane["holder"], "a")
        self.assertEqual(lane["turn_since"], began)

    def test_live_chunk_changes_take_effect_at_next_step_without_losing_tokens(self):
        original = state.CONFIG['scheduler']['chunk_tokens']
        self.addCleanup(lambda: state.CONFIG['scheduler'].update(chunk_tokens=original))
        self.addCleanup(state.STOPPING.clear)
        state.CONFIG['scheduler']['chunk_tokens'] = 96
        self.thought('a', [1, 2, 3])
        lanes.RUNS['a'].update(sampling={}, max=1000)
        lanes.schedule()
        self.read_done('a')
        calls = []
        def think(config, model, index, tokens, held, count, sampling, on_tokens):
            calls.append((count, list(tokens)))
            committed = len(lanes.RUNS['a']['generated'])
            for n in range(count):
                on_tokens([7])
                self.assertEqual(state.L['thoughts']['a']['generated'], committed + n + 1)
                self.assertEqual(len(lanes.RUNS['a']['generated']), committed)
            if len(calls) == 1:
                settings.apply(self.slice, 16)
                self.assertEqual(lanes.BUSY[0], 'a')
            else:
                state.STOPPING.set()
            return {'tokens': [7] * count, 'done': False}
        with patch.object(lanes.BACKEND, 'think', side_effect=think):
            lanes.worker(0)
        self.assertEqual([c[0] for c in calls], [96, 16])
        self.assertEqual(calls[1][1], [1, 2, 3] + [7] * 96)
        self.assertEqual(lanes.RUNS['a']['generated'], [7] * 112)
        self.assertEqual(state.L['thoughts']['a']['generated'], 112)

    def test_budget_closure_extends_warm_context_before_answer_generation(self):
        self.addCleanup(state.STOPPING.clear)
        self.thought('a', [1, 2, 3])
        run = lanes.RUNS['a']
        run.update(sampling={}, max=100, reader={'reasoning_budget': 2,
                   'think_end': 99, 'think_close': [10, 99, 10]})
        lanes.schedule()
        self.read_done('a')
        calls, reads = [], []
        def think(config, model, index, tokens, held, count, sampling, on_tokens):
            calls.append((list(tokens), held, count))
            new = [7, 8] if len(calls) == 1 else [42]
            on_tokens(new)
            if len(calls) == 2:
                state.STOPPING.set()
            return {'tokens': new, 'done': len(calls) == 2}
        def prefill(config, model, index, tokens, held):
            reads.append((list(tokens), held))
        with patch.object(lanes.BACKEND, 'think', side_effect=think), \
             patch.object(lanes.BACKEND, 'prefill', side_effect=prefill), \
             patch.object(lanes, 'log'):
            lanes.worker(0)
        self.assertEqual(calls[0][2], 2)
        self.assertEqual(reads, [([1, 2, 3, 7, 8, 10, 99], 4)])
        self.assertEqual(calls[1][:2], ([1, 2, 3, 7, 8, 10, 99, 10], 7))
        streamed = []
        while not run['queue'].empty():
            streamed.append(run['queue'].get_nowait())
        self.assertEqual(streamed, [[7, 8], [10, 99, 10], [42], {'end': 'done'}])

    def test_declared_shared_prefix_is_saved_without_a_concurrent_peer(self):
        self.addCleanup(state.STOPPING.clear)
        self.thought('a', [1, 2, 3, 4, 5])
        run = lanes.RUNS['a']
        run.update(sampling={}, max=100, reader={}, shared=3)
        lanes.schedule()
        saved = []

        def prefill(config, model, index, tokens, held):
            state.STOPPING.set()

        with patch.object(lanes.BACKEND, 'prefill', side_effect=prefill), \
             patch.object(lanes.snapshots, 'shared', return_value=False), \
             patch.object(lanes.snapshots, 'keep_shared', side_effect=lambda position, tokens: saved.append(list(tokens))):
            lanes.worker(0)
        self.assertEqual(saved, [[1, 2, 3]])

    def test_the_end_of_a_thought_restarts_the_silence_clock(self):
        state.L["agents"]["a"] = {"last_activity": state.now() - 2400, "repeats": 0, "last_thought": None,
                                  "thoughts": 0}
        self.thought("a", [1, 2, 3])
        lanes.finish("a", "failed")  # e.g. its model went away after a long thought
        self.assertLess(state.now() - state.L["agents"]["a"]["last_activity"], 1)


if __name__ == "__main__":
    unittest.main()
