"""The ledger migration: an old stored-status ledger becomes the current schema, its packets and
idle worker branches lose the retired work report, and a second run changes nothing."""
import copy
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from cointos import git, queues, state
from tests import support

loader = importlib.machinery.SourceFileLoader("upgrade_ledger", str(Path(__file__).parents[1] / "scripts/upgrade-ledger"))
spec = importlib.util.spec_from_loader("upgrade_ledger", loader)
upgrade_ledger = importlib.util.module_from_spec(spec)
loader.exec_module(upgrade_ledger)


def task(task_id, kind, status, record_hash, **fields):
    project, _, item = task_id.partition(":")
    return {"id": task_id, "kind": kind, "status": status, "record_hash": record_hash, "place": project,
            "item": item.removeprefix("decompose-"), "branch": None, "worktree": None, "receipt": None,
            "note": None, "brief": "b", "updated_at": 5, **fields}


class Upgrade(unittest.TestCase):
    def recovery_ledger(self):
        ledger = self.alias_ledger()
        owner = task('p:decompose-impl', 'decompose', 'waiting', None, record='p:impl',
                     record_version=4, role='manager', session='manager-session', created_at=1,
                     system_context='old-manager-prompt', tool_context='old-manager-tools')
        controller = task('p:operator-repair-1', 'operator', 'waiting', None, record=None,
                          record_version=4, role='operator', session='operator-session', created_at=2,
                          repair_origin={'task': owner['id'], 'version': 4},
                          system_context='old-operator-prompt', tool_context='old-operator-tools')
        ledger['tasks'].update({t['id']: t for t in (owner, controller)})
        return ledger

    def test_recovery_chains_collapse_to_one_capable_owner_with_all_evidence_preserved(self):
        original = self.recovery_ledger()
        upgraded = upgrade_ledger.upgrade(copy.deepcopy(original), [])
        owners = [t for t in upgraded['tasks'].values() if t.get('repair_origin')]
        self.assertEqual(len(owners), 1)
        self.assertEqual(owners[0]['id'], 'p:operator-repair-1')
        self.assertEqual(owners[0]['repair_origin'], {'task': 'p:impl', 'version': 4})
        for key in ('p:decompose-impl', 'p:operator-repair-1'):
            migrated, old = upgraded['tasks'][key], original['tasks'][key]
            self.assertIn(old['session'], migrated['previous_sessions'])
            self.assertEqual(migrated['brief'], old['brief'])
            self.assertEqual(migrated['receipt'], old['receipt'])
            self.assertIsNone(migrated['session'])
            self.assertNotIn('tool_context', migrated)
        self.assertEqual(upgraded['tasks']['p:decompose-impl']['recovery_owner'], owners[0]['id'])
        self.assertEqual(upgrade_ledger.upgrade(copy.deepcopy(upgraded), []), upgraded)

    def test_active_recovery_refuses_upgrade_without_partial_mutation(self):
        ledger = self.recovery_ledger()
        ledger['tasks']['p:operator-repair-1']['status'] = 'running'
        before = copy.deepcopy(ledger)
        with self.assertRaisesRegex(ValueError, 'pause construction'):
            upgrade_ledger.upgrade(ledger, [])
        self.assertEqual(ledger, before)

    def alias_ledger(self):
        brief = 'Summary: preserve accepted work and its original assignment\nDepends on: p:base, base, p:later\nKeep this exact product instruction.'
        record = dict(project='p', item='impl', kind='queued', brief=brief, summary='original summary',
                      depends=['p:base', 'base', 'p:later'], stage='implementation', reasoning_effort=None,
                      version=4, held_by='user', priority=1)
        base = dict(record, item='base', brief='Accepted original brief', depends=[],
                    done={'at': 1, 'commit': 'abc', 'via': 'tests'})
        worker = task('p:impl', 'item', 'running', None, record_version=4, record='p:impl',
                      session='retained-session', agent='retained-agent', admission_hold='user hold',
                      receipt={'disposition': 'blocked', 'summary': 'retained evidence'}, brief=brief)
        worker.pop('record_hash')  # already-current task, not the legacy hash schema
        return {'queue': {'p:base': base, 'p:impl': record}, 'tasks': {'p:impl': worker},
                'agents': {'retained-agent': {'task': 'p:impl'}}, 'history': [{'evidence': 'retained'}]}

    def test_version_four_aliases_migrate_without_assignment_or_evidence_changes(self):
        original = self.alias_ledger()
        expected = dict(copy.deepcopy(original), frontier_version=1)
        desired = queues.contents('queued', original['queue']['p:impl']['brief'], project='p')
        expected['queue']['p:impl'].update(depends=desired['depends'], brief=desired['brief'])
        expected['tasks']['p:impl'].setdefault('record_version', 4)
        migrated = upgrade_ledger.upgrade(copy.deepcopy(original), [])
        self.assertEqual(migrated, expected)
        state.L.update(migrated)
        self.assertEqual(queues.readiness(queues.live('p'), queues.landed('p'))['impl'], 'depends on unknown later')
        # A legitimate local forward reference stays unresolved until accepted.
        later = dict(migrated['queue']['p:base'], item='later', done={'at': 2, 'commit': 'def', 'via': 'landing'})
        migrated['queue']['p:later'] = later
        self.assertEqual(queues.readiness(queues.live('p'), queues.landed('p'))['impl'], 'ready')
        self.assertEqual(upgrade_ledger.upgrade(copy.deepcopy(migrated), []), migrated)
        self.assertIn('p:base', migrated['tasks']['p:impl']['brief'], 'historical/live conversation evidence is untouched')

    def test_qualified_preflight_refuses_entire_upgrade_before_mutation_or_git(self):
        for name in ('foreign:base', 'p:Base', 'p:base:extra', 'p:none'):
            ledger = self.alias_ledger()
            ledger['queue']['p:invalid'] = dict(ledger['queue']['p:impl'], item='invalid', depends=[name],
                                               brief='Depends on: ' + name)
            before = copy.deepcopy(ledger)
            with self.subTest(name=name), patch.object(upgrade_ledger, 'git') as native:
                with self.assertRaises(ValueError): upgrade_ledger.upgrade(ledger, [])
                native.assert_not_called()
            self.assertEqual(ledger, before)

    def test_disagreeing_qualified_brief_refuses_without_choosing_product_intent(self):
        ledger = self.alias_ledger()
        ledger['queue']['p:impl']['brief'] = 'Depends on: p:different\nRetain product instruction'
        before = copy.deepcopy(ledger)
        with patch.object(upgrade_ledger, 'git') as native:
            with self.assertRaisesRegex(ValueError, 'disagrees'): upgrade_ledger.upgrade(ledger, [])
            native.assert_not_called()
        self.assertEqual(ledger, before)

    def test_alias_order_does_not_turn_the_same_dependency_graph_into_a_revision(self):
        ledger = self.alias_ledger()
        ledger['queue']['p:impl']['brief'] = 'Depends on: p:later, p:base\nRetain exact product instruction.'
        migrated = upgrade_ledger.upgrade(ledger, [])
        record = migrated['queue']['p:impl']
        self.assertEqual(record['depends'], ['base', 'later'])
        self.assertEqual(record['brief'], 'Depends on: base, later\nRetain exact product instruction.')
        self.assertEqual(record['version'], 4)

    def test_aliases_also_preserve_supported_unversioned_upgrade(self):
        ledger = self.alias_ledger()
        record = ledger['queue']['p:impl']
        record.pop('version')
        record['status'] = 'queued'
        migrated = upgrade_ledger.upgrade(ledger, [])
        self.assertEqual(record['version'], 1)
        self.assertNotIn('status', record)
        self.assertEqual(record['depends'], ['base', 'later'])
        self.assertEqual(migrated['tasks']['p:impl']['record_version'], 1)
        self.assertEqual(migrated['tasks']['p:impl']['session'], 'retained-session')

    def test_every_secondary_dependency_line_refuses_before_any_changes_or_git(self):
        for secondary in ('foreign:base', 'p:base:extra', 'p:different', 'base', 'none'):
            ledger = self.alias_ledger()
            ledger['queue']['p:impl']['brief'] += '\nDepends on: ' + secondary + '\nExact remaining text\n'
            before = copy.deepcopy(ledger)
            with self.subTest(secondary=secondary), patch.object(upgrade_ledger, 'git') as native:
                with self.assertRaises(ValueError): upgrade_ledger.upgrade(ledger, [])
                native.assert_not_called()
            self.assertEqual(ledger, before)

    def test_migration_preserves_crlf_trailing_newline_and_all_nonmetadata_bytes(self):
        for ending in ('\r\n', '\n', '\r'):
            for trailing in ('', ending):
                ledger = self.alias_ledger()
                brief = ending.join(('  Exact first instruction.  ', 'Depends on: p:base, p:later',
                                     'Exact middle instruction.\t', '**Depends on:** later, base',
                                     'Exact final instruction.')) + trailing
                ledger['queue']['p:impl']['brief'] = brief
                old_task = copy.deepcopy(ledger['tasks']['p:impl'])
                with self.subTest(ending=repr(ending), trailing=repr(trailing)):
                    migrated = upgrade_ledger.upgrade(ledger, [])
                    expected = brief.replace('Depends on: p:base, p:later', 'Depends on: base, later')
                    expected = expected.replace('**Depends on:** later, base', 'Depends on: base, later')
                    self.assertEqual(migrated['queue']['p:impl']['brief'], expected)
                    self.assertEqual(migrated['tasks']['p:impl'], old_task)

    def test_secondary_metadata_failure_preserves_durable_bytes(self):
        root = self.repo / 'secondary-runtime'
        (root / 'state').mkdir(parents=True)
        (root / 'config').mkdir()
        (root / 'config/projects.json').write_text('[]')
        ledger = self.alias_ledger()
        ledger['queue']['p:impl']['brief'] += '\r\nDepends on: foreign:base\r\n'
        path = root / 'state/cointos.json'
        path.write_bytes((json.dumps(ledger, indent=3) + '\r\n').encode())
        before = path.read_bytes()
        with patch.object(upgrade_ledger, 'git') as native:
            with self.assertRaises(ValueError): upgrade_ledger.main(path)
            native.assert_not_called()
        self.assertEqual(path.read_bytes(), before)

    def test_durable_migration_refusal_preserves_original_bytes_and_has_no_git_effects(self):
        root = self.repo / 'owned-runtime'
        (root / 'state').mkdir(parents=True)
        (root / 'config').mkdir()
        (root / 'config/projects.json').write_text('[]')
        ledger = self.alias_ledger()
        ledger['queue']['p:impl']['depends'] = ['foreign:base']
        path = root / 'state/cointos.json'
        path.write_text(json.dumps(ledger, indent=3) + '\n')
        before = path.read_bytes()
        with patch.object(upgrade_ledger, 'git') as native:
            with self.assertRaises(ValueError): upgrade_ledger.main(path)
            native.assert_not_called()
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(path.with_name('.cointos.json.upgrade').exists())

    def test_inactive_blocked_assessment_routes_directly_to_manager_once(self):
        worker = task('p:a', 'item', 'review', None,
                      receipt={'disposition': 'blocked', 'summary': 'mismatch'})
        integration = task('p:integrate-a', 'integrate', 'waiting', None, worker='p:a')
        ledger = {'tasks': {t['id']: t for t in (worker, integration)}, 'queue': {}}
        first = upgrade_ledger.upgrade(ledger, [])
        self.assertEqual(worker['status'], 'failed')
        self.assertEqual(integration['status'], 'failed')
        self.assertEqual(worker['receipt']['summary'], 'mismatch')
        self.assertEqual(upgrade_ledger.upgrade(copy.deepcopy(first), []), first)

    def setUp(self):
        support.fresh_ledger(self)
        self.repo = support.repository(self)
        self.project = support.project(self, self.repo)

    def packet(self, with_report=True):
        git.run(self.repo, "checkout", "-q", "-b", "work/tests-a")
        (self.repo / "test_a.txt").write_text("test\n")
        if with_report:
            (self.repo / ".work-report.md").write_text("Status: done\n")
        commit = support.commit(self.repo, "tests")
        git.run(self.repo, "checkout", "-q", "main")
        return commit

    def test_unscoped_coin_cache_is_disposable_while_scoped_and_shared_states_survive(self):
        ledger = {"snapshots": {name: {"owner": owner} for name, owner in
                  (("old", "coin"), ("per-user", "coin/opaque"), ("start", "shared"), ("task", "p:work"))},
                  "queue": {}, "tasks": {}}
        first = upgrade_ledger.upgrade(ledger, [])
        self.assertEqual(set(first["snapshots"]), {"per-user", "start", "task"})
        self.assertEqual(upgrade_ledger.upgrade(copy.deepcopy(first), []), first)

    def ledger(self, packet):
        record = lambda item, status, **f: {"project": "p", "item": item, "kind": "queued", "brief": item, "summary": None,
                                            "depends": [], "stage": "implementation", "reasoning_effort": None,
                                            "held_by": None, "priority": 1, "status": status, "decompose": False,
                                            "hash": f"h-{item}", **f}
        return {
            "queue": {
                "p:tests-a": record("tests-a", "done", stage="test-contract", commit=packet),
                "p:landed": record("landed", "done", commit="abc"),
                "p:awaiting": record("awaiting", "blocked", decompose=True, report="r", depends=["`landed`.", "none"]),
                "p:stuck": record("stuck", "blocked", report="manager gave up", held_by="someone"),
                "p:split": record("split", "done", replaced_by=["landed"]),
                "p:fresh": record("fresh", "queued"),
            },
            "tasks": {
                "p:tests-a": task("p:tests-a", "item", "done", "x"),
                "p:landed": task("p:landed", "item", "done", "h-landed",
                                 acceptance={"commit": "abc", "worker_commit": "w", "via": "landing"}),
                "p:awaiting": task("p:awaiting", "item", "failed", "old-hash"),
                "p:decompose-awaiting": task("p:decompose-awaiting", "decompose", "done", "older-hash"),
                "p:stuck": task("p:stuck", "item", "failed", "old-hash"),
                "p:decompose-stuck": task("p:decompose-stuck", "decompose", "failed", "h-stuck"),
                "p:fresh": task("p:fresh", "item", "failed", "stale"),
                "p:garden-1": task("p:garden-1", "garden", "done", "health-hash"),
            },
        }

    def test_an_old_ledger_keeps_where_every_record_stands(self):
        packet = self.packet()
        upgraded = upgrade_ledger.upgrade(self.ledger(packet), [self.project])
        state.L.update(upgraded)
        stands = {k: queues.state(r) for k, r in upgraded["queue"].items()}
        self.assertEqual({k: s["status"] for k, s in stands.items()},
                         {"p:tests-a": "done", "p:landed": "done", "p:awaiting": "blocked", "p:stuck": "blocked",
                          "p:split": "replaced", "p:fresh": "queued"})
        self.assertTrue(stands["p:awaiting"]["recoverable"], "a failed item still awaits its manager")
        self.assertTrue(stands["p:stuck"]["recoverable"], "migration retires the old recovery chain without accepting work")
        self.assertEqual(upgraded["queue"]["p:landed"]["done"], {"at": 5, "commit": "abc", "via": "landing"})
        self.assertEqual(upgraded["queue"]["p:awaiting"]["depends"], ["landed"])
        self.assertEqual(upgraded["queue"]["p:stuck"]["held_by"], "user")
        self.assertEqual(upgraded["tasks"]["p:garden-1"]["health_hash"], "health-hash")
        for record in upgraded["queue"].values():
            self.assertFalse({"status", "decompose", "report", "hash", "commit"} & set(record))

    def test_a_packets_work_report_is_stripped_and_kept_reachable(self):
        packet = self.packet()
        upgraded = upgrade_ledger.upgrade(self.ledger(packet), [self.project])
        stripped = upgraded["queue"]["p:tests-a"]["done"]["commit"]
        self.assertNotEqual(stripped, packet)
        files = git.run(self.repo, "ls-tree", "-r", "--name-only", stripped).split()
        self.assertEqual(files, ["test_a.txt"])
        self.assertEqual(git.head(self.repo, "refs/cointos/archive/packets/tests-a"), stripped)
        again = upgrade_ledger.upgrade(copy.deepcopy(upgraded), [self.project])
        self.assertEqual(again, upgraded, "a second run changes nothing")

    def test_an_idle_worker_branch_drops_its_report_and_finishes_again(self):
        worker = support.queued(self.project, "build")
        support.running(worker, "worker-1")
        (Path(worker["worktree"]) / ".work-report.md").write_text("Status: done\n")
        (Path(worker["worktree"]) / "build.c").write_text("int build;\n")
        support.commit(worker["worktree"])
        worker.update(status="review", receipt={"run": "worker-1", "disposition": "complete", "summary": "s",
                                                "evidence": {}, "at": 1}, agent=None)
        upgraded = upgrade_ledger.upgrade(json.loads(json.dumps(state.L)), [self.project])
        moved = upgraded["tasks"][worker["id"]]
        self.assertEqual((moved["status"], moved["receipt"]), ("waiting", None))
        self.assertFalse((Path(worker["worktree"]) / ".work-report.md").exists())
        self.assertTrue(git.clean(worker["worktree"]))


if __name__ == "__main__":
    unittest.main()
