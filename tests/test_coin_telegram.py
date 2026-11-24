"""Telegram wire, tool discovery, durable delivery and conversation boundaries."""
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from cointos import coin, coin_telegram as tg, coin_input
from tests import test_coin as coin_test
from tests.test_coin import assistant, call


class Tools(unittest.TestCase):
    def test_catalog_and_discovery(self):
        self.assertGreater(len(tg.METHODS), 150)
        self.assertEqual(tg.METHODS['getMe'], {})
        for method, fields in tg.METHODS.items():
            declaration = tg.declaration(method)['function']
            self.assertEqual(declaration['name'], 'telegram_' + method)
            self.assertEqual(set(declaration['parameters']['properties']), set(fields))
            self.assertLessEqual(len(declaration['name']), 64)
        found, declarations = tg.discover({'query': 'sticker'})
        self.assertIn('sendSticker', found['methods'])
        self.assertTrue(declarations)
        self.assertEqual(tg.discover({'query': 'album'})[0]['methods'], ['sendMediaGroup'])
        result, _ = tg.discover({'type_name': 'InputMediaPhoto'})
        self.assertIn('media', result['fields'])
        for method in tg.CATALOG['excluded']:
            with self.assertRaises(ValueError):
                tg.prepare('telegram_' + method, {}, 7, 70)
        with self.assertRaises(ValueError):
            tg.discover({'names': ['missing']})

    def test_defaults_explicit_destinations_and_validation(self):
        self.assertEqual(tg.prepare('telegram_sendPhoto', {'photo': 'id'}, 7, 70),
                         ('sendPhoto', {'chat_id': 70, 'photo': 'id'}))
        self.assertEqual(tg.prepare('telegram_getChatMember', {}, 7, 70)[1], {'chat_id': 70, 'user_id': 7})
        self.assertEqual(tg.prepare('telegram_sendPhoto', {'photo': 'id', 'chat_id': '@channel'}, 7, 70)[1]['chat_id'], '@channel')
        inline = tg.prepare('telegram_editMessageText', {'inline_message_id': 'inline', 'text': 'updated'}, 7, 70)[1]
        self.assertNotIn('chat_id', inline)
        for args in ({}, {'photo': 'id', 'token': 'secret'}):
            with self.assertRaises(ValueError):
                tg.prepare('telegram_sendPhoto', args, 7, 70)

    def test_json_transport_redacts_token_fields_and_nested_strings(self):
        def endpoint(req, timeout):
            self.assertEqual(req.headers['Content-type'], 'application/json')
            self.assertEqual(json.load(req.data), {'chat_id': 70, 'photo': 'id'})
            return io.BytesIO(json.dumps({'ok': True, 'result': {'message_id': 1, 'token': 'other', 'text': 'secret'}}).encode())
        with patch.object(tg.urllib.request, 'urlopen', side_effect=endpoint):
            result = tg.request('secret', 'sendPhoto', {'chat_id': 70, 'photo': 'id'}, 3)
        self.assertEqual(result['result'], {'message_id': 1, 'token': '[redacted]', 'text': '[redacted]'})

    def test_multipart_nested_album_and_thumbnail_preserves_bytes_and_names(self):
        with tempfile.TemporaryDirectory() as directory:
            photo = Path(directory) / 'my photo.png'
            photo.write_bytes(b'\x89PNG\x00data')
            doc = Path(directory) / 'report.pdf'
            doc.write_bytes(b'%PDF-test')
            def endpoint(req, timeout):
                data = req.data.read()
                self.assertEqual(int(req.headers['Content-length']), len(data))
                self.assertIn(b'attach://upload0', data)
                self.assertIn(b'attach://upload1', data)
                self.assertIn(b'filename="my photo.png"', data)
                self.assertIn(photo.read_bytes(), data)
                self.assertIn(doc.read_bytes(), data)
                self.assertIn(b'false', data)
                return io.BytesIO(b'{"ok":true,"result":[]}')
            with patch.object(tg.urllib.request, 'urlopen', side_effect=endpoint):
                result = tg.request('secret', 'sendMediaGroup', {'chat_id': 70, 'disable_notification': False,
                    'media': [{'type': 'photo', 'media': {'path': str(photo)}},
                              {'type': 'document', 'media': {'path': str(doc)}}]}, 3)
            self.assertTrue(result['ok'])
            with self.assertRaises(ValueError):
                tg.request('secret', 'sendPhoto', {'photo': {'path': 'relative.png'}}, 3)

    def test_refusal_rate_limit_and_ambiguous_network_failure_are_not_retried(self):
        error = urllib.error.HTTPError('https://example/secret', 429, 'secret', {},
            io.BytesIO(b'{"description":"slow secret","parameters":{"retry_after":9}}'))
        with patch.object(tg.urllib.request, 'urlopen', side_effect=error) as sender:
            result = tg.request('secret', 'sendPhoto', {'photo': 'id'}, 3)
        self.assertFalse(result['ok'])
        self.assertEqual(result['parameters']['retry_after'], 9)
        self.assertNotIn('secret', result['error'])
        self.assertEqual(sender.call_count, 1)
        with patch.object(tg.urllib.request, 'urlopen', side_effect=OSError('secret')):
            result = tg.request('secret', 'sendPhoto', {'photo': 'id'}, 3)
        self.assertIn('unknown', result['error'])
        self.assertNotIn('secret', result['error'])

    def test_real_http_multipart_wire(self):
        import http.server
        import threading
        import urllib.request
        received = []
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                received.append((self.headers['Content-Type'], self.rfile.read(int(self.headers['Content-Length']))))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"ok":true,"result":{"message_id":123}}')
            def log_message(self, *args):
                pass
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        real_open = urllib.request.urlopen
        def local(req, timeout):
            req.full_url = f'http://127.0.0.1:{server.server_port}/sendDocument'
            return real_open(req, timeout=timeout)
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'wire.bin'
                path.write_bytes(bytes(range(256)) * 5000)
                with patch.object(tg.urllib.request, 'urlopen', side_effect=local):
                    result = tg.request('fixture', 'sendDocument', {'document': {'path': str(path)}}, 3)
                self.assertTrue(result['ok'])
                self.assertIn(path.read_bytes(), received[0][1])
                self.assertIn('multipart/form-data', received[0][0])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_download_preserves_existing_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'received.bin'
            with patch.object(tg, 'request', return_value={'ok': True, 'result': {'file_path': 'remote.bin'}}), \
                    patch.object(coin, 'download', side_effect=lambda token, path, stream: stream.write(b'wire')):
                result = coin.invoke('telegram_download_file', {'file_id': 'id', 'destination': str(target)}, 'secret', 7, 70, None)
                self.assertTrue(result['ok'])
                self.assertEqual(target.read_bytes(), b'wire')
                with self.assertRaises(FileExistsError):
                    coin.invoke('telegram_download_file', {'file_id': 'id', 'destination': str(target)}, 'secret', 7, 70, None)
                self.assertEqual(target.read_bytes(), b'wire')

    def test_user_attributed_events_are_retained_without_granting_other_users_access(self):
        for kind, event in [('inline_query', {'id': 'query', 'from': {'id': 7}, 'query': 'hello'}),
                            ('poll_answer', {'poll_id': 'poll', 'user': {'id': 7}, 'option_ids': [0]}),
                            ('pre_checkout_query', {'id': 'payment', 'from': {'id': 7}, 'currency': 'AUD'})]:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                item = coin_input.accept(directory, {'update_id': 1, kind: event}, {7})
                self.assertIn(kind, item['text'])
                self.assertEqual(item['user'], 7)
                self.assertEqual(item['chat'], 7)
            with tempfile.TemporaryDirectory() as directory:
                self.assertIsNone(coin_input.accept(directory, {'update_id': 1, kind: event}, {8}))

    def test_album_replay_and_current_chat_reply(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(coin, 'COIN_STATE', Path(directory)), \
                patch.object(tg, 'request', return_value={'ok': True, 'result': [
                    {'message_id': 1, 'chat': {'id': 70}}, {'message_id': 2, 'chat': {'id': 70}}]}) as sender:
            args = {'media': [{'type': 'photo', 'media': 'id1'}, {'type': 'photo', 'media': 'id2'}]}
            first = coin.telegram_tool('telegram_sendMediaGroup', args, 'secret', 7, 70, input_ids=[42])
            replay = coin.telegram_tool('telegram_sendMediaGroup', args, 'secret', 7, 70, input_ids=[42])
            self.assertTrue(first['replied'])
            self.assertTrue(replay['duplicate'])
            self.assertEqual(sender.call_count, 1)
            self.assertEqual(len(coin.recent(7)), 2)
            self.assertEqual(coin.recent(8), [])
            coin.telegram_tool('telegram_sendMediaGroup', args, 'secret', 7, 70, input_ids=[43])
            self.assertEqual(sender.call_count, 2)

    def test_single_delivery_replay_preserves_result_and_identity_scope(self):
        payload = {'message_id': 1, 'chat': {'id': 70}, 'document': {'file_id': 'downloadable'}}
        with tempfile.TemporaryDirectory() as directory, patch.object(tg, 'request', return_value={'ok': True, 'result': payload}) as sender:
            for identity in ('one', 'two'):
                root = Path(directory) / identity
                root.mkdir()
                with patch.object(coin, 'COIN_STATE', root):
                    first = coin.telegram_tool('telegram_sendDocument', {'document': 'id'}, 'fixture', 7, 70, input_ids=[42])
                    second = coin.telegram_tool('telegram_sendDocument', {'document': 'id'}, 'fixture', 7, 70, input_ids=[42])
                    self.assertEqual(first['result'], second['result'])
                    self.assertEqual(second['result']['document']['file_id'], 'downloadable')
            self.assertEqual(sender.call_count, 2)

    def test_callback_authority_durability_and_replay(self):
        update = {'update_id': 1, 'callback_query': {'id': 'click', 'from': {'id': 7}, 'data': 'yes',
            'message': {'message_id': 11, 'date': 100, 'chat': {'id': 70}, 'text': 'Choose', 'from': {'is_bot': True}}}}
        with tempfile.TemporaryDirectory() as directory:
            first = coin_input.accept(directory, update, {7})
            self.assertIn('click', first['text'])
            self.assertEqual(first['user'], 7)
            self.assertEqual(first['chat'], 70)
            self.assertEqual(coin_input.accept(directory, update, {7}), first)
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(coin_input.accept(directory, update, {8}))
            self.assertEqual(coin_input.pending(directory), [])


class TelegramTurn(unittest.TestCase):
    setUp = coin_test.Turn.setUp
    run_turn = coin_test.Turn.run_turn

    def test_media_answers_request_without_extra_text(self):
        with patch.object(tg, 'request', return_value={'ok': True, 'result': {'message_id': 1, 'chat': {'id': 70}}}):
            self.run_turn([assistant(call('telegram_sendPhoto', {'photo': 'id'}), call('done'))])
        self.assertEqual(self.sent, [])

    def test_discovered_tool_available_next_round(self):
        with patch.object(tg, 'request', return_value={'ok': True, 'result': {'message_id': 1}}):
            requests = self.run_turn([assistant(call('telegram_tools', {'names': ['sendSticker']})),
                assistant(call('telegram_sendSticker', {'sticker': 'id'}), call('done'))])
        # run_turn returns its captured model calls.
        self.assertTrue(any(entry['function']['name'] == 'telegram_sendSticker'
                            for entry in requests[1][1]['tools']))

    def test_internal_completion_cannot_send_media(self):
        with patch.object(tg, 'request') as sender, patch.object(coin, 'complete', return_value=
                assistant(call('telegram_sendPhoto', {'photo': 'id'}), call('done'))):
            coin.turn('fixture', 7, 70, [], lambda: [], None,
                      wake={'message': 'Report completion of requested work. Image.'})
        sender.assert_not_called()

    def test_callback_acknowledgement_answers_only_matching_input(self):
        text = '<cointos-telegram-callback>' + json.dumps({'id': 'click', 'data': 'yes'}) + '</cointos-telegram-callback>'
        with patch.object(tg, 'request', return_value={'ok': True, 'result': True}):
            self.run_turn([assistant(call('telegram_answerCallbackQuery', {'callback_query_id': 'click'}), call('done'))], texts=[{'id': 1, 'text': text}])
        self.assertEqual(self.sent, [])
        self.assertFalse(tg.answers('telegram_answerCallbackQuery', {'callback_query_id': 'other'}, {'text': text}))
        self.assertFalse(tg.answers('telegram_answerCallbackQuery', {'callback_query_id': 'click'}, {'text': 'A direct question'}))

    def test_poll_vote_notification_can_finish_without_a_private_chat_reply(self):
        text = '<cointos-telegram-event>' + json.dumps({'kind': 'poll_answer', 'event': {'poll_id': 'p', 'user': {'id': 7}, 'option_ids': [0]}}) + '</cointos-telegram-event>'
        self.run_turn([assistant(call('done'))], texts=[{'id': 1, 'text': text}])
        self.assertEqual(self.sent, [])
