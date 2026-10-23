import tempfile
import subprocess
import threading
import http.client
from http.server import ThreadingHTTPServer
import unittest
from pathlib import Path
from unittest.mock import patch

from cointos import api, config, gateway, git, schema, spawner, state, tasks, trees
from tests import support

GREEN = "green=15 yellow=0 brown=0\n"
SICK = ("brown\tlocal:what/is/the/state.md\tbrown: priority-one incident\n"
        "yellow\tlocal:what/is/next.md\tmarked yellow for re-verification\n"
        "yellow\tlocal:where/am/i.md\tmarked yellow for re-verification\n"
        "green=12 yellow=2 brown=1\n")


class Health(unittest.TestCase):
    def test_a_green_tree_has_nothing_to_tend(self):
        health = trees.parse(GREEN)
        self.assertEqual((health["brown"], health["yellow"], health["leaves"]), (0, 0, []))

    def test_leaves_needing_care_are_counted_and_named(self):
        health = trees.parse(SICK)
        self.assertEqual((health["brown"], health["yellow"], len(health["leaves"])), (1, 2, 3))
        self.assertNotEqual(health["hash"], trees.parse(GREEN)["hash"])

    def test_bounded_selection_prioritizes_repairs_and_samples_without_repeats(self):
        self.assertEqual(trees.select(trees.parse(SICK), [], 1), [])
        self.assertEqual(trees.select(trees.parse(SICK), trees.pending(trees.parse(SICK)), 1),
                         ["what/is/the/state.md"])
        leaves = [f"what/is/{n}.md" for n in range(10)]
        selected = trees.select(trees.parse(GREEN), leaves, 3)
        self.assertEqual(len(set(selected)), 3)
        self.assertTrue(set(selected) <= set(leaves))
        self.assertEqual(trees.select(trees.parse(GREEN), ["one.md"], 3), ["one.md"])
        self.assertEqual(trees.select(trees.parse(GREEN), [], 3), [])


class Ranks(unittest.TestCase):
    """Brown leaves go before landing and all queued work, yellow before queued work (even the
    top of the queue), a routine pass with structural audits; the worse tree first."""

    def test_brown_before_landing_and_yellow_before_queued(self):
        brown, yellow = trees.rank(trees.parse(SICK)), trees.rank({"brown": 0, "yellow": 2})
        self.assertLess(brown, [schema.KINDS["integrate"]["rank"]])
        self.assertLess([schema.KINDS["integrate"]["rank"]], yellow)
        self.assertLess(yellow, [schema.KINDS["item"]["rank"], 0])
        self.assertEqual(trees.rank(trees.parse(GREEN)), [schema.KINDS["tree-audit"]["rank"]])

    def test_the_worse_tree_first(self):
        self.assertLess(trees.rank({"brown": 3, "yellow": 0}), trees.rank({"brown": 1, "yellow": 5}))
        self.assertLess(trees.rank({"brown": 0, "yellow": 4}), trees.rank({"brown": 0, "yellow": 1}))


