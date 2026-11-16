"""The Coin viewer's journal: what a turn publishes, and how a window follows it."""
import json
from pathlib import Path
import stat
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from cointos import coin, coin_mirror


class ViewerLifetime(unittest.TestCase):
    def test_closed_windows_release_their_live_subscription(self):
        for _ in range(3):
            opened, closed, cleanup = threading.Event(), threading.Event(), threading.Event()

            def states():
                try:
                    opened.set()
                    while not cleanup.wait(.01):
                        yield {'coin': {'busy': False}}
                finally:
                    closed.set()

            self.addCleanup(cleanup.set)
            mirror = Mock()
            window = Mock()
            window.poll.return_value = 0

            def launch(*args, **kwargs):
                self.assertTrue(opened.wait(1))
                return window

            with patch.object(coin_mirror, 'Mirror', return_value=mirror), \
                    patch('cointos.config.load', return_value={
                        'opencode_v2': False, 'timeouts': {'api_seconds': 1}}), \
                    patch.object(coin_mirror.subprocess, 'Popen', side_effect=launch):
                coin_mirror.show(Path('/unused'), Path('/unused'), 'opencode', states())
            self.assertTrue(closed.wait(.5), 'closed viewer retained its live-update subscription')
            mirror.stop.assert_called_once()


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

    def test_private_coin_does_not_create_a_turn_transcript(self):
        with patch.dict(coin.SETTINGS, retain_diagnostics=False):
            coin.journal({'kind': 'user', 'text': 'synthetic private canary'})
        self.assertFalse(self.path.exists())

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
                   {'role': 'assistant', 'content': 'Checked.'},
                   {'role': 'assistant', 'tool_calls': [
                       {'id': 'end', 'function': {'name': 'done', 'arguments': '{}'}}]}]
        history = patch.object(coin, 'history_path', return_value=self.state / 'conversation.jsonl')
        with history, patch.object(coin, 'complete', side_effect=replies), patch.object(coin, 'send'), \
                patch.object(coin, 'report'), patch.object(coin, 'execute', return_value={'ok': True}):
            coin.turn('token', 7, 70, ['hello'], lambda: [], None)
        entries, _ = coin_mirror.journal_lines(self.path, 0)
        self.assertEqual([e['kind'] for e in entries], ['user', 'assistant', 'tool', 'assistant', 'assistant', 'tool'])
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


class LiveWords(unittest.TestCase):
    """Words still being generated keep reasoning in the thinking block, not the reply."""
    def setUp(self):
        self.mirror = coin_mirror.Mirror(Path('/nonexistent'), 'opencode')
        self.mirror.session, self.mirror.message = 'ses', 'msg'
        self.parts, self.deleted = {}, []

        def call(path, body=None, method=None):
            identifier = path.rsplit('/', 1)[-1]
            if method == 'PATCH':
                self.parts[identifier] = body
            elif method == 'DELETE':
                self.deleted.append(identifier)
                self.parts.pop(identifier, None)
        self.mirror.call = call

    def kinds(self):
        return {(p['type'], p['text']) for p in self.parts.values()}

    def test_live_reasoning_is_shown_as_reasoning_and_only_words_as_the_reply(self):
        self.mirror.words('thinking about it', '')
        self.assertEqual(self.kinds(), {('reasoning', 'thinking about it')})
        self.mirror.words('thinking about it more', 'Hello')
        self.assertEqual(self.kinds(), {('reasoning', 'thinking about it more'), ('text', 'Hello')})

    def test_the_finished_step_replaces_the_live_parts_in_place(self):
        self.mirror.words('draft thoughts', 'draft words')
        before = set(self.parts)
        self.mirror.feed({'kind': 'assistant', 'reasoning': 'final thoughts', 'content': 'final words'})
        self.assertEqual(set(self.parts), before)
        self.assertEqual(self.kinds(), {('reasoning', 'final thoughts'), ('text', 'final words')})

    def test_a_step_without_reasoning_removes_the_live_reasoning(self):
        self.mirror.words('draft thoughts', '')
        self.mirror.feed({'kind': 'assistant', 'reasoning': '', 'content': 'words'})
        self.assertEqual(self.kinds(), {('text', 'words')})

    def test_a_stale_live_record_does_not_reappear_after_its_step(self):
        self.mirror.feed({'kind': 'assistant', 'reasoning': 'all the thoughts', 'content': ''})
        count = len(self.parts)
        self.mirror.words('the thoughts', '')  # the daemon's tail of the step just finished
        self.assertEqual(len(self.parts), count)
        self.mirror.words('a new thought', '')
        self.assertEqual(len(self.parts), count + 1)
