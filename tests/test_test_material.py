"""Exact test material survives publication without replaying superseded edits."""
import copy
from pathlib import Path
import unittest
from unittest.mock import patch

from cointos import contracts, git, lifecycle, queues, runs, spawner, state
from tests import support


class TestMaterial(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self)
        self.repo = support.repository(self)
        (self.repo / 'tests').mkdir()
        (self.repo / 'tests/witness').write_text('base\n')
        (self.repo / 'tests/contracts.json').write_text('[]')
        (self.repo / 'product').write_text('old product')
        self.base = support.commit(self.repo)
        self.rules = {'manifest': 'tests/contracts.json', 'protected': ['tests/*'], 'non_code': []}
        git.run(self.repo, 'checkout', '-q', '-b', 'inputs')
        self.inputs = []
        for text in ('first\n', 'final\n'):
            (self.repo / 'tests/witness').write_text(text)
            self.inputs.append(support.commit(self.repo))
        git.run(self.repo, 'checkout', '-q', 'main')
        with contracts.combined(self.repo, self.base, self.inputs, self.rules, non_code='ours') as (_, composed):
            tree = git.head(self.repo, composed + '^{tree}')
        self.accepted = git.run(self.repo, 'commit-tree', tree, '-p', self.base, '-m', 'Publish exact files')

    def test_exact_composed_inputs_replay_without_ancestry_or_product_replacement(self):
        self.assertFalse(git.contains(self.repo, self.inputs[0], self.accepted))
        git.run(self.repo, 'checkout', '-q', '-b', 'accepted', self.accepted)
        (self.repo / 'product').write_text('new product')
        current = support.commit(self.repo)
        with contracts.combined(self.repo, current, self.inputs, self.rules, non_code='ours') as (path, result):
            self.assertEqual(result, current)
            self.assertEqual((Path(path) / 'product').read_text(), 'new product')
            self.assertEqual((Path(path) / 'tests/witness').read_text(), 'final\n')

    def test_changed_protected_tree_inputs_or_policy_cannot_reuse_material(self):
        for kind in ('content', 'mode', 'added', 'deleted', 'inputs', 'rules'):
            with self.subTest(kind=kind):
                git.run(self.repo, 'checkout', '-q', '--detach', self.accepted)
                inputs, rules = self.inputs, copy.deepcopy(self.rules)
                witness = self.repo / 'tests/witness'
                if kind == 'content': witness.write_text('altered\n')
                elif kind == 'mode': witness.chmod(0o755)
                elif kind == 'added': (self.repo / 'tests/extra').write_text('new test')
                elif kind == 'deleted': witness.unlink()
                elif kind == 'inputs': inputs = inputs[:1]
                elif kind == 'rules': rules['protected'].append('product')
                current = support.commit(self.repo) if kind not in ('inputs', 'rules') else self.accepted
                self.assertFalse(contracts.materialized(self.repo, current, inputs, rules))
                with self.assertRaises(contracts.CompositionError):
                    with contracts.combined(self.repo, current, inputs, rules, non_code='ours'):
                        pass

    def test_damaged_material_reference_cannot_attest_to_a_different_tree(self):
        reference = contracts.material_ref(self.repo, self.accepted, self.inputs, self.rules)
        git.run(self.repo, 'update-ref', reference, self.inputs[0])
        self.assertFalse(contracts.materialized(self.repo, self.accepted, self.inputs, self.rules))
        with self.assertRaises(contracts.CompositionError):
            with contracts.combined(self.repo, self.accepted, self.inputs, self.rules, non_code='ours'):
                pass

    def test_strict_non_code_composition_does_not_use_protected_tree_shortcut(self):
        with self.assertRaises(contracts.CompositionError):
            with contracts.combined(self.repo, self.accepted, self.inputs, self.rules):
                pass

    def test_legacy_verified_landing_bootstraps_material_without_tests_or_worker_edits(self):
        self.legacy_material()

    def test_background_retry_bootstraps_legacy_material_without_worker_edits(self):
        self.legacy_material(retry=True)

    def legacy_material(self, retry=False):
        git.run(self.repo, 'checkout', '-q', '-B', 'main', self.accepted)
        project = support.project(self, self.repo, test_policy=self.rules)
        worker = support.running(support.queued(project, 'next'), 'next-run')
        workspace = Path(worker['worktree'])
        (workspace / 'draft').write_text('preserve draft')
        before = git.head(workspace)
        for reference in git.run(self.repo, 'for-each-ref', '--format=%(refname)',
                                 'refs/cointos/test-material/').splitlines():
            git.run(self.repo, 'update-ref', '-d', reference)
        evidence = {'tests': self.inputs, 'commit': self.inputs[-1]}
        previous = {'place': 'p', 'status': 'done', 'kind': 'item', 'base_commit': self.base,
            'receipt': {'disposition': 'complete', 'evidence': evidence},
            'acceptance': {'via': 'landing', 'worker_commit': evidence['commit']}}
        state.L['tasks']['p:missing-history'] = {**previous, 'base_commit': '0' * 40}
        state.L['tasks']['p:previous'] = previous
        with patch.object(runs.landing, 'tests_of', return_value=self.inputs), \
                patch.object(contracts, '_run') as execute:
            if retry:
                lifecycle.refuse_dispatch(worker, 'preparation refused')
                lifecycle.release('next-run', 'refused')
                worker['composition_failure'] = {'main': self.accepted, 'packets': self.inputs}
                record = queues.records()[worker['record']]
                version = record['version']
                attempt = (queues.key(record), version, self.accepted, tuple(self.inputs))
                spawner.retry_composition(project, queues.key(record), attempt, self.rules,
                                          runs.material_baselines('p', self.inputs))
                self.assertEqual(record['version'], version + 1)
                self.assertNotIn('composition_failure', worker)
            else:
                runs.preflight_bindings(worker, project)
        execute.assert_not_called()
        self.assertTrue(contracts.materialized(self.repo, self.accepted, self.inputs, self.rules))
        self.assertEqual(git.head(workspace), before)
        self.assertEqual((workspace / 'draft').read_text(), 'preserve draft')