class TreeObservation(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self)
        self.repo = support.repository(self)
        self.tree = {'name': 'observed', 'path': str(self.repo), 'tree': '.knowledge', 'main_branch': 'main'}
        self.enterContext(patch.dict(state.CONFIG, projects=[], trees=[self.tree]))
        self.health = {**trees.parse(GREEN), 'inventory': ['what/is/fixture.md'], 'deferred': []}

    def test_blocked_tree_observation_keeps_dashboard_and_admission_available(self):
        entered, release = threading.Event(), threading.Event()
        def read(*args):
            self.assertFalse(state.LOCK._is_owned(), 'tree observation retained the state lock')
            entered.set(); release.wait(3)
            return self.health
        server = ThreadingHTTPServer(('127.0.0.1', 0), gateway.Handler)
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        observer = threading.Thread(target=spawner.refresh_trees)
        try:
            with patch.object(trees, 'health', side_effect=read):
                observer.start(); self.assertTrue(entered.wait(1))
                connection = http.client.HTTPConnection(*server.server_address, timeout=1)
                try:
                    connection.request('GET', '/api/ledger')
                    response = connection.getresponse()
                    self.assertEqual(response.status, 200); response.read()
                finally:
                    connection.close()
                with state.LOCK:
                    self.assertEqual(spawner.tree_work(), [])
                    self.assertNotIn('observed', state.L['trees'])
                release.set(); observer.join(2)
            self.assertFalse(observer.is_alive())
            self.assertEqual(spawner.tree_health(self.tree)['inventory'], self.health['inventory'])
        finally:
            release.set()
            if observer.ident is not None: observer.join(2)
            server.shutdown(); server.server_close()

    def test_config_changes_newer_observations_and_drain_revoke_inflight_results(self):
        for change in ('remove', 'newer', 'drain', 'stop'):
            with self.subTest(change=change), patch.dict(state.CONFIG, trees=[self.tree]):
                state.L['trees'].clear(); state.L['restarting'] = False; state.STOPPING.clear()
                newer = {**self.health, 'checked_at': 999, 'hash': 'newer'}
                def read(*args):
                    with state.LOCK:
                        if change == 'remove': state.CONFIG['trees'] = []
                        elif change == 'newer': state.L['trees']['observed'] = newer
                        elif change == 'drain': state.L['restarting'] = True
                        else: state.STOPPING.set()
                    return self.health
                with patch.object(trees, 'health', side_effect=read): spawner.refresh_trees()
                if change == 'newer': self.assertIs(state.L['trees']['observed'], newer)
                else: self.assertNotIn('observed', state.L['trees'])

    def test_read_failure_is_published_and_reported_once_at_existing_cadence(self):
        with patch.object(trees, 'health', side_effect=RuntimeError('fixture unavailable')) as read, \
                patch.object(spawner, 'alert') as notify:
            spawner.refresh_trees(); spawner.refresh_trees()
            self.assertEqual(read.call_count, 1)
            self.assertIsNone(spawner.tree_health(self.tree))
            self.assertEqual(state.L['trees']['observed']['error'], 'fixture unavailable')
            state.L['trees']['observed']['checked_at'] = 0
            spawner.refresh_trees()
            self.assertEqual(read.call_count, 2); self.assertEqual(notify.call_count, 1)

    def test_disabled_tree_is_not_observed(self):
        with patch.dict(state.CONFIG, projects=[{**self.tree, 'enabled': False}]), \
                patch.object(trees, 'health') as read:
            spawner.refresh_trees(); read.assert_not_called()


