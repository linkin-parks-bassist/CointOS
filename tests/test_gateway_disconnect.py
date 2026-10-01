import socket
import threading
import time
import json
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from cointos import gateway, lanes, state
from tests import support


class Disconnect(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self)
        self.enterContext(patch.dict(lanes.RUNS, clear=True))
        self.enterContext(patch.dict(lanes.BUSY, clear=True))
        self.enterContext(patch.dict(lanes.HELD, clear=True))
        self.enterContext(patch.dict(state.ACTIVE, chats=0, landings=0))
        self.enterContext(patch.dict(state.CONFIG, keepalive_seconds=.02))
        model = state.CONFIG['work_model']
        state.L['models'][model]['up'] = True
        self.enterContext(patch.object(gateway, 'identity', return_value=('coin', 'coin', 'coin')))
        self.enterContext(patch.object(gateway, 'render_request', return_value={'tokens': [1, 2], 'reader': {}}))
        self.enterContext(patch.object(gateway.lifecycle, 'engaged'))
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), gateway.Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def wait_for(self, predicate):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            with state.LOCK:
                if predicate():
                    return
            time.sleep(.01)
        self.fail('gateway did not settle disconnect')

    def test_disconnected_json_and_stream_callers_release_waiting_thoughts(self):
        for streaming in (False, True):
            with self.subTest(stream=streaming):
                peer = socket.create_connection(self.server.server_address)
                body = json.dumps({'model': state.CONFIG['work_model'], 'stream': streaming}).encode()
                peer.sendall(b'POST /v1/chat/completions HTTP/1.0\r\nContent-Type: application/json\r\nContent-Length: '
                             + str(len(body)).encode() + b'\r\n\r\n' + body)
                self.wait_for(lambda: bool(state.L['thoughts']))
                peer.close()
                self.wait_for(lambda: not state.L['thoughts'] and state.ACTIVE['chats'] == 0)
                self.assertFalse(lanes.RUNS)
