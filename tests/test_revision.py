"""Holding and revising queued work: an owner can stop an item from starting while deciding, and
change what it asks for at any point before acceptance."""
from pathlib import Path
import copy
import unittest

from cointos import frontier, api, lifecycle, prompts, queues, spawner, state, tasks
from tests import support

SUMMARY = "\nSummary: Explains this revised task in a few plain words."


class Revision(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self)
        support.quiet(self)
        self.project = support.project(self, support.repository(self))
        state.L["cadence"]["steward:system"] = state.now()  # keep the periodic steward out of the way
        self.manager = support.running(support.queued(self.project, "decide", "Decide the interface", kind="command"),
                                       "manager-1")

    def as_manager(self, action, **body):
        if action == "revise" and body.get("brief", "").strip():
            body["brief"] += SUMMARY  # a manager's worker brief explains itself to the dashboard
        return api.dispatch(action, {**body, "caller": support.caller(self.manager, "manager-1")})

    def worker(self, name="impl", brief="Implement it", start=True):
        worker = support.queued(self.project, name, brief)
        if start:
            support.running(worker, "worker-1")
        return worker

    def test_agent_repair_cannot_discard_accepted_test_dependencies(self):
        queues.add(self.project, "queued", "contract", "Test A\nRelies on: a", "test-contract")
        queues.finish(state.L['queue']['p:contract'], commit='accepted-tests', via='tests')
        worker = self.worker(brief="Depends on: contract\nImplement A")
        state.L['queue']['p:impl']['held_by'] = 'user'
        before = copy.deepcopy(state.L)
        with self.assertRaisesRegex(ValueError, "discard accepted test packets: contract"):
            self.as_manager('revise', item='p:impl', brief='Depends on: none\nBuild repaired; resume A',
                            reason='repair linker setup', dependencies=[])
        self.assertEqual(state.L, before, 'refusal preserves version, hold, run and artifacts')
        self.as_manager('revise', item='p:impl', brief='Build repaired; resume A',
                        reason='repair linker setup', dependencies=['contract'])
        self.assertEqual(state.L['queue']['p:impl']['depends'], ['contract'])
        self.assertEqual(state.L['queue']['p:impl']['held_by'], 'user')
        self.assertEqual(worker['status'], 'waiting')

    def test_user_can_explicitly_withdraw_test_dependency(self):
        queues.add(self.project, "queued", "contract", "Test A\nRelies on: a", "test-contract")
        queues.finish(state.L['queue']['p:contract'], commit='accepted-tests', via='tests')
        self.worker(brief="Depends on: contract\nImplement A", start=False)
        api.dispatch('revise', {'item': 'p:impl', 'brief': 'Different user-approved contract',
                               'dependencies': [], 'reason': 'withdraw old requirement'})
        self.assertEqual(state.L['queue']['p:impl']['depends'], [])

    # ------------------------------------------------ cancelling

    def test_cancelling_stops_the_run_and_drops_the_item_and_its_integration(self):
        worker = self.worker()
        integration = tasks.create("integrate", self.project, "integrate-impl", worker["brief"], [2], worker=worker["id"])
        api.dispatch("cancel", {"items": ["p:impl"], "reason": "duplicate of other work"})
        self.assertNotIn("p:impl", state.L["queue"])
        self.assertNotIn("worker-1", state.L["agents"])
        self.assertEqual((worker["status"], worker["cancelled"]), ("failed", "duplicate of other work"))
        self.assertEqual(integration["status"], "failed")
        self.assertIsNone(spawner.next_task(), "nothing of it is scheduled again")

    def test_cancelling_refuses_while_live_work_depends_on_it(self):
        queues.add(self.project, "queued", "base", "Base")
        queues.add(self.project, "queued", "top", "Depends on: base\nTop")
        with self.assertRaisesRegex(ValueError, "p:top still depend"):
            api.dispatch("cancel", {"items": ["p:base"], "reason": "r"})
        api.dispatch("cancel", {"items": ["p:base", "p:top"], "reason": "both redundant"})
        self.assertFalse({"p:base", "p:top"} & set(state.L["queue"]))

    def test_only_the_owning_manager_or_user_cancels_and_never_accepted_work(self):
        queues.add(self.project, "queued", "impl", "Implement it")
        with self.assertRaisesRegex(ValueError, "why"):
            self.as_manager("cancel", items=["p:impl"], reason=" ")
        self.as_manager("cancel", items=["p:impl"], reason="duplicate")
        queues.add(self.project, "queued", "landed", "Landed")
        queues.finish(state.L["queue"]["p:landed"])
        with self.assertRaisesRegex(ValueError, "already accepted"):
            api.dispatch("cancel", {"items": ["p:landed"], "reason": "r"})

    def test_a_fresh_run_is_told_what_its_assignment_already_queued(self):
        self.as_manager("queue", project="p", kind="queued", name="first-try",
                        brief="Do it.\nSummary: Removes the old rollback checks from the tests.")
        text = prompts.launch_text(self.manager, self.project)
        self.assertIn("p:first-try (queued): Removes the old rollback checks from the tests.", text)
        self.assertIn("Do not queue this work again", text)

    # ------------------------------------------------ holding

    def test_the_user_releases_any_hold_and_a_manager_only_its_own(self):
        queues.add(self.project, "queued", "impl", "Implement it")
        queues.add(self.project, "queued", "managed", "Manager-owned item")
        state.L["queue"]["p:impl"]["held_by"] = "user"
        self.as_manager("hold", item="p:managed")
        api.dispatch("unhold", {"item": "p:impl"})
        api.dispatch("unhold", {"item": "p:managed"})
        self.assertTrue(all(r["held_by"] is None for r in state.L["queue"].values()))

    def test_a_held_item_does_not_start_until_released(self):
        queues.add(self.project, "queued", "impl", "Implement it")
        self.as_manager("hold", item="p:impl")
        self.assertIsNone(spawner.next_task())
        self.as_manager("unhold", item="p:impl")
        self.assertEqual(spawner.next_task()["id"], "p:impl")

    def test_holding_a_running_item_stops_it_uncharged_and_keeps_it_waiting(self):
        worker = self.worker()
        self.as_manager("hold", item="p:impl")
        self.assertEqual((worker["status"], worker["runs"]), ("waiting", 0))
        self.assertNotIn("worker-1", state.L["agents"])
        self.assertIsNone(spawner.next_task(), "a held waiting task is not resumed")

    def test_a_held_reviewed_item_is_not_integrated(self):
        worker = support.reviewed(self.worker(start=False), "worker-1")
        self.as_manager("hold", item="p:impl")
        self.assertIsNone(spawner.next_task())
        self.assertEqual(worker["status"], "review")

    def test_a_stalled_integration_does_not_block_the_projects_other_reviewed_items(self):
        first = support.reviewed(self.worker("first", start=False), "worker-1")
        stalled = spawner.next_task()
        self.assertEqual(stalled["worker"], first["id"])
        stalled["admission_hold"] = "killed by the user"
        first["status"] = "running"  # revised: back at work on its brief
        second = support.reviewed(self.worker("second", start=False), "worker-2")
        task = spawner.next_task()
        self.assertEqual((task["kind"], task["worker"]), ("integrate", second["id"]))
        first["status"] = "review"
        spawner.next_task()
        self.assertEqual(sum(t["kind"] == "integrate" and t["worker"] == first["id"] for t in state.L["tasks"].values()),
                         1, "a held integration's worker gets no second integration")

    def test_holds_end_when_their_holder_settles(self):
        queues.add(self.project, "queued", "impl", "Implement it")
        self.as_manager("hold", item="p:impl")
        lifecycle.submit(self.manager["id"], "manager-1", "blocked", "Needs the user's call")
        self.assertIsNone(state.L["queue"]["p:impl"]["held_by"])

    def test_one_holder_at_a_time_and_user_can_release_any(self):
        queues.add(self.project, "queued", "impl", "Implement it")
        api.dispatch("hold", {"item": "p:impl"})
        with self.assertRaisesRegex(ValueError, "already held by user"):
            self.as_manager("hold", item="p:impl")
        self.as_manager("revise", item="p:impl", brief="Implement it differently", reason="interface changed")
        self.assertEqual(state.L["queue"]["p:impl"]["held_by"], "user")
        self.assertFalse(spawner.next_task(), "a manager revision cannot release user-held work")
        api.dispatch("revise", {"item": "p:impl", "brief": "A further correction", "reason": "clarify"})
        self.assertEqual(state.L["queue"]["p:impl"]["held_by"], "user")
        with self.assertRaisesRegex(ValueError, "held by user"):
            self.as_manager("unhold", item="p:impl")
        api.dispatch("unhold", {"item": "p:impl"})
        self.assertEqual(spawner.next_task()["id"], "p:impl")

    # ------------------------------------------------ revising

    def test_revision_preserves_another_tasks_hold(self):
        queues.add(self.project, "queued", "impl", "Implement it")
        record = state.L["queue"]["p:impl"]
        record["held_by"] = "p:other-manager"
        self.as_manager("revise", item="p:impl", brief="Corrected implementation", reason="clarify")
        self.assertEqual(record["held_by"], "p:other-manager")

    def test_origin_revision_stops_stale_recovery_and_preserves_its_work(self):
        worker = self.worker(start=False)
        lifecycle.fail(worker, 'Original assignment blocked')
        manager, _ = tasks.request_repair(worker)
        support.running(manager, 'repair-run')
        artifact = Path(manager['worktree']) / 'preserved-investigation.txt'
        artifact.write_text('unfinished investigation\n')
        api.dispatch('revise', {'item': worker['id'], 'brief': 'Corrected assignment', 'reason': 'False premise'})
        self.assertEqual(manager['status'], 'failed')
        self.assertTrue(manager.get('cancelled'))
        self.assertNotIn('repair-run', state.L['agents'])
        self.assertEqual(artifact.read_text(), 'unfinished investigation\n')
        self.assertEqual(state.L['queue'][worker['id']]['version'], 2)
        self.assertEqual(worker['status'], 'waiting')
        self.assertEqual(spawner.next_task()['id'], worker['id'])

    def test_recovery_can_finish_its_own_revision_but_legacy_foreign_revision_expires(self):
        worker = self.worker(start=False)
        lifecycle.fail(worker, 'Original assignment blocked')
        manager, _ = tasks.request_repair(worker)
        support.running(manager, 'repair-run')
        api.dispatch('revise', {'item': worker['id'], 'brief': 'Corrected assignment' + SUMMARY,
                               'reason': 'Verified correction', 'caller': support.caller(manager, 'repair-run')})
        self.assertEqual(manager['status'], 'running')
        self.assertFalse(frontier.obsolete(manager))
        # A retained authority written by an older daemon can contain the same stale relation.
        state.L['queue'][worker['id']]['revised_by'] = 'user'
        self.assertFalse(spawner.runnable(manager, {}))
        lifecycle.reconcile()
        self.assertEqual(manager['status'], 'failed')
        self.assertTrue(manager.get('cancelled'))

    def test_brief_revision_preserves_construction_metadata_unless_explicitly_changed(self):
        worker = support.queued(self.project, "contract", "Write tests\nRelies on: code.py", stage="test-contract",
                                reasoning_effort="xhigh", budget={"generation_seconds": 123, "generation_tokens": 456})
        self.as_manager("revise", item=worker["id"], brief="Correct the test brief\nRelies on: code.py", reason="false premise")
        record = state.L["queue"][worker["id"]]
        self.assertEqual((record["stage"], worker["stage"]), ("test-contract", "test-contract"))
        self.assertEqual((record["reasoning_effort"], worker["reasoning_effort"]), ("xhigh", "xhigh"))
        self.assertEqual(record["budget"], {"generation_seconds": 123, "generation_tokens": 456})
        self.assertEqual(worker["budget"], record["budget"])
        self.as_manager("revise", item=worker["id"], brief="Implement the tested behavior", reason="new stage",
                        stage="implementation", reasoning_effort="low", budget={"generation_tokens": 789})
        self.assertEqual((record["stage"], worker["stage"]), ("implementation", "implementation"))
        self.assertEqual(worker["reasoning_effort"], "low")
        self.assertEqual(record["budget"], {"generation_seconds": 123, "generation_tokens": 789})
        self.assertEqual(worker["budget"], record["budget"])

    def test_revising_an_undispatched_item_replaces_its_brief_and_dependencies(self):
        queues.add(self.project, "queued", "iface", "Extend the interface")
        queues.add(self.project, "queued", "impl", "Implement it")
        before = state.L["queue"]["p:impl"]["version"]
        self.as_manager("revise", item="p:impl", brief="Depends on: iface\nImplement the extended interface",
                        reason="the interface is extended first", stage="implementation")
        record = state.L["queue"]["p:impl"]
        self.assertEqual((record["depends"], queues.status(record)), (["iface"], "queued"))
        self.assertEqual(record["version"], before + 1)
        self.assertEqual(spawner.next_task()["id"], "p:iface", "the revised item now waits for its new dependency")

    def test_revising_a_running_item_restarts_it_fresh_on_the_new_brief(self):
        worker = self.worker()
        worker.update(session="old-session", runs=3)
        (Path(worker["worktree"]) / "partial.c").write_text("int partial;\n")
        self.as_manager("revise", item="p:impl", brief="Implement the extended interface", reason="interface extended")
        self.assertNotIn("worker-1", state.L["agents"])
        self.assertEqual((worker["status"], worker["session"], worker["runs"]), ("waiting", None, 0))
        self.assertEqual((worker["brief"], worker["record_version"]),
                         ("Implement the extended interface" + SUMMARY, state.L["queue"]["p:impl"]["version"]))
        self.assertTrue((Path(worker["worktree"]) / "partial.c").exists(), "the branch keeps earlier work")
        text = prompts.launch_text(worker, self.project)
        self.assertIn(f"Revised by {self.manager['id']}: interface extended", text)
        self.assertIn("Implement the extended interface", text)
        self.assertEqual(spawner.next_task()["id"], "p:impl")

    def test_revising_a_reviewed_item_sends_it_back_to_its_worker(self):
        worker = support.reviewed(self.worker(start=False), "worker-1")
        self.as_manager("revise", item="p:impl", brief="Implement the extended interface", reason="interface extended")
        self.assertEqual((worker["status"], worker["receipt"], worker["review"]), ("waiting", None, None))

    def test_a_reviewed_item_under_integration_must_wait(self):
        worker = support.reviewed(self.worker(start=False), "worker-1")
        integration = tasks.create("integrate", self.project, "integrate-impl", "b", [2], item="impl", worker=worker["id"])
        support.running(integration, "integrator-1", worktree=False)
        with self.assertRaisesRegex(ValueError, "being integrated"):
            self.as_manager("revise", item="p:impl", brief="Something else", reason="changed")
        self.assertEqual(worker["status"], "review")

    def test_existing_integration_waits_for_revised_worker_and_uses_the_new_brief(self):
        worker = support.reviewed(self.worker(start=False), "worker-1")
        integration = tasks.create("integrate", self.project, "integrate-impl", worker["brief"], [2],
                                   item="impl", worker=worker["id"])
        integration.update(session="old-review-session", runs=2)
        branch = integration["branch"]
        self.as_manager("hold", item=worker["id"])
        self.assertFalse(spawner.runnable(integration, {}), "holding reviewed work also gates an existing integration")
        self.as_manager("revise", item=worker["id"], brief="Implement the corrected contract", reason="false premise")
        self.assertEqual(spawner.next_task()["id"], worker["id"])
        self.assertEqual((integration["brief"], integration["session"], integration["runs"], integration["branch"]),
                         (worker["brief"], None, 0, branch))
        self.assertIn(worker["brief"], prompts.launch_text(integration, self.project))
        self.assertFalse(spawner.runnable(integration, {}))
        support.reviewed(worker, "worker-2")
        self.assertEqual(spawner.next_task()["id"], integration["id"])
        for status in ("waiting", "running", "failed", "done"):
            worker["status"] = status
            self.assertFalse(spawner.runnable(integration, {}), status)
        del state.L["tasks"][worker["id"]]
        self.assertFalse(spawner.runnable(integration, {}), "a missing worker cannot be integrated")

    def test_a_failed_item_can_be_revised_into_new_work(self):
        worker = self.worker()
        worker["runs"] = state.CONFIG["spawner"]["max_runs_per_task"]
        lifecycle.stop("worker-1", "silent too long", requeue=True)
        self.assertEqual((worker["status"], queues.status(state.L["queue"]["p:impl"])), ("failed", "blocked"))
        self.as_manager("revise", item="p:impl", brief="Implement a smaller slice", reason="the old scope was too big")
        self.assertEqual((worker["status"], worker["runs"], queues.status(state.L["queue"]["p:impl"])), ("waiting", 0, "queued"))

    def test_accepted_or_superseded_work_cannot_be_revised(self):
        worker = self.worker(start=False)
        worker.update(status="done", acceptance={"commit": "c", "worker_commit": "w", "via": "landing"})
        queues.finish(state.L["queue"]["p:impl"], commit="c", via="landing")
        with self.assertRaisesRegex(ValueError, "already accepted"):
            self.as_manager("revise", item="p:impl", brief="Again", reason="more")
        queues.add(self.project, "queued", "old", "Old")
        state.L["queue"]["p:old"]["replaced_by"] = ["impl"]
        with self.assertRaisesRegex(ValueError, "superseded"):
            self.as_manager("revise", item="p:old", brief="Again", reason="more")

    def test_a_revision_needs_a_reason_and_a_valid_brief(self):
        queues.add(self.project, "queued", "impl", "Implement it")
        for body, message in (({"brief": "New", "reason": " "}, "why"), ({"brief": "", "reason": "r"}, "brief"),
                              ({"brief": "New", "reason": "r", "stage": "whatever"}, "stage")):
            with self.subTest(body=body), self.assertRaisesRegex(ValueError, message):
                self.as_manager("revise", item="p:impl", **body)
        self.assertEqual(state.L["queue"]["p:impl"]["brief"], "Implement it")

    def test_superseding_rebases_existing_assignments_and_preserves_work_and_holds(self):
        parent = support.queued(self.project, "old", "Old")
        parent.update(status="failed", note="needs replacement")
        queues.add(self.project, "queued", "new", "Replacement")
        worker = self.worker("after", "Depends on: old\nKeep this work" + SUMMARY)
        path = Path(worker["worktree"]) / "artifact.txt"
        path.write_bytes(b"uncommitted work\0")
        worker["session"] = "old-session"
        record = state.L["queue"][worker["record"]]
        record["held_by"] = "user"
        worker["admission_hold"] = "explicit kill"
        integration = tasks.create("integrate", self.project, "integrate-after", worker["brief"], [2],
                                   worker=worker["id"])
        integration.update(session="old-review", admission_hold="review paused")
        api.dispatch("supersede", {"task": parent["id"], "replacements": ["new"], "reason": "repair dependency"})
        self.assertEqual(record["depends"], ["new"])
        self.assertEqual(queues.depends(worker["brief"]), ["new"])
        self.assertEqual(worker["record_version"], record["version"])
        self.assertEqual((worker["status"], worker["session"], worker["runs"]), ("waiting", None, 0))
        self.assertNotIn("worker-1", state.L["agents"])
        self.assertEqual(path.read_bytes(), b"uncommitted work\0")
        self.assertEqual((record["held_by"], worker["admission_hold"]), ("user", "explicit kill"))
        self.assertEqual((integration["brief"], integration["session"], integration["admission_hold"]),
                         (record["brief"], None, "review paused"))
        version = record["version"]
        api.dispatch("supersede", {"task": parent["id"], "replacements": ["new"], "reason": "repair dependency"})
        self.assertEqual(record["version"], version, "lost-reply retry must not reset it again")

    def test_replacement_refuses_active_validation_before_any_graph_change(self):
        import copy
        parent = support.queued(self.project, "old", "Old")
        parent.update(status="failed", note="needs replacement")
        queues.add(self.project, "queued", "new", "Replacement")
        worker = self.worker("after", "Depends on: old\nKeep this work" + SUMMARY, start=False)
        for mode in ("validation", "integration"):
            with self.subTest(mode=mode):
                worker["validating"] = mode == "validation"
                integration = tasks.create("integrate", self.project, "review-after-" + mode,
                                           worker["brief"], [2], worker=worker["id"])
                integration["status"] = "running" if mode == "integration" else "waiting"
                before = copy.deepcopy(state.L["queue"])
                with self.assertRaisesRegex(ValueError, "no records changed"):
                    api.dispatch("supersede", {"task": parent["id"], "replacements": ["new"], "reason": "repair"})
                self.assertEqual(state.L["queue"], before)

    # ------------------------------------------------ rights

    def test_only_the_owning_projects_manager_or_user_decides(self):
        queues.add(self.project, "queued", "impl", "Implement it")
        steward = support.running(tasks.create("steward", tasks.SYSTEM, "loose-ends", "", [6]), "steward-1", worktree=False)
        with self.assertRaisesRegex(ValueError, "owning project's running manager"):
            api.dispatch("hold", {"item": "p:impl", "caller": support.caller(steward, "steward-1")})
        other = {**self.project, "name": "q"}
        state.CONFIG["projects"].append(other)
        foreign = support.running(support.queued(other, "plan", "Plan", kind="command"), "manager-2", worktree=False)
        with self.assertRaisesRegex(ValueError, "owning project's running manager"):
            api.dispatch("revise", {"item": "p:impl", "brief": "X", "reason": "r",
                                    "caller": support.caller(foreign, "manager-2")})
        with self.assertRaisesRegex(ValueError, "has no queue item"):
            api.dispatch("hold", {"item": "impl"})
        api.dispatch("hold", {"item": "p:impl"})  # the user
        self.assertEqual(state.L["queue"]["p:impl"]["held_by"], "user")

    def test_same_project_qualified_dependencies_normalize_brief_metadata_and_retry_aliases(self):
        queues.add(self.project, 'queued', 'base', 'Build the base')
        qualified = 'Depends on: p:base, base, p:later, later\nImplement after both prerequisites.' + SUMMARY
        result = self.as_manager('queue', project='p', kind='queued', name='qualified', brief=qualified)
        record = state.L['queue']['p:' + result['item']]
        self.assertEqual(record['depends'], ['base', 'later'])
        self.assertEqual(queues.line(record['brief'], 'Depends on'), 'base, later')
        self.assertNotIn('p:base', record['brief'])
        # Equivalent caller spelling is one proposal, including lost-response retries.
        repeated = self.as_manager('queue', project='p', kind='queued', name='qualified',
                                   brief=qualified.replace('p:base, base, p:later, later', 'base, later'))
        self.assertEqual(repeated, result)
        self.assertEqual(record['version'], 1)
        self.assertEqual(record['proposed_by'], self.manager['id'])
        readiness = lambda: queues.readiness(queues.live('p'), queues.landed('p'))['qualified']
        self.assertEqual(readiness(), 'depends on unknown later')
        queues.add(self.project, 'queued', 'later', 'Build the forward prerequisite')
        self.assertEqual(readiness(), 'waiting')
        queues.finish(state.L['queue']['p:base'])
        queues.finish(state.L['queue']['p:later'])
        self.assertEqual(readiness(), 'ready')

    def test_revising_running_item_normalizes_same_project_dependencies_in_task_and_record(self):
        worker = self.worker()
        queues.add(self.project, 'queued', 'base', 'Build the base')
        self.as_manager('revise', item='p:impl', reason='Use the corrected prerequisite',
                        brief='Depends on: p:base, base, p:later\nImplement the corrected brief.')
        record = state.L['queue']['p:impl']
        self.assertEqual(record['depends'], ['base', 'later'])
        self.assertEqual(queues.line(record['brief'], 'Depends on'), 'base, later')
        self.assertEqual(worker['brief'], record['brief'])
        self.assertEqual(worker['record_version'], 2)
        self.assertEqual(record['version'], 2)
        self.assertEqual(worker['status'], 'waiting')
        self.assertNotIn('worker-1', state.L['agents'])

    def test_foreign_and_malformed_qualified_dependencies_refuse_before_any_mutation(self):
        worker = self.worker()
        source = Path(worker['worktree']) / 'preserved-source.txt'
        source.write_bytes(b'Uncommitted fixture work must survive refusal.\n')
        original_bytes = source.read_bytes()
        rejected = ('q:base', ':base', 'p:', 'p::base', 'p:base:extra', 'p:none', 'p:base/item', 'p:base name')
        for held in (False, True):
            if held:
                self.as_manager('hold', item='p:impl')
            for dependency in rejected:
                for action in ('queue', 'revise'):
                    with self.subTest(held=held, dependency=dependency, action=action):
                        before = copy.deepcopy(state.L)
                        body = {'brief': 'Depends on: ' + dependency + '\nDo the checked work.' + SUMMARY}
                        if action == 'queue':
                            body.update(project='p', kind='queued', name='refused')
                        else:
                            body.update(item='p:impl', reason='Check prerequisite identity before revising')
                        with self.assertRaises(ValueError):
                            self.as_manager(action, **body)
                        self.assertEqual(state.L, before, 'refusal changed a hold, run, brief, version or queue record')
                        self.assertEqual(source.read_bytes(), original_bytes)
            self.assertEqual(worker['status'], 'waiting' if held else 'running')
            self.assertEqual(state.L['queue']['p:impl']['held_by'], self.manager['id'] if held else None)



if __name__ == "__main__":
    unittest.main()
