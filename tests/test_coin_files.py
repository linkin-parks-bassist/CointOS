"""General file operations exercise real disk state without a Coin path sandbox."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cointos import coin, coin_files


class Filesystem(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def run_tool(self, name, path, **arguments):
        return coin.execute(name, {'path': str(path), **arguments})

    def test_create_write_read_search_copy_move_and_remove(self):
        folder = self.root / 'photos'
        self.run_tool('fs_mkdir', folder)
        source = folder / 'notes.txt'
        self.run_tool('fs_write', source, content='first\nsecond\nthird\n')
        read = self.run_tool('fs_read', source, start_line=2, lines=1)
        self.assertEqual(read['content'], 'second\n')
        self.assertEqual(read['total_lines'], 3)
        self.assertEqual(self.run_tool('fs_list', folder)['entries'][0]['name'], 'notes.txt')
        self.assertEqual(self.run_tool('fs_stat', source)['size'], source.stat().st_size)
        self.assertEqual(self.run_tool('fs_search', folder, glob='*.txt', text='second')['matches'],
                         [{'path': str(source), 'line': 2, 'text': 'second'}])
        copy = folder / 'copy.txt'
        self.run_tool('fs_copy', source, destination=str(copy))
        moved = folder / 'renamed.txt'
        self.run_tool('fs_move', copy, destination=str(moved))
        self.assertFalse(copy.exists())
        self.assertEqual(moved.read_bytes(), source.read_bytes())
        self.run_tool('fs_remove', moved)
        self.assertFalse(moved.exists())
        self.assertEqual(source.read_text(), 'first\nsecond\nthird\n')

    def test_album_listing_has_exact_visible_total_and_complete_pages(self):
        for number in range(294):
            (self.root / f'photo-{number:03}.jpg').touch()
        (self.root / '.knowledge').mkdir()
        names, offset = [], 0
        while offset is not None:
            page = self.run_tool('fs_list', self.root, offset=offset)
            self.assertEqual(page['total_entries'], 295)
            self.assertLessEqual(len(page['entries']), 20)
            names.extend(item['name'] for item in page['entries'])
            offset = page['next_offset']
        self.assertEqual(names, ['.knowledge', *[f'photo-{number:03}.jpg' for number in range(294)]])
        for args in ({'limit': 0}, {'limit': 21}, {'offset': -1}, {'offset': True}):
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.run_tool('fs_list', self.root, **args)

    def test_collisions_refuse_without_modifying_either_file(self):
        source, destination = self.root / 'source', self.root / 'destination'
        source.write_bytes(b'source')
        destination.write_bytes(b'keep')
        for name, args in [('fs_copy', {'destination': str(destination)}),
                           ('fs_move', {'destination': str(destination)}),
                           ('fs_write', {'content': 'replace'})]:
            with self.subTest(name=name), self.assertRaises(FileExistsError):
                self.run_tool(name, destination if name == 'fs_write' else source, **args)
            self.assertEqual(destination.read_bytes(), b'keep')
            self.assertEqual(source.read_bytes(), b'source')
        self.run_tool('fs_write', destination, content='authorised replacement', overwrite=True)
        self.assertEqual(destination.read_text(), 'authorised replacement')

    def test_bulk_transfer_handles_hundreds_without_extra_hashing(self):
        source, destination = self.root / 'inbox', self.root / 'pictures'
        source.mkdir()
        for number in range(294):
            (source / f'{number}.jpg').write_bytes(str(number).encode())
        with patch.object(coin_files.hashlib, 'file_digest', side_effect=AssertionError('unexpected verification')):
            result = self.run_tool('fs_transfer', source, destination=str(destination), operation='move')
        self.assertTrue(result['ok'])
        self.assertEqual(result['transferred'], 294)
        self.assertEqual(list(source.iterdir()), [])
        self.assertEqual((destination / '293.jpg').read_bytes(), b'293')

    def test_bulk_collision_keeps_both_and_continues_other_files(self):
        source, destination = self.root / 'inbox', self.root / 'pictures'
        source.mkdir(); destination.mkdir()
        (source / 'a.jpg').write_bytes(b'original')
        (source / 'b.jpg').write_bytes(b'next')
        (destination / 'a.jpg').write_bytes(b'keep')
        result = self.run_tool('fs_transfer', source, destination=str(destination), operation='move')
        self.assertFalse(result['ok'])
        self.assertEqual((result['failed'], result['transferred']), (1, 1))
        self.assertEqual((source / 'a.jpg').read_bytes(), b'original')
        self.assertEqual((destination / 'a.jpg').read_bytes(), b'keep')
        self.assertEqual((destination / 'b.jpg').read_bytes(), b'next')

    def test_bulk_transfer_has_no_knowledge_directory_gate(self):
        (self.root / 'a.jpg').write_bytes(b'safe')
        (self.root / '.knowledge').mkdir()
        destination = self.root / 'pictures'
        result = self.run_tool('fs_transfer', self.root, destination=str(destination), operation='move')
        self.assertTrue(result['ok'])
        self.assertEqual((destination / 'a.jpg').read_bytes(), b'safe')

    def test_explicit_hash_verification_preserves_source_on_bad_copy(self):
        source, destination = self.root / 'inbox', self.root / 'pictures'
        source.mkdir()
        (source / 'a.jpg').write_bytes(b'original')
        execute = coin_files.execute
        def corrupt(name, arguments):
            if name == 'fs_copy':
                Path(arguments['destination']).write_bytes(b'corrupted')
                return {'ok': True}
            return execute(name, arguments)
        with patch.object(coin_files, 'execute', side_effect=corrupt):
            result = self.run_tool('fs_transfer', source, destination=str(destination), operation='move', verification='hash')
        self.assertFalse(result['ok'])
        self.assertEqual(result['failed'], 1)
        self.assertEqual((source / 'a.jpg').read_bytes(), b'original')

    def test_write_failure_keeps_existing_bytes_and_cleans_temporary(self):
        target = self.root / 'notes'
        target.write_bytes(b'keep')
        def broken(stream):
            stream.write(b'incomplete')
            raise OSError('disk failure')
        with self.assertRaises(OSError):
            coin_files.publish(target, broken, overwrite=True)
        self.assertEqual(target.read_bytes(), b'keep')
        self.assertEqual(list(self.root.iterdir()), [target])

    def test_recursive_copy_move_and_explicit_removal(self):
        source = self.root / 'source'
        (source / 'sub').mkdir(parents=True)
        (source / 'sub/a').write_bytes(b'picture')
        copy, moved = self.root / 'copy', self.root / 'moved'
        self.run_tool('fs_copy', source, destination=str(copy))
        self.run_tool('fs_move', copy, destination=str(moved))
        self.assertFalse(copy.exists())
        self.assertEqual((moved / 'sub/a').read_bytes(), b'picture')
        with self.assertRaises(OSError):
            self.run_tool('fs_remove', moved)
        self.run_tool('fs_remove', moved, recursive=True)
        self.assertFalse(moved.exists())

    def test_local_paths_and_knowledge_aliases_have_no_coin_gate(self):
        knowledge = self.root / '.knowledge'
        knowledge.mkdir()
        answer = knowledge / 'answer.md'
        answer.write_text('local data')
        alias = self.root / 'alias'
        alias.symlink_to(knowledge, target_is_directory=True)
        for actor in ('cointos-coin', 'ordinary-agent'):
            with patch.dict('os.environ', KT_ACTOR=actor):
                self.assertEqual(self.run_tool('fs_read', alias / 'answer.md')['content'], 'local data')
        self.run_tool('fs_write', knowledge / 'new.md', content='new data')
        self.assertEqual(len(self.run_tool('fs_search', knowledge)['matches']), 2)
        self.assertIn('.knowledge', [e['name'] for e in self.run_tool('fs_list', self.root)['entries']])
        destination = self.root / 'copy'
        self.run_tool('fs_copy', knowledge, destination=str(destination))
        self.assertEqual((destination / 'answer.md').read_text(), 'local data')
        self.run_tool('fs_remove', destination, recursive=True)
        self.assertFalse(destination.exists())

    def test_command_runs_in_requested_directory_and_reports_real_failure(self):
        result = coin.execute('run_command', {'command': "printf 'saved' > note; cat note; printf 'problem' >&2; exit 7", 'cwd': str(self.root)})
        self.assertFalse(result['ok'])
        self.assertEqual(result['exit_code'], 7)
        self.assertEqual(result['stdout'], 'saved')
        self.assertEqual(result['stderr'], 'problem')
        self.assertEqual((self.root / 'note').read_text(), 'saved')
