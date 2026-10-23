"""Standing photo intake scales in the data plane, without one model turn per file."""
import hashlib
import json
from pathlib import Path
import queue
import tempfile
import unittest
from unittest.mock import Mock, patch

from cointos import coin, coin_input, coin_routing


class Routing(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(coin, 'COIN_STATE', self.root / 'coin'))
        self.enterContext(patch.object(coin, 'report'))
        self.enterContext(patch.object(coin.kt_mcp, 'open_session', return_value=None))
        self.enterContext(patch.object(coin, 'attachment_file', side_effect=lambda token, ident: {
            'file_path': ident, 'file_size': len(ident.encode())}))
        self.download = self.enterContext(patch.object(coin, 'download', side_effect=lambda token, path, stream: stream.write(path.encode())))
        self.media = coin.COIN_STATE / 'attachments'
        self.rules = coin.COIN_STATE / 'routing'
        self.dest = self.root / 'pictures'

    def accept(self, ident, user=7, text='', at=100):
        return coin_input.accept(coin.COIN_STATE / 'inputs', {'update_id': ident, 'message': {
            'from': {'id': user}, 'chat': {'id': user * 10}, 'date': at,
            'text': text, 'photo': [{'file_id': str(ident), 'width': 10, 'height': 10}]}}, {7, 8})

    def test_294_photos_route_without_model_or_extra_hash_verification(self):
        coin_routing.configure(self.rules, 7, str(self.dest), start_at=50)
        for ident in range(1, 295):
            self.accept(ident)
        with patch.object(coin, 'complete') as model, patch.object(coin, 'send') as send, \
                patch.object(coin_routing, '_hash', side_effect=AssertionError('routine files must not be rehashed')):
            coin.transfer_pending_attachments('fixture-token', {7})
            coin.transfer_pending_attachments('fixture-token', {7})
        model.assert_not_called()
        send.assert_not_called()
        self.assertEqual(self.download.call_count, 294)
        self.assertEqual(coin_input.pending(coin.COIN_STATE / 'inputs'), [])
        self.assertEqual(len(list(self.dest.iterdir())), 294)
        for ident in range(1, 295):
            self.assertEqual((self.dest / f'photo_{ident}.jpg').read_bytes(), str(ident).encode())
        # Reopening the durable rule and another batch need no conversation history.
        self.accept(295)
        coin.transfer_pending_attachments('fixture-token', {7})
        self.assertEqual((self.dest / 'photo_295.jpg').read_bytes(), b'295')

    def test_setup_race_catches_up_saved_files_but_not_older_or_other_users(self):
        self.accept(1, at=10)
        self.accept(2, at=100)
        self.accept(3, user=8, at=100)
        coin.transfer_pending_attachments('fixture-token', {7, 8})
        coin_routing.configure(self.rules, 7, str(self.dest), start_at=50)
        coin.transfer_pending_attachments('fixture-token', {7, 8})
        self.assertEqual([p.name for p in self.dest.iterdir()], ['photo_2.jpg'])
        self.assertTrue((self.media / '7/1/0/files/photo.jpg').exists())
        self.assertTrue((self.media / '8/3/0/files/photo.jpg').exists())

    def test_move_receipt_survives_restart_and_later_manual_organisation(self):
        route = coin_routing.configure(self.rules, 7, str(self.dest), 'move', start_at=0)
        entry = self.accept(1)
        coin.transfer_pending_attachments('fixture-token', {7})
        source = self.media / '7/1/0/files/photo.jpg'
        self.assertFalse(source.exists())
        moved = self.root / 'elsewhere.jpg'
        (self.dest / 'photo_1.jpg').rename(moved)
        # Interrupted intake acknowledgement replays the descriptor, not the move.
        with patch.object(coin_input, 'pending', return_value=[entry]):
            coin.transfer_pending_attachments('fixture-token', {7})
        self.assertTrue(moved.exists())
        self.assertFalse((self.dest / 'photo_1.jpg').exists())
        self.assertEqual(self.download.call_count, 1)
        self.assertFalse(coin_routing.receipt(self.media, 7, 1, 0)['present'])

    def test_caption_and_text_reach_model_while_plain_photos_do_not(self):
        coin_routing.configure(self.rules, 7, str(self.dest), start_at=0)
        self.accept(1)
        self.accept(2, text='This one needs a different folder')
        coin.transfer_pending_attachments('fixture-token', {7})
        self.assertEqual([v['id'] for v in coin_input.pending(coin.COIN_STATE / 'inputs')], [2])
        self.assertFalse((self.dest / 'photo_2.jpg').exists())
        inbox = Mock(); inbox.get.side_effect = KeyboardInterrupt
        with patch.object(coin, 'complete', return_value={'role': 'assistant', 'content': 'Caption received.'}) as model, \
                patch.object(coin, 'send'), self.assertRaises(KeyboardInterrupt):
            coin.worker('fixture-token', inbox, {7})
        self.assertIn('This one needs a different folder', str(model.call_args.args[1]))

    def test_collision_is_preserved_and_other_photos_still_proceed(self):
        coin_routing.configure(self.rules, 7, str(self.dest), 'move', start_at=0)
        (self.dest / 'photo_1.jpg').write_bytes(b'keep')
        self.accept(1); self.accept(2)
        coin.transfer_pending_attachments('fixture-token', {7})
        self.assertEqual((self.dest / 'photo_1.jpg').read_bytes(), b'keep')
        self.assertEqual((self.dest / 'photo_2.jpg').read_bytes(), b'2')
        self.assertTrue((self.media / '7/1/0/files/photo.jpg').exists())
        self.assertEqual([v['id'] for v in coin_input.pending(coin.COIN_STATE / 'inputs')], [1])
        status = coin.invoke('attachment_status', {}, '', 7, 70, None)
        self.assertEqual(status['failed_inputs'], 1)

    def test_cancelled_and_removed_user_routes_do_not_continue(self):
        coin_routing.configure(self.rules, 7, str(self.dest), start_at=0)
        self.accept(1)
        coin.transfer_pending_attachments('fixture-token', set())
        self.assertFalse(list(self.dest.iterdir()))
        self.assertTrue(coin_routing.stop(self.rules, 7))
        coin.transfer_pending_attachments('fixture-token', {7})
        self.assertEqual(coin_input.pending(coin.COIN_STATE / 'inputs'), [])
        self.assertTrue((self.media / '7/1/0/files/photo.jpg').exists())
        self.assertFalse(list(self.dest.iterdir()))

    def test_captioned_setup_applies_only_current_captioned_inputs(self):
        self.accept(1, text='Copy incoming pictures here')
        self.accept(2, text='A separate caption')
        for entry in coin_input.pending(coin.COIN_STATE / 'inputs'):
            coin.input_text('fixture-token', entry)
        first = coin_input.pending(coin.COIN_STATE / 'inputs')[0]
        coin.invoke('attachment_route', {'destination': str(self.dest)}, '', 7, 70, None, inputs=[first])
        coin.transfer_pending_attachments('fixture-token', {7})
        self.assertTrue((self.dest / 'photo_1.jpg').exists())
        self.assertFalse((self.dest / 'photo_2.jpg').exists())

    def test_standing_rule_is_visible_after_conversation_history_is_gone(self):
        coin_routing.configure(self.rules, 7, str(self.dest), 'move', start_at=0)
        def answer(model, messages, **options):
            route = next(m['content'] for m in messages if '<cointos-photo-route>' in m.get('content', ''))
            self.assertIn(str(self.dest), route)
            self.assertIn('"operation": "move"', route)
            return {'role': 'assistant', 'content': ''}
        with patch.object(coin, 'recent', return_value=[]), patch.object(coin, 'complete', side_effect=answer):
            coin.turn('fixture-token', 7, 70, ['Stop the photo rule'], lambda: [], None)


if __name__ == '__main__':
    unittest.main()
