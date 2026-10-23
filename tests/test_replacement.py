"""Real file ownership across replacement, validation and receipt publication."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from cointos import api, contracts, lifecycle, replacement, state
from tests.test_landing import Project


class LeaseTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def probe(self, shared=False):
        code = ('from pathlib import Path; from cointos.replacement import lease; import sys\n'
                'with lease(Path(sys.argv[1]), shared=sys.argv[2] == "True") as acquired:\n'
                ' sys.exit(0 if acquired else 1)\n')
        return subprocess.run([sys.executable, '-c', code, str(self.root), str(shared)], check=False).returncode

    def test_requests_coexist_and_exclude_replacement_across_processes(self):
        with replacement.lease(self.root, shared=True) as acquired:
            self.assertTrue(acquired)
            self.assertEqual(self.probe(shared=True), 0)
            self.assertEqual(self.probe(), 1)
        self.assertEqual(self.probe(), 0)

    def test_replacement_excludes_new_requests_and_releases_after_failure(self):
        with self.assertRaisesRegex(RuntimeError, 'copy failed'):
            with replacement.lease(self.root) as acquired:
                self.assertTrue(acquired)
                self.assertEqual(self.probe(shared=True), 1)
                raise RuntimeError('copy failed')
        self.assertEqual(self.probe(shared=True), 0)

    def test_nonregular_owner_fails_without_blocking_or_following_links(self):
        directory = self.root / 'state'
        directory.mkdir()
        owner = directory / 'replacement.lock'
        target = self.root / 'untouched'
        target.write_text('keep')
        owner.symlink_to(target)
        with self.assertRaises(OSError):
            with replacement.lease(self.root): self.fail('symlink acquired')
        self.assertEqual(target.read_text(), 'keep')
        owner.unlink()
        os.mkfifo(owner)
        with self.assertRaisesRegex(ValueError, 'regular file'):
            with replacement.lease(self.root): self.fail('FIFO acquired')


class RequestSettlementTests(Project):
    def setUp(self):
        super().setUp()
        self.runtime = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(api, 'ROOT', self.runtime))
        self.enterContext(patch.dict(state.ACTIVE, landings=0))

    def excluded(self, busy=True):
        with replacement.lease(self.runtime) as acquired:
            self.assertFalse(acquired)
        if busy:
            self.assertEqual(state.ACTIVE['landings'], 1)
            self.assertTrue(self.worker['validating'])

    def available(self):
        with replacement.lease(self.runtime) as acquired:
            self.assertTrue(acquired)
        self.assertEqual(state.ACTIVE['landings'], 0)
        self.assertFalse(self.worker.get('validating'))

    def test_finish_protects_validation_submission_save_and_publication(self):
        self.implement()
        submit = lifecycle.submit
        check = contracts.packet_check
        def checked(*args, **kwargs):
            self.excluded()
            return check(*args, **kwargs)
        def submitted(*args, **kwargs):
            self.excluded()
            return submit(*args, **kwargs)
        with patch.object(contracts, 'packet_check', side_effect=checked), \
                patch.object(lifecycle, 'submit', side_effect=submitted), \
                patch.object(api, 'save', side_effect=self.excluded), \
                patch.object(api.queues, 'publish', side_effect=self.excluded):
            self.assertEqual(self.finish()['disposition'], 'complete')
        self.available()

    def test_replacement_refuses_admission_before_validation_or_receipt(self):
        self.implement()
        with replacement.lease(self.runtime), patch.object(contracts, 'packet_check') as check:
            with self.assertRaisesRegex(api.ApiError, 'replacement in progress'):
                self.finish()
            check.assert_not_called()
            self.assertIsNone(self.worker.get('receipt'))
        self.available()

    def test_failed_validation_and_failed_publication_release_ownership(self):
        self.implement()
        with patch.object(contracts, 'packet_check', side_effect=ValueError('fixture rejection')):
            with self.assertRaisesRegex(api.ApiError, 'fixture rejection'):
                self.finish()
        self.available()
        with patch.object(api.queues, 'publish', side_effect=OSError('publication failed')):
            with self.assertRaisesRegex(OSError, 'publication failed'):
                self.finish()
        self.available()

    def test_third_refusal_settles_blocked_receipt_before_releasing(self):
        self.implement()
        with patch.object(contracts, 'packet_check', side_effect=ValueError('unchanged rejection')):
            for _ in range(2):
                with self.assertRaisesRegex(api.ApiError, 'unchanged rejection'):
                    self.finish()
                self.available()
            with patch.object(api.queues, 'publish', side_effect=self.excluded):
                self.assertEqual(self.finish()['disposition'], 'blocked')
        self.available()

    def test_landing_holds_ownership_through_publication(self):
        integration, candidate, submitted = self.landing()
        def published():
            self.excluded(busy=False)
            self.assertEqual(state.ACTIVE['landings'], 1)
            self.assertTrue(integration['validating'])
        with patch.object(api.queues, 'publish', side_effect=published):
            api.dispatch('land', {'caller': {'task': integration['id'], 'run': 'integrator-1'},
                                  'commit': candidate})
        self.available()
