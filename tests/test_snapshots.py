import copy
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cointos import backend_llama, gateway, lanes, lifecycle, memory, snapshots, snapshot_cleanup, state

WORK = state.CONFIG["work_model"]


class Snapshots(unittest.TestCase):
    """Only a conversation that can go on keeps saved contexts, and only ones it can go on from."""

    def setUp(self):
        transfers = set(snapshots.TRANSFERS)
        self.addCleanup(lambda: (snapshots.TRANSFERS.clear(), snapshots.TRANSFERS.update(transfers)))
        snapshots.TRANSFERS.clear()
        previous = copy.deepcopy(state.L)
        self.addCleanup(lambda: (state.L.clear(), state.L.update(previous)))
        saved = dict(lanes.HELD)
        self.addCleanup(lambda: (lanes.HELD.clear(), lanes.HELD.update(saved)))
        state.L.clear()
        state.L.update(state.fresh({}))
        state.L["lanes"] = [lane for lane in state.L["lanes"] if lane["model"] == WORK][:1]
        state.L["tasks"]["t"] = {"id": "t", "status": "running"}
        self.forgotten = []
        self.backend_save = snapshots.BACKEND.save
        self.backend_delete = snapshots.BACKEND.delete_snapshot_file
        self.enterContext(mock.patch.object(snapshots.BACKEND, "save", self.save))
        self.enterContext(mock.patch.object(snapshots.BACKEND, "forget", lambda config, name: self.forgotten.append(name)))
        self.enterContext(mock.patch.object(snapshots.BACKEND, 'delete_snapshot_file', self.delete))
        self.enterContext(mock.patch.object(snapshots.BACKEND, "restore", lambda config, model, index, name: True))
        self.real_make_room = snapshots.make_room
        self.enterContext(mock.patch.object(snapshots, "make_room", lambda need: True))
        self.while_saving = lambda: None
        self.ram_released = 0
        self.enterContext(mock.patch.object(snapshots.BACKEND, 'budget', return_value=None))
        self.enterContext(mock.patch.object(memory, 'measure', side_effect=lambda: {
            'available_gb': state.CONFIG['memory']['reserve_gb'] + state.L['memory'].get('headroom_gb', 0) + self.ram_released}))

    def delete(self, config, entry):
        if entry['name'] not in self.forgotten:
            self.forgotten.append(entry['name'])
        self.ram_released = entry['bytes'] / memory.GB if entry['tier'] == 'memory' else 0
        return entry['bytes']

    def drain(self):
        snapshot_cleanup.drain('memory')
        snapshot_cleanup.drain('disk')

    def save(self, config, model, index, name):
        self.while_saving()  # a save takes seconds, outside the lock
        return {"bytes": 1}

    def test_a_state_saved_as_its_task_ends_is_not_kept(self):
        self.while_saving = lambda: state.L["tasks"]["t"].update(status="done")
        self.assertFalse(snapshots.keep(0, [1, 2, 3], "t", "suspended"))
        self.assertEqual(state.L["snapshots"], {})
        self.drain()
        self.assertEqual(len(self.forgotten), 1)

    def test_a_state_saved_as_its_task_is_forgotten_is_not_kept(self):
        self.while_saving = lambda: state.L["tasks"].pop("t")
        self.assertFalse(snapshots.keep(0, [1, 2, 3], "t", "suspended"))
        self.assertEqual(state.L["snapshots"], {})

    def test_coin_user_and_shared_starts_are_kept_without_tasks(self):
        for tokens, owner in enumerate(("coin", "user", "shared")):
            self.assertTrue(snapshots.keep(0, [tokens], owner, "checkpoint"))
        self.assertEqual(sorted(s["owner"] for s in state.L["snapshots"].values()), ["coin", "shared", "user"])

    def test_longer_shared_start_does_not_erase_tiers_other_roles_can_reuse(self):
        for tokens in ([1, 2], [1, 2, 3, 4], [1, 2, 3, 4, 5, 6]):
            snapshots.keep_shared(0, tokens)
        self.assertEqual(sorted(s["tokens"] for s in state.L["snapshots"].values()), [2, 4, 6])
        # A different role extends the shared base, but not the first role's instructions.
        restored = lanes.switch(0, [1, 2, 3, 4, 99, 100], "t")
        self.assertIsNotNone(restored)
        self.assertEqual(lanes.HELD[0], [1, 2, 3, 4])

    def test_single_conversation_checkpoint_supersedes_old_states_but_suspension_keeps_its_checkpoint(self):
        snapshots.keep(0, [1, 2], "t", "checkpoint")
        snapshots.keep(0, [1, 2, 3], "t", "suspended")
        self.assertEqual(sorted(s["tokens"] for s in state.L["snapshots"].values()), [2, 3])
        snapshots.keep(0, [1, 2, 3, 4], "t", "checkpoint")
        self.assertEqual([s["tokens"] for s in state.L["snapshots"].values()], [4])

    def test_existing_suspended_state_becomes_a_checkpoint_when_committed(self):
        snapshots.keep(0, [1, 2], "t", "suspended")
        snapshots.keep(0, [1, 2], "t", "checkpoint")
        snapshots.keep(0, [1, 2, 3], "t", "suspended")
        self.assertEqual(sorted((s["tokens"], s["kind"]) for s in state.L["snapshots"].values()),
                         [(2, "checkpoint"), (3, "suspended")])

    def pressure_caches(self):
        self.drain()
        state.L['snapshots'].clear()
        state.L['memory'] = {'headroom_gb': 20}
        for n in range(5):
            state.L['snapshots'][str(n)] = {
                'owner': 't' if n == 4 else 'user', 'model': WORK, 'tokens': 2,
                'digest': snapshots.digest([1, 2] if n == 4 else [9, n]),
                'kind': 'checkpoint', 'bytes': 7.5 * memory.GB,
                'last_run': n, 'tier': 'memory'}

    def test_replacement_reclaims_its_obsolete_cache_before_spilling_other_work(self):
        for limit, headroom in ((40, 20), (50, 1)):
            with self.subTest(limit=limit, headroom=headroom):
                self.pressure_caches()
                self.forgotten.clear()
                state.L['memory']['headroom_gb'] = headroom
                def saved(*args):
                    self.assertNotIn('4', state.L['snapshots'])
                    self.assertEqual(set(state.L['snapshots']), {'0', '1', '2', '3'})
                    self.assertAlmostEqual(state.L['memory']['headroom_gb'], headroom - .1)
                    return {'bytes': 7.6 * memory.GB}
                with mock.patch.dict(state.CONFIG['memory'], snapshots_gb=limit), \
                        mock.patch.object(memory, 'snapshot_gb', return_value=7.6), \
                        mock.patch.object(snapshots, 'make_room', self.real_make_room), \
                        mock.patch.object(snapshots, 'evict', side_effect=AssertionError('unrelated eviction')), \
                        mock.patch.object(snapshots.BACKEND, 'save', side_effect=saved):
                    self.assertTrue(snapshots.keep(0, [1, 2, 3], 't', 'checkpoint'))
                self.assertEqual(self.forgotten, ['4'])
                self.assertAlmostEqual(sum(s['bytes'] for s in state.L['snapshots'].values()) / memory.GB, 37.6)
                self.assertFalse(snapshots.RESERVED)

    def test_replacement_failure_preserves_old_cache_when_both_fit(self):
        for limit in (40, 50):
            with self.subTest(limit=limit):
                self.pressure_caches()
                self.forgotten.clear()
                with mock.patch.dict(state.CONFIG['memory'], snapshots_gb=limit), \
                        mock.patch.object(memory, 'snapshot_gb', return_value=7.6), \
                        mock.patch.object(snapshots, 'make_room', self.real_make_room), \
                        mock.patch.object(snapshots, 'evict', side_effect=AssertionError('unrelated eviction')), \
                        mock.patch.object(snapshots.BACKEND, 'save', side_effect=RuntimeError('save failed')):
                    with self.assertRaisesRegex(RuntimeError, 'save failed'):
                        snapshots.keep(0, [1, 2, 3], 't', 'checkpoint')
                self.assertEqual('4' in state.L['snapshots'], limit == 50)
                self.assertTrue({'0', '1', '2', '3'} <= state.L['snapshots'].keys())
                self.assertFalse(snapshots.RESERVED)
                self.assertEqual(state.L['tasks']['t']['status'], 'running')

    def test_replacement_preserves_semantic_shared_divergent_and_other_model_caches(self):
        self.pressure_caches()
        rows = state.L['snapshots']
        rows['0'].update(owner='t', kind='prefix', digest=snapshots.digest([1, 2]))
        rows['1'].update(owner='t')  # divergent token prefix
        rows['2'].update(owner='shared', digest=snapshots.digest([1, 2]))
        rows['3'].update(owner='t', model='other', digest=snapshots.digest([1, 2]))
        with mock.patch.dict(state.CONFIG['memory'], snapshots_gb=40), \
                mock.patch.object(memory, 'snapshot_gb', return_value=7.6), \
                mock.patch.object(snapshots, 'make_room', self.real_make_room), \
                mock.patch.object(snapshots, 'evict', side_effect=AssertionError('protected eviction')), \
                mock.patch.object(snapshots.BACKEND, 'save', return_value={'bytes': 7.6 * memory.GB}):
            self.assertTrue(snapshots.keep(0, [1, 2, 3], 't', 'checkpoint'))
        self.assertEqual(self.forgotten, ['4'])
        self.assertTrue({'0', '1', '2', '3'} <= rows.keys())

    def test_replacement_does_not_credit_or_delete_an_inflight_transfer(self):
        state.L['snapshots'] = {'moving': {'owner': 't', 'tier': 'moving',
                                         'bytes': 8 * memory.GB, 'last_run': 0}}
        state.L['memory'] = {'headroom_gb': 20}
        with mock.patch.dict(state.CONFIG['memory'], snapshots_gb=8):
            self.assertFalse(snapshots.room(1, replacing=['moving']))
        self.assertEqual(self.forgotten, [])
        self.assertEqual(state.L['memory']['headroom_gb'], 20)

    def test_replacement_keeps_fallback_when_reclaim_cannot_meet_host_headroom(self):
        self.pressure_caches()
        state.L['memory']['headroom_gb'] = -1
        with mock.patch.dict(state.CONFIG['memory'], snapshots_gb=40), \
                mock.patch.object(memory, 'snapshot_gb', return_value=7.6), \
                mock.patch.object(snapshots.threading, 'Thread'), \
                mock.patch.object(snapshots.BACKEND, 'save') as saved:
            self.assertFalse(snapshots.keep(0, [1, 2, 3], 't', 'checkpoint'))
        self.assertIn('4', state.L['snapshots'])
        self.assertEqual(self.forgotten, [])
        saved.assert_not_called()

    def test_replacement_keeps_fallback_when_pending_bytes_prevent_admission(self):
        self.pressure_caches()
        rows = state.L['snapshots']
        rows['0'].update(tier='moving', bytes=33 * memory.GB)
        state.L['snapshots'] = {'moving': rows['0'], '4': rows['4']}
        with mock.patch.dict(state.CONFIG['memory'], snapshots_gb=40), \
                mock.patch.object(memory, 'snapshot_gb', return_value=7.6), \
                mock.patch.object(snapshots.threading, 'Thread'), \
                mock.patch.object(snapshots.BACKEND, 'save') as saved:
            self.assertFalse(snapshots.keep(0, [1, 2, 3], 't', 'checkpoint'))
        self.assertIn('4', state.L['snapshots'])
        self.assertEqual(self.forgotten, [])
        self.assertEqual(state.L['memory']['headroom_gb'], 20)
        saved.assert_not_called()

    def test_history_prefix_survives_tail_checkpoints_and_advances_independently(self):
        owner = 'coin/history-fixture'
        snapshots.keep(0, [1, 2], owner, 'prefix')
        snapshots.keep(0, [1, 2, 3, 4], owner, 'checkpoint')
        snapshots.keep(0, [1, 2, 3, 4, 5], owner, 'suspended')
        snapshots.keep(0, [1, 2, 3, 4, 5, 6], owner, 'checkpoint')
        self.assertEqual(sorted((s['tokens'], s['kind']) for s in state.L['snapshots'].values()),
                         [(2, 'prefix'), (6, 'checkpoint')])
        snapshots.keep(0, [1, 2, 3], owner, 'prefix')
        self.assertEqual(sorted((s['tokens'], s['kind']) for s in state.L['snapshots'].values()),
                         [(3, 'prefix'), (6, 'checkpoint')])
        snapshots.forget_diverged(owner, WORK, [1, 2, 3, 99, 100])
        self.assertEqual([s['kind'] for s in state.L['snapshots'].values()], ['prefix'])

    def test_identical_checkpoint_promotes_to_prefix_without_saving_again(self):
        snapshots.keep(0, [1, 2], 'coin/a', 'checkpoint')
        with mock.patch.object(snapshots.BACKEND, 'save') as save:
            self.assertTrue(snapshots.retain_prefix(WORK, [1, 2], 'coin/a'))
            snapshots.keep(0, [1, 2], 'coin/a', 'checkpoint')
            save.assert_not_called()
        self.assertEqual([s['kind'] for s in state.L['snapshots'].values()], ['prefix'])

    def test_shared_start_reuses_existing_bytes_but_survives_original_task_retirement(self):
        snapshots.keep(0, [1, 2], "t", "checkpoint")
        with mock.patch.object(snapshots.BACKEND, "save") as save:
            snapshots.keep_shared(0, [1, 2])
            save.assert_not_called()
        state.L["tasks"]["t"]["status"] = "done"
        snapshots.forget_orphans()
        self.assertEqual([s["owner"] for s in state.L["snapshots"].values()], ["shared"])

    def test_identical_tokens_of_different_models_are_not_the_same_state(self):
        snapshots.keep(0, [1, 2], "shared", "checkpoint")
        state.L["lanes"][0]["model"] = "other-model"
        snapshots.keep(0, [1, 2], "shared", "checkpoint")
        self.assertEqual({s["model"] for s in state.L["snapshots"].values()}, {WORK, "other-model"})

    def test_coin_new_history_forgets_diverged_states_but_keeps_matching_start(self):
        snapshots.keep(0, [1, 2, 3], "coin/a", "checkpoint")
        snapshots.keep(0, [1, 2, 30], "coin/a", "checkpoint")
        snapshots.keep(0, [1, 2, 50], "coin/b", "checkpoint")
        with mock.patch.dict(lanes.RUNS, clear=True), mock.patch.object(lanes, "schedule"):
            lanes.begin("coin", "coin", "coin/a", WORK, {"tokens": [1, 2, 30, 40], "reader": {}}, {}, 100)
        self.assertEqual(len(state.L["snapshots"]), 2)
        self.assertEqual({s["owner"]: s["digest"] for s in state.L["snapshots"].values()},
                         {"coin/a": snapshots.digest([1, 2, 30]), "coin/b": snapshots.digest([1, 2, 50])})

    def test_independent_user_requests_do_not_discard_each_others_saved_starts(self):
        snapshots.keep(0, [1, 2, 3], "user", "checkpoint")
        snapshots.keep(0, [1, 2, 30], "user", "checkpoint")
        with mock.patch.dict(lanes.RUNS, clear=True), mock.patch.object(lanes, "schedule"):
            lanes.begin("external", "user", "user", WORK, {"tokens": [1, 2, 30, 40], "reader": {}}, {}, 100)
        self.assertEqual(len(state.L["snapshots"]), 2)

    def test_coin_cache_scope_changes_by_user_without_changing_priority(self):
        with mock.patch.object(gateway.keys, "owner", return_value=("coin", "coin")):
            first = gateway.identity("key", "opaque-a")
            self.assertEqual(first, gateway.identity("key", "opaque-a"))
            self.assertNotEqual(first[2], gateway.identity("key", "opaque-b")[2])
        self.assertEqual(first[:2], ("coin", "coin"))
        self.assertTrue(snapshots.live(first[2]))
        self.assertNotIn("opaque-a", first[2])

    def test_request_user_metadata_cannot_change_a_managed_tasks_identity(self):
        state.L["agents"]["run"] = {"task": "t"}
        with mock.patch.object(gateway.keys, "owner", return_value=("run", "background")):
            self.assertEqual(gateway.identity("key", "coin/pretend"), ("run", "background", "t"))

    def test_conversation_liveness_is_task_reachability_not_task_outcome(self):
        self.assertTrue(snapshots.live("t"))
        state.L["tasks"]["t"]["status"] = "review"
        self.assertTrue(snapshots.live("t"), "reviewed work can be returned to this conversation")
        state.L["tasks"]["t"]["status"] = "done"
        self.assertFalse(snapshots.live("t"))
        state.L["agents"]["run-1"] = {"task": "t"}
        self.assertTrue(snapshots.live("t"), "a terminal task's surviving run can still issue a request")

    def test_orphaned_snapshots_are_forgotten_but_review_and_untasked_ones_kept(self):
        state.L["tasks"]["r"] = {"id": "r", "status": "review"}
        for name, owner in (("a", "gone"), ("b", "r"), ("c", "shared"), ("d", "coin"), ("e", "t")):
            state.L["snapshots"][name] = {"owner": owner}
        snapshots.forget_orphans()
        self.assertEqual(sorted(state.L["snapshots"]), ["b", "c", "d", "e"])
        self.drain()
        self.assertEqual(self.forgotten, ["a"])

    def test_reconciliation_forgets_terminal_owners_but_preserves_surviving_runs(self):
        for name, status in (("accepted", "done"), ("failed", "failed"), ("finishing", "done"), ("review", "review")):
            state.L["tasks"][name] = {"id": name, "kind": "item", "status": status, "branch": None, "record": None}
            state.L["snapshots"][name] = {"owner": name, "tier": "disk"}
        state.L["agents"]["finishing-run"] = {"task": "finishing"}
        state.L["tasks"]["t"].update(kind="item", branch=None, record=None)
        lifecycle.reconcile()
        self.assertEqual(set(state.L["snapshots"]), {"finishing", "review"})
        self.drain()
        self.assertEqual(set(self.forgotten), {"accepted", "failed"})

    def test_owner_retirement_during_spill_defers_cleanup_until_copy_finishes(self):
        state.L["snapshots"]["moving"] = {"owner": "t", "tier": "moving", "bytes": 123}
        def transfer(config, name):
            state.L["tasks"]["t"]["status"] = "done"
            snapshots.forget_orphans()
            self.assertEqual(self.forgotten, [])
            self.assertEqual(state.L["snapshots"][name]["bytes"], 123)
            self.assertTrue(state.L["snapshots"][name]["discard"])
        with mock.patch.object(snapshots.BACKEND, "spill", side_effect=transfer):
            snapshots.spill("moving")
        self.assertEqual(state.L["snapshots"], {})
        self.drain()
        self.assertEqual(self.forgotten, ["moving"])

    def test_unspill_does_not_restore_a_retired_owner_or_a_discarded_live_prefix(self):
        for retire in (True, False):
            with self.subTest(retire=retire):
                state.L["tasks"]["t"]["status"] = "running"
                state.L["snapshots"]["disk"] = {"owner": "t", "tier": "disk", "bytes": 123}
                self.forgotten.clear()
                def transfer(config, name):
                    if retire:
                        state.L["tasks"]["t"]["status"] = "done"
                    snapshots.forget_owner("t")
                    self.assertEqual(self.forgotten, [])
                    self.assertEqual(state.L["snapshots"][name]["tier"], "moving")
                with mock.patch.object(snapshots.BACKEND, "copy_back", side_effect=transfer):
                    self.assertFalse(snapshots.bring_back("disk"))
                self.assertEqual(state.L["snapshots"], {})
                self.drain()
                self.assertEqual(self.forgotten, ["disk"])

    def test_unspill_error_is_a_cache_miss_and_cleans_the_failed_transfer(self):
        state.L["snapshots"]["disk"] = {"owner": "t", "tier": "disk", "bytes": 123}
        with mock.patch.object(snapshots.BACKEND, "copy_back", side_effect=OSError("missing cache file")):
            self.assertFalse(snapshots.bring_back("disk"))
        self.assertEqual(state.L["snapshots"], {})
        self.drain()
        self.assertEqual(self.forgotten, ["disk"])

    def test_startup_discards_unrecoverable_transfers_but_keeps_committed_tiers(self):
        for name, tier in (("copy", "moving"), ("ram", "memory"), ("disk", "disk")):
            state.L["snapshots"][name] = {"owner": "t", "tier": tier}
        snapshots.recover_transfers()
        self.assertEqual(set(state.L["snapshots"]), {"ram", "disk"})
        self.drain()
        self.assertEqual(self.forgotten, ["copy"])

    def test_shutdown_reserves_each_spill_before_admitting_the_next(self):
        for disk_gb, pending_gb, expected in ((6, 0, ["a", "b"]),
                                               (9, 0, ["a", "b"]),
                                               (6, 4, ["a"])):
            with self.subTest(disk_gb=disk_gb, pending_gb=pending_gb):
                state.L["snapshots"].clear()
                self.forgotten.clear()
                spilled = []
                for name, tier, size in (("disk", "disk", disk_gb),
                                         ("pending", "moving", pending_gb),
                                         ("a", "memory", 4), ("b", "memory", 4)):
                    if size:
                        state.L["snapshots"][name] = {
                            "owner": "shared", "tier": tier,
                            "bytes": size * memory.GB, "last_run": 0}

                def transfer(config, name):
                    occupied = sum(s["bytes"] for s in state.L["snapshots"].values()
                                   if s["tier"] in ("disk", "moving"))
                    self.assertLessEqual(occupied, 10 * memory.GB)
                    spilled.append(name)

                with mock.patch.dict(state.CONFIG["memory"], disk_snapshots_gb=10), \
                        mock.patch.object(snapshots.BACKEND, "spill", side_effect=transfer):
                    snapshots.persist()
                self.assertEqual(spilled, expected)
                self.assertEqual(self.forgotten, ["disk"])
                self.assertEqual(state.L["snapshots"]["b"]["tier"],
                                 "disk" if "b" in expected else "memory")

    def test_save_process_death_does_not_leave_unaccounted_cache_files(self):
        with tempfile.TemporaryDirectory() as folder:
            ram, disk = Path(folder) / "ram", Path(folder) / "disk"
            ram.mkdir(); disk.mkdir()
            with mock.patch.dict(state.CONFIG, snapshots=str(ram), disk_snapshots=str(disk)), \
                    mock.patch.dict(state.CONFIG['models'][WORK], backend='llama'), \
                    mock.patch.object(snapshots.BACKEND, 'delete_snapshot_file', self.backend_delete):
                pid = os.fork()
                if pid == 0:
                    def interrupted(model, path, body, timeout):
                        (ram / body["filename"]).write_bytes(b"x" * 1048576)
                        os._exit(137)  # before save returns or the ledger can publish it
                    try:
                        with mock.patch.object(snapshots.BACKEND, "save", self.backend_save), \
                                mock.patch.object(backend_llama, "_server", side_effect=interrupted):
                            snapshots.keep(0, [1, 2, 3], "user", "checkpoint")
                    finally:
                        os._exit(1)  # a failed fixture must never continue the parent suite
                _, status = os.waitpid(pid, 0)
                self.assertEqual(os.waitstatus_to_exitcode(status), 137)
                self.assertEqual(state.L["snapshots"], {})
                orphan = next(ram.iterdir())
                (disk / orphan.name).write_bytes(b"partial copy")
                snapshots.recover_transfers()
                snapshots.forget_orphans()
                state.L["snapshots"]["tracked"] = {"owner": "user", "tier": "memory"}
                state.L["snapshots"]["on-disk"] = {"owner": "user", "tier": "disk"}
                state.L["snapshots"]["moving"] = {"owner": "user", "tier": "moving"}
                for directory in (ram, disk):
                    (directory / "tracked.bin").write_bytes(b"known")
                    (directory / "on-disk.bin").write_bytes(b"known")
                    (directory / "moving.bin").write_bytes(b"transferring")
                    (directory / "saving.bin").write_bytes(b"in flight")
                    (directory / "note.txt").write_text("not a snapshot")
                with mock.patch.dict(snapshots.RESERVED, {"saving": 1}, clear=True):
                    snapshots.forget_untracked()
                    self.drain()
                self.assertEqual({p.name for p in ram.iterdir()},
                                 {"tracked.bin", "saving.bin", "moving.bin", "note.txt"})
                self.assertEqual({p.name for p in disk.iterdir()},
                                 {"on-disk.bin", "moving.bin", "note.txt"})

    def test_file_reconciliation_preserves_a_real_save_before_ledger_publication(self):
        with tempfile.TemporaryDirectory() as folder:
            ram, disk = Path(folder) / "ram", Path(folder) / "disk"
            ram.mkdir(); disk.mkdir()
            with mock.patch.dict(state.CONFIG, snapshots=str(ram), disk_snapshots=str(disk)), \
                    mock.patch.dict(state.CONFIG['models'][WORK], backend='llama'):
                def saved(model, path, body, timeout):
                    file = ram / body["filename"]
                    file.write_bytes(b"saved")
                    self.assertEqual(state.L["snapshots"], {})
                    with state.LOCK:
                        snapshots.forget_untracked()
                    self.assertTrue(file.exists(), "the save reservation owns the unpublished file")
                    return {"n_saved": 3}
                with mock.patch.object(snapshots.BACKEND, "save", self.backend_save), \
                        mock.patch.object(backend_llama, "_server", side_effect=saved):
                    self.assertTrue(snapshots.keep(0, [1, 2, 3], "user", "checkpoint"))
                self.assertEqual(len(state.L["snapshots"]), 1)
                snapshots.forget_untracked()
                self.assertEqual(len(list(ram.iterdir())), 1)

    def test_file_cleanup_error_is_observable_without_repeated_notifications(self):
        with mock.patch.object(snapshots.BACKEND, "snapshot_files",
                               side_effect=PermissionError("cache permission")) as cleanup:
            snapshots.forget_untracked()
            snapshots.forget_untracked()
            self.assertEqual(state.L["snapshot_cleanup_error"], "cache permission")
            self.assertEqual(sum(e["event"] == "snapshot file cleanup failed"
                                 for e in state.L["history"]), 1)
            self.assertEqual(state.L["alerts"], [])
            cleanup.side_effect = None
            cleanup.return_value = []
            snapshots.forget_untracked()
            self.assertNotIn("snapshot_cleanup_error", state.L)

    def test_a_task_does_not_save_the_state_its_next_thought_has_left_behind(self):
        # The lane holds the end of t's last thought, which the conversation, as rendered
        # again for its next thought, does not go on from.
        state.L["lanes"][0]["resident"] = "t"
        lanes.HELD[0] = [1, 2, 3, 40, 41]
        lanes.switch(0, [1, 2, 3, 50, 51, 52], "t")
        self.assertEqual(state.L["snapshots"], {})

    def test_complete_snapshot_is_selected_only_when_backend_can_decode_from_it(self):
        for backend, expected in (('gufo', [1, 2, 3, 4]), ('llama', [1, 2, 3])):
            with self.subTest(backend=backend), mock.patch.dict(state.CONFIG['models'][WORK], backend=backend):
                state.L['snapshots'].clear()
                lanes.HELD.clear()
                state.L['lanes'][0]['resident'] = None
                snapshots.keep(0, [1, 2, 3], 't', 'checkpoint')
                snapshots.keep(0, [1, 2, 3, 4], 't', 'suspended')
                restored = lanes.switch(0, [1, 2, 3, 4], 't')
                self.assertIsNotNone(restored)
                self.assertEqual(lanes.HELD[0], expected)

    def test_coin_does_not_resave_a_diverged_state_at_the_next_switch(self):
        state.L["lanes"][0]["resident"] = "coin/a"
        lanes.HELD[0] = [1, 2, 3, 40, 41]
        lanes.switch(0, [1, 2, 3, 50, 51, 52], "coin/a")
        self.assertEqual(state.L["snapshots"], {})

    def test_switching_coin_users_keeps_the_previous_users_state(self):
        state.L["lanes"][0]["resident"] = "coin/a"
        lanes.HELD[0] = [1, 2, 3, 40, 41]
        lanes.switch(0, [1, 2, 3, 50, 51, 52], "coin/b")
        self.assertEqual([s["owner"] for s in state.L["snapshots"].values()], ["coin/a"])

    def test_another_conversation_is_saved_when_switched_out(self):
        state.L["tasks"]["u"] = {"id": "u", "status": "running"}
        state.L["lanes"][0]["resident"] = "u"
        lanes.HELD[0] = [7, 8, 9]
        lanes.switch(0, [1, 2, 3], "t")
        self.assertEqual([s["owner"] for s in state.L["snapshots"].values()], ["u"])

    def test_switch_timings_separate_save_transfer_and_native_restore(self):
        for ready, valid in ((True, True), (True, False), (False, False)):
            with self.subTest(ready=ready, valid=valid):
                state.L['snapshots'].clear()
                snapshots.keep(0, [1, 2, 3], 't', 'checkpoint')
                name, cached = next(iter(state.L['snapshots'].items()))
                cached['tier'] = 'disk'
                state.L['lanes'][0]['resident'] = 'user'
                lanes.HELD[0] = [7, 8, 9]
                clock = [100.0]
                def save(*args):
                    clock[0] += 3
                    return False  # declined saves still take time
                def bring_back(*args):
                    clock[0] += 5
                    if ready:
                        cached['tier'] = 'memory'
                    return ready
                def restore(*args):
                    clock[0] += 7
                    return valid
                with mock.patch.object(lanes.time, 'monotonic', side_effect=lambda: clock[0]), \
                     mock.patch.object(snapshots, 'keep', side_effect=save), \
                     mock.patch.object(snapshots, 'bring_back', side_effect=bring_back), \
                     mock.patch.object(lanes.BACKEND, 'restore', side_effect=restore) as native:
                    restored = lanes.switch(0, [1, 2, 3, 4], 't')
                event = state.L['history'][-1]
                self.assertEqual(event['event'], 'switch')
                self.assertEqual(event['restore_tier'], 'disk')
                self.assertEqual(event['save_seconds'], 3)
                self.assertEqual(event['transfer_seconds'], 5)
                self.assertEqual(event['restore_seconds'], 7 if ready else 0)
                self.assertEqual(event['seconds'], 15 if ready else 8)
                self.assertEqual(native.call_count, int(ready))
                self.assertEqual(restored, name if ready and valid else None)
                self.assertEqual(event['broken_snapshot'], name if ready and not valid else None)

    def test_switch_uses_a_shorter_ram_prefix_when_the_disk_prefix_cannot_fit(self):
        snapshots.keep(0, [1, 2], 't', 'checkpoint')
        snapshots.keep(0, [1, 2, 3, 4], 't', 'suspended')
        short, long = sorted(state.L['snapshots'], key=lambda n: state.L['snapshots'][n]['tokens'])
        state.L['snapshots'][short]['bytes'] = 2 * memory.GB
        state.L['snapshots'][long].update(tier='disk', bytes=6 * memory.GB)
        state.L['memory']['headroom_gb'] = 0
        # Even deleting the two-GB fallback cannot make six GB of headroom.
        # The genuine admission path must refuse without destroying it.
        with mock.patch.object(snapshots, 'make_room', self.real_make_room), \
             mock.patch.object(lanes.BACKEND, 'unspill') as unspill, \
             mock.patch.object(lanes.BACKEND, 'restore', return_value=True) as restore:
            restored = lanes.switch(0, [1, 2, 3, 4, 5], 't')
        self.assertEqual(restored, short)
        self.assertEqual(lanes.HELD[0], [1, 2])
        restore.assert_called_once_with(state.CONFIG, WORK, 0, short)
        unspill.assert_not_called()
        self.assertEqual(state.L['snapshots'][long]['tier'], 'disk')
        self.assertEqual(state.L['history'][-1]['restore_tier'], 'memory')

    def test_switch_falls_back_after_a_corrupt_longer_cache(self):
        snapshots.keep(0, [1, 2], 't', 'checkpoint')
        snapshots.keep(0, [1, 2, 3, 4], 't', 'suspended')
        short, long = sorted(state.L['snapshots'], key=lambda n: state.L['snapshots'][n]['tokens'])
        with mock.patch.object(lanes.BACKEND, 'restore', side_effect=[False, True]) as restore:
            restored = lanes.switch(0, [1, 2, 3, 4, 5], 't')
        self.assertEqual(restored, short)
        self.assertEqual(lanes.HELD[0], [1, 2])
        self.assertEqual([call.args[-1] for call in restore.call_args_list], [long, short])
        self.assertNotIn(long, state.L['snapshots'])
        event = state.L['history'][-1]
        self.assertEqual((event['restored'], event['broken_snapshot']), (2, long))


if __name__ == "__main__":
    unittest.main()
