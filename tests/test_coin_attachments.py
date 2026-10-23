"""Actual media intake, storage, interrupted downloads and model filesystem dispatch."""
import copy
import hashlib
import io
import json
from pathlib import Path
import queue
import tempfile
import unittest
from unittest.mock import patch
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import urllib.request
import urllib.error

from cointos import coin, coin_attachments, coin_files, coin_input, privatejson


class Attachments(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(coin, 'COIN_STATE', self.root))
        self.enterContext(patch.object(coin, 'report'))
        self.update = {'update_id': 1, 'message': {'from': {'id': 7}, 'chat': {'id': 70}, 'date': 100,
            'media_group_id': 'album', 'caption': 'Save these for later', 'photo': [
                {'file_id': 'small', 'width': 10, 'height': 10, 'file_size': 1},
                {'file_id': 'large', 'width': 100, 'height': 100, 'file_size': 7}]}}
        self.intake = self.root / 'inputs'
        self.payload = b'picture'
        self.enterContext(patch.object(coin, 'telegram', side_effect=self.telegram))
        self.downloads = []
        self.enterContext(patch.object(coin, 'download', side_effect=self.download))

    def telegram(self, token, method, body):
        self.assertEqual(method, 'getFile')
        return {'file_path': 'photos/' + body['file_id'], 'file_size': len(self.payload)}

    def download(self, token, remote, stream):
        self.downloads.append(remote)
        stream.write(self.payload)

    def input(self, update=None):
        return coin_input.accept(self.intake, update or self.update, {7})

    def test_album_keeps_largest_photo_each_caption_and_independent_identity(self):
        first = self.input()
        second_update = copy.deepcopy(self.update)
        second_update['update_id'] = 2
        second_update['message'].pop('caption')
        second_update['message']['photo'][-1]['file_id'] = 'other'
        second = self.input(second_update)
        self.assertEqual(first['attachments'][0]['file_id'], 'large')
        self.assertEqual(second['text'], '')
        self.assertEqual([item['media_group_id'] for item in coin_input.pending(self.intake)], ['album', 'album'])
        for item in (first, second):
            text = coin.input_text('fixture-token', item)
            metadata = json.loads(text.split('<cointos-attachments>\n')[1].split('\n</')[0])
            saved = metadata['files'][0]
            self.assertEqual(Path(saved['path']).read_bytes(), self.payload)
            self.assertEqual(saved['sha256'], hashlib.sha256(self.payload).hexdigest())
            self.assertEqual(saved['size'], len(self.payload))
            self.assertTrue(saved['present'])
            self.assertNotIn('fixture-token', text)
        self.assertEqual(self.downloads, ['photos/large', 'photos/other'])

    def test_documents_keep_labels_but_cannot_escape_storage(self):
        update = copy.deepcopy(self.update)
        update['message'].pop('photo')
        update['message']['document'] = {'file_id': 'document', 'file_name': '../../outside/日本語.png',
                                        'mime_type': 'image/png', 'file_size': len(self.payload)}
        record = self.input(update)
        text = coin.input_text('token', record)
        saved = next(self.root.glob('attachments/7/1/0/files/*.png'))
        self.assertEqual(saved.name, '日本語.png')
        self.assertEqual(saved.read_bytes(), self.payload)
        self.assertIn('../../outside/日本語.png', text)  # label is preserved as data

    def test_replay_does_not_download_or_resurrect_a_moved_file(self):
        item = self.input()
        coin.input_text('token', item)
        original = next(self.root.glob('attachments/7/1/0/files/*.jpg'))
        moved = self.root / 'organised.jpg'
        coin.execute('fs_move', {'path': str(original), 'destination': str(moved)})
        text = coin.input_text('token', self.input())
        self.assertIn('"present": false', text)
        self.assertFalse(original.exists())
        self.assertEqual(moved.read_bytes(), self.payload)
        self.assertEqual(len(self.downloads), 1)

    def test_file_media_types_and_duplicate_animation_document_reference(self):
        for index, kind in enumerate(coin_attachments.MEDIA, 1):
            update = copy.deepcopy(self.update)
            update['update_id'] = index
            update['message'].pop('photo')
            update['message'][kind] = {'file_id': str(index), 'mime_type': 'application/octet-stream'}
            if kind == 'animation':
                update['message']['document'] = update['message'][kind].copy()
            item = self.input(update)
            self.assertEqual(len(item['attachments']), 1)
            coin.input_text('token', item)
        self.assertEqual(len(self.downloads), len(coin_attachments.MEDIA))

    def test_download_failure_keeps_pending_input_and_no_partial_file(self):
        item = self.input()
        def broken(token, remote, stream):
            stream.write(b'part')
            raise OSError('connection reset')
        with patch.object(coin, 'download', side_effect=broken), self.assertRaises(OSError):
            coin.input_text('token', item)
        self.assertEqual(len(coin_input.pending(self.intake)), 1)
        self.assertFalse(list(self.root.glob('attachments/**/*.jpg')))
        self.assertFalse(list(self.root.glob('attachments/**/.coin-*')))
        coin.input_text('token', item)
        self.assertEqual(next(self.root.glob('attachments/**/*.jpg')).read_bytes(), self.payload)

    def test_short_download_is_not_committed(self):
        item = self.input()
        with patch.object(coin, 'download', side_effect=lambda token, remote, stream: stream.write(b'x')), \
                self.assertRaisesRegex(OSError, 'incomplete'):
            coin.input_text('token', item)
        self.assertFalse(list(self.root.glob('attachments/**/*.jpg')))
        self.assertFalse(list(self.root.glob('attachments/**/saved.json')))

    def test_permanent_rejection_preserves_descriptor_reports_error_and_allows_retry(self):
        item = self.input()
        error = urllib.error.HTTPError('https://telegram.invalid/botSECRET/getFile', 400, 'Bad request', {},
                                      io.BytesIO(b'{"description":"Bad Request: file is too big"}'))
        with patch.object(coin, 'telegram', side_effect=error):
            text = coin.input_text('SECRET', item)
        self.assertIn('file is too big', text)
        self.assertNotIn('SECRET', text)
        self.assertFalse(list(self.root.glob('attachments/**/*.jpg')))
        self.assertEqual(len(list(self.root.glob('attachments/**/request.json'))), 1)
        coin_input.complete(self.intake, [item['id']])
        self.assertEqual(coin_input.pending(self.intake), [])
        retried = coin.invoke('attachment_retry', {'update_id': 1, 'index': 0}, 'token', 7, 70, None)
        self.assertTrue(retried['ok'])
        self.assertEqual(Path(retried['attachment']['path']).read_bytes(), self.payload)
        with self.assertRaises(FileNotFoundError):
            coin.invoke('attachment_retry', {'update_id': 1, 'index': 0}, 'token', 8, 80, None)

    def test_receipt_failure_reuses_committed_bytes_on_restart(self):
        item = self.input()
        write = privatejson.write
        def failure(fd, filename, data, validate):
            if filename == 'saved.json':
                raise OSError('receipt persistence failed')
            return write(fd, filename, data, validate)
        with patch.object(privatejson, 'write', side_effect=failure), self.assertRaises(OSError):
            coin.input_text('token', item)
        coin.input_text('token', item)
        self.assertEqual(len(self.downloads), 1)

    def test_unauthorised_media_is_not_retained_or_downloaded(self):
        update = copy.deepcopy(self.update)
        update['message']['from']['id'] = 8
        self.assertIsNone(self.input(update))
        self.assertEqual(coin_input.pending(self.intake), [])
        self.assertFalse((self.root / 'attachments').exists())
        self.assertEqual(self.downloads, [])

    def test_changed_retained_media_cannot_replace_saved_input(self):
        self.input()
        before = (self.intake / 'intake.json').read_bytes()
        changed = copy.deepcopy(self.update)
        changed['message']['photo'][-1]['file_id'] = 'replacement'
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.input(changed)
        self.assertEqual((self.intake / 'intake.json').read_bytes(), before)

    def test_payload_labels_cannot_collide_with_storage_authority(self):
        for index, name in enumerate(['saved.json', 'owner.lock', 'files'], 1):
            update = copy.deepcopy(self.update)
            update['update_id'] = index
            update['message'].pop('photo')
            update['message']['document'] = {'file_id': str(index), 'file_name': name}
            item = self.input(update)
            coin.input_text('token', item)
            saved = self.root / f'attachments/7/{index}/0/files' / name
            self.assertEqual(saved.read_bytes(), self.payload)
            coin.input_text('token', item)
        self.assertEqual(len(self.downloads), 3)

    def test_turn_dispatches_real_file_tools_from_attachment_metadata(self):
        item = self.input()
        organised = self.root / 'photos'
        captured, sent = [], []
        def call(name, arguments):
            return {'id': name, 'function': {'name': name, 'arguments': json.dumps(arguments)}}
        def model(model, messages, **options):
            captured.append(copy.deepcopy(messages))
            if len(captured) == 1:
                self.assertIn('Save these for later', str(messages))
                content = next(m['content'] for m in messages if m['role'] == 'user' and '<cointos-attachments>' in m['content'])
                path = json.loads(content.split('<cointos-attachments>\n')[1].split('\n</')[0])['files'][0]['path']
                return {'role': 'assistant', 'tool_calls': [call('fs_mkdir', {'path': str(organised)}),
                    call('fs_move', {'path': path, 'destination': str(organised / 'saved.jpg')})]}
            self.assertTrue(all(json.loads(m['content'])['ok'] for m in messages if m['role'] == 'tool'))
            return {'role': 'assistant', 'content': 'Saved the picture in photos.'}
        with patch.object(coin, 'complete', side_effect=model), patch.object(coin, 'send', side_effect=lambda *args: sent.append(args[-1])):
            coin.turn('token', 7, 70, [item], lambda: [], None)
        self.assertEqual((organised / 'saved.jpg').read_bytes(), self.payload)
        self.assertEqual(sent, ['Saved the picture in photos.'])

    def test_poller_persists_album_then_worker_downloads_all_files_after_restart(self):
        first, second = copy.deepcopy(self.update), copy.deepcopy(self.update)
        second['update_id'] = 2
        second['message'].pop('caption')
        second['message']['photo'][-1]['file_id'] = 'second'
        responses = iter([[first, second], KeyboardInterrupt()])
        offsets = []
        def poll(token, method, body, *args):
            self.assertEqual(method, 'getUpdates')
            offsets.append(body['offset'])
            result = next(responses)
            if isinstance(result, BaseException):
                raise result
            return result
        with patch.object(coin, 'credentials', return_value=('token', {7})), \
                patch.object(coin, 'service_thread'), patch.object(coin, 'telegram', side_effect=poll), \
                self.assertRaises(KeyboardInterrupt):
            coin.main()
        self.assertEqual(offsets, [None, 3])
        self.assertEqual(self.downloads, [])  # saved descriptors, independent of model/network work
        coin.transfer_pending_attachments('token', {7})  # captionless sibling bypasses the model
        actual_pending = coin_input.pending
        def stop_after_completion(directory):
            records = actual_pending(directory)
            if not records:
                raise KeyboardInterrupt()
            return records
        def model(model, messages, **options):
            attachments = [m for m in messages if m['role'] == 'user' and '<cointos-attachments>' in m['content']]
            self.assertEqual(len(attachments), 1)  # the caption still reaches Coin
            self.assertEqual(len(list(self.root.glob('attachments/**/*.jpg'))), 2)
            return {'role': 'assistant', 'content': 'Both pictures are saved.'}
        with patch.object(coin.kt_mcp, 'open_session', return_value=None), \
                patch.object(coin_input, 'pending', side_effect=stop_after_completion), \
                patch.object(coin, 'complete', side_effect=model), patch.object(coin, 'send') as sender, \
                self.assertRaises(KeyboardInterrupt):
            coin.worker('token', queue.Queue(), {7})
        self.assertCountEqual(self.downloads, ['photos/large', 'photos/second'])
        self.assertEqual(actual_pending(self.intake), [])
        sender.assert_called_once_with('token', 70, 'Both pictures are saved.')

    def test_real_http_byte_stream_is_committed_and_hashed(self):
        payload = self.payload
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        item = self.input()
        open_url = urllib.request.urlopen
        urls = []
        def routed(url, **options):
            urls.append(url)
            return open_url(f'http://127.0.0.1:{server.server_port}/image.jpg', **options)
        try:
            with patch.object(coin, 'download', wraps=Attachments.real_download), \
                    patch.object(coin.urllib.request, 'urlopen', side_effect=routed):
                coin.input_text('fixture-token', item)
        finally:
            server.shutdown()
            server.server_close()
            worker.join()
        self.assertEqual(urls, ['https://api.telegram.org/file/botfixture-token/photos/large'])
        self.assertEqual(next(self.root.glob('attachments/**/*.jpg')).read_bytes(), payload)

    def test_download_transport_never_leaks_token_in_failure(self):
        # Use the actual transport rather than the fixture download callback.
        with patch.object(coin, 'download', wraps=Attachments.real_download), \
                patch.object(coin.urllib.request, 'urlopen', side_effect=OSError('https://api.telegram.org/file/botSECRET/bad')):
            with self.assertRaises(OSError) as caught:
                coin.download('SECRET', 'photos/image.jpg', io.BytesIO())
        self.assertNotIn('SECRET', str(caught.exception))

    real_download = staticmethod(coin.download)
