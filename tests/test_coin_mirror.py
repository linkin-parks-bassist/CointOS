"""The Coin viewer's journal: what a turn publishes, and how a window follows it."""
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from cointos import coin, coin_mirror


class Journal(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.state = Path(directory.name)
        self.enterContext(patch.object(coin, 'COIN_STATE', self.state))
        self.path = self.state / 'turns.jsonl'

    def test_entries_are_private_and_followed_from_a_position(self):
        coin.journal({'kind': 'user', 'text': 'one'})
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        entries, position = coin_mirror.journal_lines(self.path, 0)
        self.assertEqual([e['text'] for e in entries], ['one'])
        coin.journal({'kind': 'user', 'text': 'two'})
        entries, position = coin_mirror.journal_lines(self.path, position)
        self.assertEqual([e['text'] for e in entries], ['two'])
        self.assertEqual(coin_mirror.journal_lines(self.path, position), ([], position))

    def test_partial_and_damaged_lines_do_not_stop_the_view(self):
        self.path.write_bytes(b'not json\n{"kind": "user"}\n{"unfinished":')
        entries, position = coin_mirror.journal_lines(self.path, 0)
        self.assertEqual(entries, [{'kind': 'user'}])
        with self.path.open('ab') as stream:
            stream.write(b' 1}\n')
        self.assertEqual(coin_mirror.journal_lines(self.path, position)[0], [{'unfinished': 1}])

    def test_rotation_keeps_whole_recent_entries_and_a_window_restarts_from_the_top(self):
        with patch.dict(coin.SETTINGS, journal_bytes=400):
            for number in range(40):
                coin.journal({'kind': 'user', 'text': str(number)})
        self.assertLessEqual(self.path.stat().st_size, 500)
        entries, _ = coin_mirror.journal_lines(self.path, 0)
        self.assertEqual(entries[-1]['text'], '39')
        self.assertEqual(coin_mirror.journal_lines(self.path, 10 ** 6)[0], entries)

    def test_a_failed_journal_never_stops_a_turn(self):
        self.path.mkdir()
        coin.journal({'kind': 'user', 'text': 'still fine'})

    def test_a_turn_publishes_words_and_tool_activity(self):
        replies = [{'role': 'assistant', 'content': '', 'reasoning_content': 'thinking', 'tool_calls': [
                       {'id': 'c', 'type': 'function', 'function': {'name': 'send', 'arguments': '{"message": "On it"}'}}]},
                   {'role': 'assistant', 'content': 'Checked.'}]
        history = patch.object(coin, 'history_path', return_value=self.state / 'conversation.jsonl')
        with history, patch.object(coin, 'complete', side_effect=replies), patch.object(coin, 'send'), \
                patch.object(coin, 'report'), patch.object(coin, 'execute', return_value={'ok': True}):
            coin.turn('token', 7, 70, ['hello'], lambda: [], None)
        entries, _ = coin_mirror.journal_lines(self.path, 0)
        self.assertEqual([e['kind'] for e in entries], ['user', 'assistant', 'tool', 'assistant'])
        self.assertEqual(entries[1]['reasoning'], 'thinking')
        self.assertEqual(entries[2]['name'], 'send')
        self.assertEqual(entries[2]['input'], {'message': 'On it'})
        self.assertEqual(json.loads(entries[2]['output']), {'ok': True, 'output': 'sent'})
        self.assertEqual(entries[3]['content'], 'Checked.')


class Window(unittest.TestCase):
    def test_window_uses_the_users_settings_and_only_the_server_is_isolated(self):
        mirror = coin_mirror.Mirror(Path('/nonexistent'), 'opencode')
        mirror.password = 'secret'
        with patch.dict(coin_mirror.os.environ, {'XDG_STATE_HOME': '/home/user/state'}):
            environment = mirror.window_environment()
        self.assertEqual(environment['XDG_STATE_HOME'], '/home/user/state')
        self.assertEqual(environment['OPENCODE_SERVER_PASSWORD'], 'secret')


class StandInReply(unittest.TestCase):
    def test_only_mirrored_text_is_answered_silently(self):
        self.assertEqual(coin_mirror._text({'content': [{'type': 'text', 'text': 'a'}, {'type': 'text', 'text': 'b'}]}), 'ab')
        self.assertEqual(coin_mirror._text({'content': 'plain'}), 'plain')
