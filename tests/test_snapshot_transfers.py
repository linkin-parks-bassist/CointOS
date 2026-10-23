"""Real-file recovery after the copying process dies at each publication boundary."""
import errno
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cointos import backend_native as native, snapshots, snapshot_cleanup, state
from tests import support


class InterruptedTransfers(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = {'models': {'q': {'backend': 'gufo'}, 'l': {'backend': 'llama'}},
                       'snapshots': str(self.root / 'ram'), 'disk_snapshots': str(self.root / 'disk')}
        self.data = bytes(range(256)) * 1024

    def places(self, model, name):
        suffix = Path('gufo') if model == 'q' else Path()
        paths = [Path(self.config[key]) / suffix / (name + '.bin')
                 for key in ('snapshots', 'disk_snapshots')]
        for p in paths:
            p.parent.mkdir(parents=True, exist_ok=True)
        return paths

    def crash(self, model, direction, boundary, name):
        ram, disk = self.places(model, name)
        source, destination = (ram, disk) if direction == 'spill' else (disk, ram)
        source.write_bytes(self.data)
        pid = os.fork()
        if pid == 0:
            unlink = os.unlink
            def partial(src, dst, *args, **kwargs):
                Path(dst).write_bytes(Path(src).read_bytes()[:len(self.data)//2])
                os._exit(137)
            def before_unlink(path, *args, **kwargs):
                if Path(path) == source:
                    os._exit(137)
                return unlink(path, *args, **kwargs)
            try:
                # Force move's cross-filesystem path even in this temporary tree.
                with patch('os.rename', side_effect=OSError(errno.EXDEV, 'cross-device')):
                    if boundary == 'partial':
                        with patch('shutil.copyfile', side_effect=partial):
                            getattr(native, direction)(self.config, name)
                    elif boundary == 'copied':
                        with patch('os.unlink', side_effect=before_unlink), \
                                patch('os.remove', side_effect=before_unlink):
                            getattr(native, direction)(self.config, name)
                    else:
                        getattr(native, direction)(self.config, name)
                        os._exit(137)  # copied and source removed, before ledger commit
            finally:
                os._exit(1)
        _, status = os.waitpid(pid, 0)
        self.assertEqual(os.waitstatus_to_exitcode(status), 137)
        return ram, disk, source, destination

    def test_process_death_at_each_copy_boundary_preserves_complete_bytes(self):
        for model in ('q', 'l'):
            for direction in ('spill', 'unspill'):
                for boundary in ('partial', 'copied', 'removed'):
                    with self.subTest(model=model, direction=direction, boundary=boundary):
                        name = model + '-' + direction + '-' + boundary
                        ram, disk, source, destination = self.crash(model, direction, boundary, name)
                        tier = native.recover_transfer(self.config, model, name, len(self.data))
                        expected = source if boundary == 'partial' else (
                            ram if boundary == 'copied' else destination)
                        self.assertEqual(tier, 'memory' if expected == ram else 'disk')
                        self.assertEqual(expected.read_bytes(), self.data)
                        self.assertFalse((disk if expected == ram else ram).exists())

    def test_partial_missing_symlink_and_wrong_size_files_do_not_qualify(self):
        for model in ('q', 'l'):
            ram, disk = self.places(model, model)
            target = self.root / (model + '-foreign')
            target.write_bytes(self.data)
            ram.symlink_to(target)
            disk.write_bytes(self.data[:-1])
            self.assertIsNone(native.recover_transfer(self.config, model, model, len(self.data)))
            self.assertEqual(target.read_bytes(), self.data)
            ram.unlink(); disk.unlink()
            self.assertIsNone(native.recover_transfer(self.config, model, model, len(self.data)))
        self.assertIsNone(native.recover_transfer(self.config, 'absent', 'x', 1))

    def test_backend_choice_does_not_recover_another_formats_same_named_file(self):
        ram, _ = self.places('q', 'same')
        ram.write_bytes(self.data)
        self.assertIsNone(native.recover_transfer(self.config, 'l', 'same', len(self.data)))
        self.assertTrue(ram.exists())

    def test_startup_keeps_recovered_tier_but_never_resurrects_discarded_or_retired_owners(self):
        for owner, discard, kept in (('coin/a', False, True), ('coin/a', True, False), ('gone', False, False)):
            with self.subTest(owner=owner, discard=discard):
                ram, disk = self.places('q', 'startup')
                ram.write_bytes(self.data)
                disk.write_bytes(b'partial')
                state.L['snapshots'] = {'startup': {'model': 'q', 'owner': owner, 'tier': 'moving',
                                                   'discard': discard, 'bytes': len(self.data)}}
                with patch.dict(state.CONFIG, self.config):
                    snapshots.recover_transfers()
                    snapshots.forget_untracked()
                    snapshot_cleanup.drain('memory')
                    snapshot_cleanup.drain('disk')
                self.assertEqual('startup' in state.L['snapshots'], kept)
                self.assertEqual(ram.exists(), kept)
                self.assertFalse(disk.exists())
                if kept:
                    self.assertEqual(state.L['snapshots']['startup']['tier'], 'memory')
                    self.assertEqual(ram.read_bytes(), self.data)