class GardeningTasks(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self)
        self.repo = support.repository(self)
        self.root = self.repo / ".knowledge"
        self.root.mkdir()
        for n in range(5):
            (self.root / f"{n}.md").write_text("A test answer.")
        support.commit(self.repo)
        tree = {"name": "test", "path": str(self.repo), "tree": ".knowledge", "main_branch": "main"}
        self.enterContext(patch.dict(state.CONFIG, projects=[], trees=[tree]))
        self.tree = tree
        self.read_health = spawner.tree_health
        self.inventory = trees.inventory(tree)
        self.health = self.enterContext(patch.object(spawner, "tree_health", return_value={
            **trees.parse(GREEN), 'inventory': self.inventory}))

    def test_routine_batch_is_fixed_at_creation_and_blocks_an_overlapping_audit(self):
        task = spawner.next_task()
        self.assertEqual((task["kind"], task["role"]), ("garden", "gardener"))
        self.assertEqual(len(task["brief"].splitlines()), state.CONFIG["garden"]["leaves_per_pass"])
        task["status"] = "running"
        self.assertIsNone(spawner.next_task())

    def test_routine_batch_never_names_a_leaf_the_worktree_cannot_see(self):
        # An uncommitted working-tree leaf is not in the main branch, so a garden worktree
        # (built from it) cannot see it; the inventory must exclude it or the gardener chases a
        # phantom address (the recurring blocked garden).
        (self.root / "untracked").mkdir()
        (self.root / "untracked" / "phantom.md").write_text("Not committed anywhere.")
        self.assertEqual(trees.inventory(self.tree), [f"{n}.md" for n in range(5)])
        self.assertNotIn("untracked/phantom.md", trees.inventory(self.tree))
        for _ in range(20):
            self.assertTrue(set(trees.select(trees.parse(GREEN), trees.inventory(self.tree), 3))
                            <= {f"{n}.md" for n in range(5)})

    def test_structural_audit_has_its_own_role_and_cadence(self):
        state.L["cadence"]["garden:test"] = state.now()
        task = spawner.next_task()
        self.assertEqual((task["kind"], task["role"]), ("tree-audit", "tree-auditor"))
        self.assertEqual(task["brief"], "")
        task["status"] = "done"
        self.assertIsNone(spawner.next_task())

    def test_changed_remaining_health_schedules_another_bounded_batch(self):
        self.health.return_value = {**trees.parse('brown\tlocal:0.md\tneeds repair\n'), 'inventory': self.inventory}
        task = spawner.next_task()
        self.assertEqual(task["brief"].splitlines()[0], "0.md")
        task["status"] = "done"
        self.health.return_value = {**trees.parse("yellow\tlocal:2.md\tunverified\n"), 'inventory': self.inventory}
        following = spawner.next_task()
        self.assertNotEqual(following["id"], task["id"])
        self.assertEqual(following["brief"], "2.md")

    def test_health_repair_never_dispatches_an_untracked_phantom_or_empty_batch(self):
        (self.root / 'draft.md').write_text('A pending canonical answer.\n')
        self.health.return_value = {**trees.parse('brown\tlocal:draft.md\tneeds repair\n'), 'inventory': self.inventory}
        self.assertIsNone(spawner.next_task())
        self.assertFalse(state.L['tasks'])

    def test_routine_batch_preserves_pending_answers_index_and_policy_but_allows_health_stamps(self):
        (self.root / '0.md').write_text('Unstaged current answer.\n')
        (self.root / '1.md').write_text('Staged current answer.\n')
        git.run(self.repo, 'add', '.knowledge/1.md')
        (self.root / '1.md').write_text('A test answer.')  # the index still contains a draft
        (self.root / '2.md').unlink()
        (self.root / '3.md').write_text('---\nexpires_every: 2d\n---\nA test answer.')
        (self.root / '4.md').write_text('---\nstatus: yellow\nchecked_at: now\nrevised_at: now\n---\nA test answer.')
        before = (git.head(self.repo), (self.repo / '.git/index').read_bytes(),
                  git.run(self.repo, 'diff'), git.run(self.repo, 'diff', '--cached'))
        run = subprocess.run
        def status(command, *args, **kwargs):
            if command[:2] == ['kt', 'status']:
                return subprocess.CompletedProcess(command, 0, stdout=GREEN, stderr='')
            return run(command, *args, **kwargs)
        self.health.side_effect = self.read_health
        with patch.object(trees.subprocess, 'run', side_effect=status):
            spawner.refresh_trees()
            task = spawner.next_task()
        self.assertEqual(task['brief'], '4.md')
        self.assertEqual(before, (git.head(self.repo), (self.repo / '.git/index').read_bytes(),
                         git.run(self.repo, 'diff'), git.run(self.repo, 'diff', '--cached')))

    def test_unavailable_health_answers_are_reported_once_without_a_phantom_task(self):
        health = {**trees.parse(SICK), 'inventory': [], 'deferred': trees.pending(trees.parse(SICK))}
        with patch.object(trees, 'health', return_value=health), patch.object(spawner, 'alert') as notify:
            spawner.refresh_trees()
            self.read_health(self.tree)
            spawner.refresh_trees()
            self.read_health(self.tree)
        self.assertEqual(notify.call_count, 1)
        self.assertIn('pending or absent canonical answers', notify.call_args.args[0])
        self.assertFalse(state.L['tasks'])

    def test_no_change_gardener_cannot_complete_against_a_newer_canonical_answer(self):
        task = support.running(spawner.next_task(), 'garden-run')
        selected = task['brief'].splitlines()[0]
        canonical = self.root / selected
        canonical.write_text('A newer pending owner answer.\n')
        run = subprocess.run
        def status(command, *args, **kwargs):
            if command[:2] == ['kt', 'status']:
                return subprocess.CompletedProcess(command, 0, stdout=GREEN, stderr='')
            return run(command, *args, **kwargs)
        body = {'caller': support.caller(task, 'garden-run'), 'outcome': 'complete',
                'detail': 'Checked my unchanged branch snapshot'}
        with patch.object(trees.subprocess, 'run', side_effect=status):
            with self.assertRaisesRegex(ValueError, 'pending canonical knowledge'):
                api.dispatch('finish', body)
        self.assertIsNone(task['receipt'])
        result = api.dispatch('finish', {**body, 'outcome': 'blocked', 'detail': 'Canonical owner has a newer draft'})
        self.assertEqual(result['receipt']['disposition'], 'blocked')
        self.assertEqual(canonical.read_text(), 'A newer pending owner answer.\n')

    def test_draft_blocked_garden_defers_recovery_until_its_owner_commits(self):
        task = support.running(spawner.next_task(), 'garden-run')
        selected = task['brief'].splitlines()[0]
        canonical = self.root / selected
        canonical.write_text('The canonical owner is still writing this answer.\n')
        api.dispatch('finish', {'caller': support.caller(task, 'garden-run'),
                               'outcome': 'blocked', 'detail': 'Pending canonical answer'})
        self.health.side_effect = self.read_health
        run = subprocess.run
        def status(command, *args, **kwargs):
            if command[:2] == ['kt', 'status']:
                return subprocess.CompletedProcess(command, 0, stdout=GREEN, stderr='')
            return run(command, *args, **kwargs)
        with patch.object(trees.subprocess, 'run', side_effect=status):
            spawner.refresh_trees()
            spawner.repair_work({})
            self.assertFalse(any(t.get('repair_origin') for t in state.L['tasks'].values()))
            self.assertEqual(task['receipt']['disposition'], 'blocked')
            self.assertEqual(canonical.read_text(), 'The canonical owner is still writing this answer.\n')
            support.commit(self.repo, 'owner commits its answer')
            state.L['trees'][self.tree['name']]['checked_at'] = 0
            spawner.refresh_trees()
            spawner.repair_work({})
        repairs = [t for t in state.L['tasks'].values() if t.get('repair_origin')]
        self.assertEqual(len(repairs), 1)
        self.assertEqual(repairs[0]['repair_origin']['task'], task['id'])

    def test_draft_deferral_preserves_started_recovery_and_fails_open_on_unknown_health(self):
        task = spawner.next_task()
        task.update(status='done', receipt={'disposition': 'blocked', 'summary': 'Pending answer'})
        repair, _ = tasks.request_repair(task)
        self.health.return_value = {**trees.parse(GREEN), 'deferred': task['brief'].splitlines()}
        self.assertFalse(spawner.runnable(repair, {}))
        self.health.return_value = None
        state.L['trees'][self.tree['name']] = {'error': 'unavailable', 'checked_at': state.now()}
        self.assertTrue(spawner.runnable(repair, {}), 'unknown health must not hide a repairable failure')
        self.health.return_value = {**trees.parse(GREEN), 'deferred': task['brief'].splitlines()}
        support.running(repair, 'repair-run', worktree=False)
        self.assertTrue(spawner.runnable(repair, {}), 'started recovery retains its context and allowance')

    def test_garden_recovery_waits_for_first_observation_then_retains_read_failure_behavior(self):
        task = spawner.next_task()
        task.update(status='done', receipt={'disposition': 'blocked', 'summary': 'Pending answer'})
        self.health.side_effect = self.read_health
        spawner.repair_work({})
        self.assertFalse(any(t.get('repair_origin') for t in state.L['tasks'].values()))
        with patch.object(trees, 'health', side_effect=RuntimeError('fixture unavailable')):
            spawner.refresh_trees()
        spawner.repair_work({})
        repairs = [t for t in state.L['tasks'].values() if t.get('repair_origin')]
        self.assertEqual(len(repairs), 1)
        self.assertTrue(spawner.runnable(repairs[0], {}))

    def test_clean_editor_branch_does_not_hide_accepted_main_answers(self):
        before = git.head(self.repo)
        (self.root / '0.md').write_text('New answer on accepted main.\n')
        (self.root / 'main-only.md').write_text('An accepted answer absent from the editor branch.\n')
        main = support.commit(self.repo, 'advance accepted knowledge')
        git.run(self.repo, 'switch', '-qc', 'editor', before)
        index = (self.repo / '.git/index').read_bytes()
        self.assertEqual(trees.available_inventory(self.tree), [f'{n}.md' for n in range(5)] + ['main-only.md'])
        self.assertEqual(git.head(self.repo), before)
        self.assertEqual(git.head(self.repo, 'main'), main)
        self.assertEqual((self.repo / '.git/index').read_bytes(), index)

    def test_registered_project_trees_are_gardened_without_manual_tree_entries(self):
        project = {"name": "project", "path": str(self.root.parent), "main_branch": "main"}
        (self.root.parent / ".knowledge").mkdir(exist_ok=True)
        with patch.dict(state.CONFIG, projects=[project], trees=[]):
            self.assertEqual([tree["name"] for tree in config.managed_trees(state.CONFIG)], ["project"])

    def test_a_disabled_projects_tree_is_not_maintained(self):
        project = {"name": "project", "path": str(self.root.parent), "main_branch": "main", "enabled": False}
        (self.root.parent / ".knowledge").mkdir(exist_ok=True)
        with patch.dict(state.CONFIG, projects=[project], trees=[]):
            self.assertEqual(spawner.tree_work(), [])
            self.assertEqual([tree["name"] for tree in config.managed_trees(state.CONFIG)], ["project"])


if __name__ == "__main__":
    unittest.main()
