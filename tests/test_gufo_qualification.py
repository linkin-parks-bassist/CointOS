"""The experimental parking transaction must preserve cache bytes through recovery."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('gufo_qualification', Path(__file__).resolve().parents[1]/'patches/gufo/qualify.py')
qualification = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qualification)


class CacheParking(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.parking = qualification.Run(self.root/'evidence', {'port': 1, 'snapshots': str(self.root/'ram')}, 'q', {})
        self.source = self.root/'ram'/'cached.bin'
        self.source.parent.mkdir()
        self.source.write_bytes(b'native attention and recurrent state\0\xff'*1024)
        self.source.chmod(0o644)
        self.original = self.source.read_bytes()

    def test_offload_and_recovered_process_restore_exact_bytes(self):
        entry = self.parking.offload(self.source, 'caches')
        self.assertFalse(self.source.exists())
        self.assertTrue(entry['ready'])
        recovered = qualification.Run(self.root/'evidence')
        recovered.restore_files('caches')
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(self.source.stat().st_mode & 0o777, 0o644)
        recovered.restore_files('caches')  # Recovery is idempotent.
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_crash_between_unlink_and_final_journal_stamp_is_recoverable(self):
        entry = self.parking.offload(self.source, 'caches')
        entry.pop('offloaded')
        self.parking.save()
        qualification.Run(self.root/'evidence').restore_files('caches')
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_corrupt_backup_is_rejected_before_restoring_live_cache(self):
        entry = self.parking.offload(self.source, 'caches')
        Path(entry['backup']).write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            qualification.Run(self.root/'evidence').restore_files('caches')
        self.assertFalse(self.source.exists())

    def test_failed_copy_never_removes_original(self):
        backup = self.root/'bad-copy.bin'
        with self.assertRaisesRegex(ValueError, 'checksum'):
            qualification.copy_checked(self.source, backup, '0'*64)
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertFalse(backup.exists())

    def test_completed_recovery_cannot_rewind_a_live_model(self):
        self.parking.journal['restored'] = True
        self.parking.save()
        with patch.object(qualification.gufo, 'kill') as kill, patch.object(qualification, 'systemctl') as systemctl:
            qualification.Run(self.root/'evidence').recover()
        kill.assert_not_called()
        systemctl.assert_not_called()

    def test_native_warm_restore_and_pressure_settle_precede_adoption(self):
        run = self.parking
        run.config.update(memory={'reserve_gb': 24, 'max_psi': 1.5},
                          timeouts={'model_launch_seconds': 60}, tick_seconds=1)
        run.journal.update(original_gufo={'identity': 'native-dflash'}, drained_ledger={
            'snapshots': {'small': {'model': 'q', 'tier': 'memory', 'bytes': 1, 'tokens': 10},
                          'large': {'model': 'q', 'tier': 'memory', 'bytes': 2, 'tokens': 20}}})
        order = []
        with patch.object(qualification.gufo, 'launch', side_effect=lambda *a: order.append('launch')), \
             patch.object(qualification.gufo, '_call', return_value={'identity': 'native-dflash'}), \
             patch.object(qualification.gufo, 'restore', side_effect=lambda *a: order.append(('restore', a[-1])) or True), \
             patch.object(qualification.memory, 'measure', side_effect=[
                 {'available_gb': 50, 'psi': 5}, {'available_gb': 50, 'psi': 0.1}]), \
             patch.object(qualification.time, 'sleep', side_effect=lambda n: order.append('settle')):
            run.prepare_production()
        self.assertEqual(order, ['launch', ('restore', 'large'), 'settle'])
        self.assertEqual(run.journal['recovery_memory']['psi'], 0.1)

    def test_freeze_and_thaw_wait_for_kernel_acknowledgement(self):
        group=self.root/'cgroup';group.mkdir()
        (group/'cgroup.freeze').write_text('0')
        (group/'cgroup.events').write_text('populated 1\nfrozen 0\n')
        def acknowledge(_):
            wanted=(group/'cgroup.freeze').read_text()
            (group/'cgroup.events').write_text('populated 1\nfrozen '+wanted+'\n')
        with patch.object(qualification,'cgroup_path',return_value=group), \
             patch.object(qualification.time,'sleep',side_effect=acknowledge), \
             patch.object(qualification.subprocess,'run') as command:
            qualification.systemctl('freeze','cointos-coin.service')
            self.assertEqual((group/'cgroup.freeze').read_text(),'1')
            qualification.systemctl('thaw','cointos-coin.service')
            self.assertEqual((group/'cgroup.freeze').read_text(),'0')
        command.assert_not_called()

    def test_service_reports_kernel_freeze_state_when_manager_is_stale(self):
        group=self.root/'cgroup';group.mkdir()
        (group/'cgroup.events').write_text('populated 1\nfrozen 0\n')
        with patch.object(qualification,'cgroup_path',return_value=group), \
             patch.object(qualification.subprocess,'check_output',return_value=
                          'ActiveState=active\nMainPID=123\nFreezerState=thawing\nControlGroup=/unit\n'):
            self.assertEqual(qualification.service('cointos-coin.service')['FreezerState'],'running')
