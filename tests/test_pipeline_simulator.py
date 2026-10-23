"""Safety/progress assertions across the simulator's declared fault matrix."""
import unittest
import itertools

from tests.pipeline_simulator import Simulation, run


class FaultCampaign(unittest.TestCase):
    def test_project_qualified_api_dependencies_share_the_local_graph(self):
        result = run(1, 63031, ['qualified_dependencies'])
        self.assertEqual(result['failures'], [])
        self.assertEqual(result['outcomes'], {'qualified-local-dependencies-ready': 1})

    def test_existing_qualified_ledger_migration_preserves_authority_and_graph(self):
        for seed in (63041, 63042, 63043):
            with self.subTest(seed=seed):
                result = run(1, seed, ['migrate_qualified_dependencies'])
                self.assertEqual(result['failures'], [])
                self.assertEqual(result['outcomes'], {'qualified-ledger-migrated-with-authority-retained': 1})

    def test_every_ordered_pair_of_landing_faults(self):
        result = run(seed=23119, pairs=True)
        self.assertEqual(result['cases'], 930)
        self.assertEqual(result['failures'], [])

    def test_every_fault_and_seeded_compound_schedules(self):
        result = run(2000, 391702)
        self.assertEqual(result['failures'], [])
        self.assertGreater(result['outcomes'].get('landed', 0), 0)
        self.assertGreater(result['outcomes'].get('direct-controller-repair', 0), 0)

    def test_published_work_settles_without_retired_artifacts(self):
        result = run(1, 198, ['dirty_main', 'retired_after_publish', 'duplicate'])
        self.assertEqual(result['failures'], [])
        self.assertEqual(result['outcomes'], {'landed': 1})

    def test_failure_has_no_authority_after_kill(self):
        result = run(1, 198, ['failed_test_after_kill'])
        self.assertEqual(result['failures'], [])
        self.assertEqual(result['outcomes'], {'refused-control-race': 1})

    def test_daemon_replacement_adopts_or_readmits_without_losing_work(self):
        for fault in (f for f in Simulation.faults if f.startswith('adopt_')):
            with self.subTest(fault=fault):
                result = run(1, 62711, [fault])
                self.assertEqual(result['failures'], [])
                expected = ('adopted-and-landed' if fault in (
                    'adopt_live_worker', 'adopt_live_integrator', 'adopt_receipted_worker') else 'readmitted-and-landed')
                if fault == 'adopt_published_exhausted':
                    expected = 'published-intent-before-budget'
                self.assertEqual(result['outcomes'], {expected: 1})

    def test_resumed_review_waits_for_its_project_then_drains(self):
        result = run(1, 62721, ['integration_resume_race'])
        self.assertEqual(result['failures'], [])
        self.assertEqual(result['outcomes'], {'serialized-resumed-review': 1})

    def test_automatic_repairs_are_bounded_and_hand_useful_work_back(self):
        for fault in (f for f in Simulation.faults if f.startswith('repair_')):
            with self.subTest(fault=fault):
                result = run(1, 62781, [fault])
                self.assertEqual(result['failures'], [])
                expected = {'repair_stale_before_admission': 'obsolete-repair-withdrawn',
                            'repair_superseded_periodic': 'obsolete-periodic-repair-withdrawn',
                            'repair_prerequisite_arrived': 'same-version-dependency-repair-drained',
                            'repair_obstruction_cleared': 'cleared-obstruction-progresses-without-repair',
                            'repair_pending_graph_regression': 'regressed-pending-repair-drained',
                            'repair_human_cancelled': 'human-repair-cancellation-retained',
                            'repair_live_superseded': 'live-superseded-repair-closed',
                            'repair_newer_failed': 'unresolved-newer-maintenance-refused',
                            'repair_newer_pending': 'unresolved-newer-maintenance-refused',
                            'repair_no_recursive_operator': 'repair-bounded-without-recursion'}.get(
                                fault, 'repair-handback-and-landed')
                self.assertEqual(result['outcomes'], {expected: 1})

    def test_queue_and_maintenance_share_task_identity_namespace(self):
        expected = {'namespace_maintenance_first': 'live-maintenance-identity-preserved',
                    'namespace_queue_first': 'queue-namespace-safe-and-landed',
                    'namespace_cancelled_record': 'cancelled-task-identity-preserved'}
        for fault, outcome in expected.items():
            with self.subTest(fault=fault):
                result = run(1, 62761, [fault])
                self.assertEqual(result['failures'], [])
                self.assertEqual(result['outcomes'], {outcome: 1})

    def test_unit_observation_requires_confirmed_death_and_checked_receipt(self):
        for fault in (f for f in Simulation.faults if f.startswith('observer_')):
            with self.subTest(fault=fault):
                result = run(1, 62771, [fault])
                self.assertEqual(result['failures'], [])
                expected = ('observed-receipt-and-landed' if fault == 'observer_query_oserror'
                            else 'observed-terminal-without-receipt')
                self.assertEqual(result['outcomes'], {expected: 1})

    def test_run_artifact_publication_is_atomic_under_observation_and_interruption(self):
        for fault in (f for f in Simulation.faults if f.startswith('artifact_')):
            with self.subTest(fault=fault):
                result = run(1, 62791, [fault])
                self.assertEqual(result['failures'], [])
                self.assertEqual(result['outcomes'], {'atomic-run-artifacts-observed': 1})

    def test_producer_metadata_failure_still_cleans_server_group(self):
        result = run(1, 62811, ['producer_metadata_failure'])
        self.assertEqual(result['failures'], [])
        self.assertEqual(result['outcomes'], {'producer-error-cleaned': 1})

    def test_red_contract_requires_current_independent_review(self):
        expected = {'hidden_red_review': 'hidden-reviewed-without-publication',
                    'hidden_red_main': 'hidden-reviewed-without-publication',
                    'hidden_green_review': 'green-contract-reviewed-and-published',
                    'hidden_rejected_review': 'hidden-reviewed-without-publication',
                    'hidden_blocked_review': 'hidden-blocked-review-to-controller',
                    'hidden_validation_races': 'hidden-invalid-review-refused',
                    'hidden_save_replacement': 'hidden-save-replacement-recovered'}
        for fault, outcome in expected.items():
            with self.subTest(fault=fault):
                result = run(1, 62821, [fault])
                self.assertEqual(result['failures'], [])
                self.assertEqual(result['outcomes'], {outcome: 1})

    def test_admission_identity_and_failed_start_preserve_ownership(self):
        for fault in (f for f in Simulation.faults if f.startswith('admission_')):
            with self.subTest(fault=fault):
                result = run(1, 62831, [fault])
                self.assertEqual(result['failures'], [])
                expected = ('historical-run-artifacts-preserved' if fault == 'admission_launch_artifacts'
                            else 'unique-admission-and-landed')
                self.assertEqual(result['outcomes'], {expected: 1})

    def test_authority_storage_refuses_erasure_then_corrected_inputs_drain(self):
        for fault in (f for f in Simulation.faults if f.startswith('authority_')):
            with self.subTest(fault=fault):
                result = run(1, 62861, [fault])
                self.assertEqual(result['failures'], [])
                self.assertEqual(result['outcomes'], {'authority-corrected-and-landed': 1})
        result = run(1, 62864, ['authority_ledger', 'authority_enrollment', 'authority_namespace'])
        self.assertEqual(result['failures'], [])
        for pair in itertools.combinations((f for f in Simulation.faults if f.startswith('authority_')), 2):
            with self.subTest(pair=pair):
                result = run(1, 62865, list(pair))
                self.assertEqual(result['failures'], [])
