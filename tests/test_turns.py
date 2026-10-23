import copy
import queue
import unittest
from unittest.mock import patch

from cointos import lanes, state, settings, runs

WORK = state.CONFIG["work_model"]


class Turns(unittest.TestCase):
    """The slice clock belongs to the turn: it counts reading and generation and
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
            "started_at": state.now(), "generated": 0, "prompt": len(tokens), "read": 0, "progress_at": state.now()}
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
        with patch.object(lanes.scheduler, "draw", lambda config, thought, now: {"a": 0.1, "b": 0.9}[thought["agent"]]):
            lanes.schedule()
        self.assertEqual(lane["holder"], "b", "a's turn is past its slice, so a waiting equal that draws higher gets the lane")

    def test_finishing_a_cold_read_does_not_restart_the_slice(self):
        lane = state.L["lanes"][0]
        self.thought("a", [1, 2, 3, 4, 5])
        lanes.schedule()
        self.assertEqual(lane["holder"], "a")
        state.L["thoughts"]["a"]["since"] = lane["turn_since"] = state.now() - self.slice - 5  # a long cold read
        began = lane["turn_since"]
        self.read_done("a")
        self.assertEqual(lane["turn_since"], began)
        self.thought("b", [9, 9, 9])
        with patch.object(lanes.scheduler, "draw", lambda config, thought, now: {"a": 0.1, "b": 0.9}[thought["agent"]]):
            lanes.schedule()
        self.assertEqual(lane["holder"], "b")

    def test_partial_read_yields_and_resumes_its_saved_prefix(self):
        self.addCleanup(state.STOPPING.clear)
        clock = [100.0]
        native, cache, reads, replies = [], {}, [], []
        with patch.object(lanes, 'now', side_effect=lambda: clock[0]):
            self.thought('a', list(range(5000)))
            self.thought('b', [9001, 9002, 9003])
            for agent in ('a', 'b'):
                lanes.RUNS[agent].update(sampling={}, max=100, reader={})
                state.L['tasks'][agent] = {'status': 'running'}
            with patch.object(lanes.scheduler, 'draw', lambda config, thought, now: {'a': .9, 'b': .1}[thought['agent']]):
                lanes.schedule()

            def prefill(config, model, index, tokens, held):
                if held:
                    self.assertEqual(native, tokens[:held])
                reads.append((tokens[0], held, len(tokens)))
                native[:] = tokens
                clock[0] += self.slice + 1
                if len(reads) == 3:
                    state.STOPPING.set()

            def save(config, model, index, name):
                cache[name] = list(native)
                return {'bytes': 100}

            def restore(config, model, index, name):
                native[:] = cache[name]
                return True

            def think(config, model, index, tokens, held, count, sampling, on_tokens):
                self.assertEqual(native, tokens[:held])
                replies.append(tokens[0])
                on_tokens([77])
                native[:] = tokens
                return {'tokens': [77], 'held': list(tokens), 'done': True}

            with patch.object(lanes.scheduler, 'draw', lambda config, thought, now: {'a': .1, 'b': .9}[thought['agent']]), \
                 patch.object(lanes.BACKEND, 'prefill', side_effect=prefill), \
                 patch.object(lanes.BACKEND, 'save', side_effect=save), \
                 patch.object(lanes.BACKEND, 'restore', side_effect=restore), \
                 patch.object(lanes.BACKEND, 'forget', side_effect=lambda config, name: cache.pop(name, None)), \
                 patch.object(lanes.BACKEND, 'think', side_effect=think), \
                 patch.object(lanes.snapshots, 'room', return_value=True), \
                 patch.object(lanes.snapshots, 'make_room', return_value=True), \
                 patch.object(lanes, 'log'):
                lanes.worker(0)
        chunk = state.CONFIG['scheduler']['read_chunk_tokens']
        self.assertEqual(reads, [(0, 0, chunk), (9001, 0, 2), (0, chunk, chunk * 2)])
        self.assertEqual(replies, [9001])
        self.assertIn('a', state.L['thoughts'])

    def test_small_tail_edit_reuses_the_single_earlier_checkpoint(self):
        self.addCleanup(state.STOPPING.clear)
        native, cache, reads = [], {}, []
        original = list(range(3000))
        def prefill(config, model, index, tokens, held):
            if held: self.assertEqual(native, tokens[:held])
            reads.append((held, len(tokens)))
            native[:] = tokens
        def save(config, model, index, name):
            cache[name] = list(native)
            return {'bytes': 100}
        def restore(config, model, index, name):
            native[:] = cache[name]
            return True
        def think(config, model, index, tokens, held, count, sampling, on_tokens):
            self.assertEqual(native, tokens[:held])
            state.STOPPING.set()
            return {'tokens': [77], 'held': tokens + [77], 'done': True}
        with patch.object(lanes.BACKEND, 'prefill', side_effect=prefill), \
             patch.object(lanes.BACKEND, 'save', side_effect=save), \
             patch.object(lanes.BACKEND, 'restore', side_effect=restore), \
             patch.object(lanes.BACKEND, 'forget', side_effect=lambda config, name: cache.pop(name, None)), \
             patch.object(lanes.BACKEND, 'think', side_effect=think), \
             patch.object(lanes.snapshots, 'room', return_value=True), \
             patch.object(lanes.snapshots, 'make_room', return_value=True), patch.object(lanes, 'log'):
            self.thought('user', original)
            lanes.RUNS['user'].update(sampling={}, max=100, reader={})
            lanes.schedule(); lanes.worker(0)
            self.assertEqual([s['tokens'] for s in state.L['snapshots'].values()], [2967])
            state.STOPPING.clear(); lanes.HELD.clear(); native.clear(); reads.clear()
            edited = original[:-16] + list(range(9000, 9016))
            self.thought('user', edited)
            lanes.RUNS['user'].update(sampling={}, max=100, reader={})
            lanes.schedule(); lanes.worker(0)
            self.assertEqual(reads, [(2967, 2999)])
            self.assertEqual(len(state.L['snapshots']), 1)
            state.STOPPING.clear(); reads.clear()
            lanes.HELD[0] = original[:2980]; native[:] = original[:2980]
            self.thought('user', original)
            lanes.RUNS['user'].update(sampling={}, max=100, reader={})
            lanes.schedule(); lanes.worker(0)
            self.assertEqual(reads, [(2980, 2981), (2981, 2999)])
            self.assertEqual([s['tokens'] for s in state.L['snapshots'].values()], [2981])

    def test_failed_checkpoint_keeps_the_successful_partial_read(self):
        for failure in (False, OSError('no space')):
            with self.subTest(failure=failure):
                self.thought('a', list(range(5000)))
                self.thought('b', [9001, 9002, 9003])
                lane = state.L['lanes'][0]
                lane.update(holder='a')
                state.L['thoughts']['a'].update(lane=0, since=state.now() - self.slice - 1)
                held = list(range(1024))
                lanes.HELD[0] = held
                kwargs = {'side_effect': failure} if isinstance(failure, Exception) else {'return_value': False}
                with patch.object(lanes.scheduler, 'draw', lambda config, thought, now: {'a': .1, 'b': .9}[thought['agent']]), \
                     patch.object(lanes.snapshots, 'keep', **kwargs), patch.object(lanes, 'log'):
                    lanes.checkpoint_read(0, 'a', held)
                    lanes.schedule()
                self.assertEqual(lane['holder'], 'a')
                self.assertEqual(lanes.HELD[0], held)
                self.assertFalse(state.L['thoughts']['a']['read_checkpoint'])

    def test_coin_history_prefix_restores_after_tail_rebuild_and_resets_on_rollover(self):
        self.addCleanup(state.STOPPING.clear)
        native, cache, reads = [], {}, []
        owner = 'coin/history-fixture'
        def prefill(config, model, index, tokens, held):
            if held:
                self.assertEqual(native, tokens[:held])
            reads.append((held, len(tokens)))
            native[:] = tokens
        def save(config, model, index, name):
            cache[name] = list(native)
            return {'bytes': 100}
        def restore(config, model, index, name):
            native[:] = cache[name]
            return True
        def think(config, model, index, tokens, held, count, sampling, on_tokens):
            self.assertEqual(native, tokens[:held])
            state.STOPPING.set()
            return {'tokens': [77], 'held': tokens + [77], 'done': True}
        def run(tokens, prefix):
            state.STOPPING.clear()
            lanes.HELD.clear()
            native.clear()
            reads.clear()
            lanes.snapshots.forget_diverged(owner, WORK, tokens)
            self.thought(owner, tokens)
            lanes.RUNS[owner].update(sampling={}, max=100, reader={}, retained_prefix=prefix, shared=[1000])
            lanes.schedule()
            lanes.worker(0)
        with patch.object(lanes.BACKEND, 'prefill', side_effect=prefill), \
             patch.object(lanes.BACKEND, 'save', side_effect=save), \
             patch.object(lanes.BACKEND, 'restore', side_effect=restore), \
             patch.object(lanes.BACKEND, 'forget', side_effect=lambda config, name: cache.pop(name, None)), \
             patch.object(lanes.BACKEND, 'think', side_effect=think), \
             patch.object(lanes.snapshots, 'room', return_value=True), \
             patch.object(lanes.snapshots, 'make_room', return_value=True), patch.object(lanes, 'log'):
            run(list(range(3000)), 2000)
            self.assertEqual(sorted((s['tokens'], s['kind']) for s in state.L['snapshots'].values() if s['owner'] == owner),
                             [(2000, 'prefix'), (2967, 'checkpoint')])
            run(list(range(2100)) + list(range(10000, 10900)), 2100)
            self.assertEqual(reads[0], (2000, 2100))
            self.assertEqual(sorted((s['tokens'], s['kind']) for s in state.L['snapshots'].values() if s['owner'] == owner),
                             [(2100, 'prefix'), (2967, 'checkpoint')])
            run(list(range(1000)) + list(range(20000, 22000)), 1900)
            self.assertEqual(reads[0], (1000, 1900))
            self.assertEqual(sorted((s['tokens'], s['kind']) for s in state.L['snapshots'].values() if s['owner'] == owner),
                             [(1900, 'prefix'), (2967, 'checkpoint')])

    def test_exhausted_reasoning_continuation_keeps_the_prompt_before_tool_retokenization(self):
        self.addCleanup(state.STOPPING.clear)
        original = list(range(3000))
        native, cache, reads = [], {}, []
        def prefill(config, model, index, tokens, held):
            if held:
                self.assertEqual(native, tokens[:held])
            reads.append((held, len(tokens)))
            native[:] = tokens
        def save(config, model, index, name):
            cache[name] = list(native)
            return {'bytes': 100}
        def restore(config, model, index, name):
            native[:] = cache[name]
            return True
        def think(config, model, index, tokens, held, count, sampling, on_tokens):
            self.assertEqual(native, tokens[:held])
            state.STOPPING.set()
            return {'tokens': [77], 'held': tokens + [77], 'done': True}
        with patch.object(lanes.BACKEND, 'prefill', side_effect=prefill), \
             patch.object(lanes.BACKEND, 'save', side_effect=save), \
             patch.object(lanes.BACKEND, 'restore', side_effect=restore), \
             patch.object(lanes.BACKEND, 'forget', side_effect=lambda config, name: cache.pop(name, None)), \
             patch.object(lanes.BACKEND, 'think', side_effect=think), \
             patch.object(lanes.snapshots, 'room', return_value=True), \
             patch.object(lanes.snapshots, 'make_room', return_value=True), patch.object(lanes, 'log'):
            self.thought('user', original)
            lanes.RUNS['user'].update(sampling={}, max=100, reader={
                'reasoning_budget': 4, 'reasoning_used': 4, 'think_end': 9900, 'think_close': [10, 9900, 10]})
            lanes.schedule(); lanes.worker(0)
            self.assertEqual([s['tokens'] for s in state.L['snapshots'].values()], [2967])
            # The native transcript splits the closed reasoning and following answer
            # into separate messages, changing only the new tail after the old prompt.
            next_prompt = original + [10, 9900, 10, 8000, 8001, 8002, 8003]
            lanes.snapshots.forget_diverged('user', WORK, next_prompt)
            state.STOPPING.clear(); lanes.HELD.clear(); native.clear(); reads.clear()
            self.thought('user', next_prompt)
            lanes.RUNS['user'].update(sampling={}, max=100, reader={})
            lanes.schedule(); lanes.worker(0)
            self.assertEqual(reads[0][0], 2967)
            self.assertLess(sum(end-start for start, end in reads), 100)

    def test_unavailable_checkpoint_cannot_make_a_reader_yield(self):
        self.thought('a', list(range(5000)))
        lanes.schedule()
        self.thought('b', [9001, 9002, 9003])
        lane = state.L['lanes'][0]
        lane['turn_since'] = state.L['thoughts']['a']['since'] = state.now() - self.slice - 1
        lanes.HELD[0] = list(range(1024))
        lanes.RUNS['a']['read_checkpoint'] = 'saved'
        base = {'model': WORK, 'tokens': 1024, 'tier': 'memory'}
        for invalid in (None, {**base, 'tier': 'moving'}, {**base, 'discard': True},
                        {**base, 'tokens': 512}, {**base, 'model': 'other'}):
            with self.subTest(checkpoint=invalid):
                state.L['snapshots'].clear()
                if invalid:
                    state.L['snapshots']['saved'] = invalid
                with patch.object(lanes.scheduler, 'draw', lambda config, thought, now: {'a': .1, 'b': .9}[thought['agent']]):
                    lanes.schedule()
                self.assertEqual(lane['holder'], 'a')
                self.assertFalse(state.L['thoughts']['a']['read_checkpoint'])

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
        with patch.object(lanes.scheduler, "draw", lambda config, thought, now: {"a": 0.1, "b": 0.9}[thought["agent"]]):
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
        with patch.object(lanes.scheduler, "draw", lambda config, thought, now: {"a": 0.9, "b": 0.1}[thought["agent"]]):
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
            return {'tokens': [7] * count, 'done': False, 'held': tokens + [7] * (count - 1)}
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
            return {'tokens': new, 'done': len(calls) == 2, 'held': tokens + new[:-1]}
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
        run.update(sampling={}, max=100, reader={}, shared=[3])
        lanes.schedule()
        saved = []

        def prefill(config, model, index, tokens, held):
            state.STOPPING.set()

        with patch.object(lanes.BACKEND, 'prefill', side_effect=prefill), \
             patch.object(lanes.snapshots, 'shared', return_value=False), \
             patch.object(lanes.snapshots, 'keep_shared', side_effect=lambda position, tokens: saved.append(list(tokens))):
            lanes.worker(0)
        self.assertEqual(saved, [[1, 2, 3]])

    def test_each_declared_shared_tier_is_saved_in_turn(self):
        """A project-wide, an all-roles and a role start: each read stops at the next unsaved one."""
        self.addCleanup(state.STOPPING.clear)
        self.thought('a', list(range(1, 11)))
        run = lanes.RUNS['a']
        run.update(sampling={}, max=100, reader={}, shared=[2, 4, 6])
        lanes.schedule()
        saved, reads = [], []

        def prefill(config, model, index, tokens, held):
            reads.append((len(tokens), held))
            if len(reads) == 3:
                state.STOPPING.set()

        with patch.object(lanes.BACKEND, 'prefill', side_effect=prefill), \
             patch.object(lanes.snapshots, 'shared', side_effect=lambda model, tokens: len(tokens) == 4), \
             patch.object(lanes.snapshots, 'keep_shared', side_effect=lambda position, tokens: saved.append(len(tokens))):
            lanes.worker(0)
        self.assertEqual(saved, [2, 6])  # 4 already exists, so it is read through, not saved again
        self.assertEqual(reads[:2], [(2, 0), (6, 2)])

    def test_the_end_of_a_thought_restarts_the_silence_clock(self):
        state.L["agents"]["a"] = {"last_activity": state.now() - 2400, "repeats": 0, "last_thought": None,
                                  "thoughts": 0}
        self.thought("a", [1, 2, 3])
        lanes.finish("a", "failed")  # e.g. its model went away after a long thought
        self.assertLess(state.now() - state.L["agents"]["a"]["last_activity"], 1)

    def test_gpu_time_counts_reading_and_generation_for_agents_and_coin(self):
        self.addCleanup(state.STOPPING.clear)
        for agent_id in ('a', 'coin'):
            for generating in (False, True):
                with self.subTest(agent=agent_id, generating=generating):
                    state.STOPPING.clear()
                    state.L['thoughts'].clear()
                    lanes.RUNS.clear()
                    lanes.HELD.clear()
                    state.L['lanes'][0].update(holder=None, turn_agent=None, held_for=None)
                    timing = state.L['coin'] if agent_id == 'coin' else state.L['agents'].setdefault(agent_id, {})
                    timing.update(gpu_seconds=5, generated=0)
                    self.thought(agent_id, [1, 2, 3])
                    lanes.RUNS[agent_id].update(sampling={}, max=100)
                    lanes.schedule()
                    if generating:
                        self.read_done(agent_id)
                    clock = [100.0]
                    def step(*args):
                        self.assertIsNotNone(timing['gpu_since'])
                        clock[0] += 3
                        state.STOPPING.set()
                        return {'tokens': [7], 'held': [1, 2, 3], 'done': False, 'generation_seconds': 2,
                                'draft_rounds': 1, 'draft_tokens': 3, 'draft_accepted_tokens': 0,
                                'sampling': {'temperature': 1},
                                'rate': 12.34 if generating else None}
                    with patch.object(lanes.time, 'monotonic', side_effect=lambda: clock[0]), \
                         patch.object(lanes.BACKEND, 'think', side_effect=step), \
                         patch.object(lanes.BACKEND, 'prefill', side_effect=step), \
                         patch.object(lanes.snapshots, 'live', return_value=False), \
                         patch.object(lanes, 'switch'):
                        lanes.worker(0)
                    self.assertEqual(timing['gpu_seconds'], 8)
                    self.assertIsNone(timing['gpu_since'])
                    self.assertEqual(state.L['thoughts'][agent_id].get('rate'), 12.3 if generating else None)
                    if generating:
                        self.assertEqual(timing['speculation'], {
                            'draft_rounds': 1, 'draft_tokens': 3, 'draft_accepted_tokens': 0,
                            'generation_tokens': 1, 'generation_seconds': 2})
                        decode = state.L['thoughts'][agent_id]['decode']
                        self.assertEqual(decode['context_tokens'], 3)
                        self.assertEqual(decode['sampling'], {'temperature': 1})
                        self.assertEqual(decode['draft_accepted_tokens'], 0)
                    else:
                        self.assertNotIn('speculation', timing)
                        self.assertNotIn('decode', state.L['thoughts'][agent_id])
                    if agent_id == 'a':
                        self.assertEqual(timing.get('generation_seconds', 0), 2 if generating else 0)

    def test_agent_activity_clock_survives_repeated_progress_events(self):
        state.L['agents']['a'] = {'doing': None}
        with patch.object(runs, 'now', return_value=100):
            runs.observed('a', 'activity', 'reading file')
        with patch.object(runs, 'now', return_value=120):
            runs.observed('a', 'activity', 'reading file')
        self.assertEqual(state.L['agents']['a']['doing_since'], 100)
        with patch.object(runs, 'now', return_value=130):
            runs.observed('a', 'activity', 'running tests')
        self.assertEqual(state.L['agents']['a']['doing_since'], 130)

    def test_a_generation_step_without_progress_cannot_replay_or_claim_the_whole_context(self):
        self.addCleanup(state.STOPPING.clear)
        self.thought('a', [1, 2, 3])
        run = lanes.RUNS['a']
        run.update(sampling={}, max=100)
        lanes.schedule()
        self.read_done('a')
        def empty(*args):
            state.STOPPING.set()
            return {'tokens': [], 'done': False}
        with patch.object(lanes.BACKEND, 'think', side_effect=empty), \
             patch.object(lanes.traceback, 'print_exc'), patch.object(lanes, 'alert'):
            lanes.worker(0)
        self.assertFalse(state.L['thoughts'])
        self.assertEqual(lanes.HELD[0], [])
        self.assertEqual(run['queue'].get_nowait(), {'end': 'failed'})

    def test_gufo_complete_state_continues_across_chunks_without_restore_or_reread(self):
        self.addCleanup(state.STOPPING.clear)
        self.thought('a', [1, 2, 3])
        state.L['agents']['a'] = {'generation_tokens': 1000, 'generation_seconds': 100}
        lanes.RUNS['a'].update(sampling={}, max=100)
        lanes.HELD[0] = [1, 2, 3]
        state.L['lanes'][0]['resident'] = 'a'
        calls = []
        def think(config, model, index, tokens, held, *args):
            self.assertEqual(held, len(tokens))
            calls.append(list(tokens))
            new = [6 + len(calls)]
            if len(calls) == 3:
                state.STOPPING.set()
            return {'tokens': new, 'held': tokens + new, 'done': False,
                    'draft_rounds': 1, 'draft_tokens': len(calls),
                    'draft_accepted_tokens': 0, 'generation_seconds': len(calls) / 2}
        with patch.dict(state.CONFIG['models'][WORK], backend='gufo'), \
             patch.object(lanes.BACKEND, 'think', side_effect=think), \
             patch.object(lanes.BACKEND, 'prefill') as prefill, \
             patch.object(lanes, 'switch') as switch:
            lanes.schedule()
            self.assertFalse(state.L['thoughts']['a']['reading'])
            lanes.worker(0)
        switch.assert_not_called()
        prefill.assert_not_called()
        self.assertEqual(calls, [[1, 2, 3], [1, 2, 3, 7], [1, 2, 3, 7, 8]])
        self.assertEqual(lanes.HELD[0], [1, 2, 3, 7, 8, 9])
        self.assertEqual(state.L['agents']['a']['speculation'], {
            'draft_rounds': 3, 'draft_tokens': 6, 'draft_accepted_tokens': 0,
            'generation_tokens': 3, 'generation_seconds': 3})
        self.assertEqual(state.L['thoughts']['a']['decode']['context_tokens'], 5)

    def test_bounded_rereading_after_cache_loss_is_progress_below_an_old_frontier(self):
        self.addCleanup(state.STOPPING.clear)
        self.thought('a', [1, 2, 3, 4, 5, 6])
        lanes.RUNS['a'].update(sampling={}, max=100)
        lanes.schedule()
        thought = state.L['thoughts']['a']
        thought.update(read=5, progress_at=state.now() - 1000)
        lanes.HELD[0] = [1, 2]
        def prefill(*args):
            state.STOPPING.set()
        with patch.object(lanes.BACKEND, 'prefill', side_effect=prefill):
            lanes.worker(0)
        self.assertEqual(thought['read'], 5)
        self.assertLess(state.now() - thought['progress_at'], 1)


if __name__ == "__main__":
    unittest.main()
