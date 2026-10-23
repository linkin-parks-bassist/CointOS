import socket
import threading
import time
import json
import io
import queue
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from cointos import gateway, lanes, state, tasks
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

    def test_template_rejection_is_not_retried_as_an_outage(self):
        error = urllib.error.HTTPError('http://backend/apply-template', 400, 'Bad Request', {}, None)
        with patch.object(gateway, 'render_request', side_effect=error):
            request = urllib.request.Request(
                f'http://127.0.0.1:{self.server.server_address[1]}/v1/chat/completions',
                json.dumps({'model': state.CONFIG['work_model']}).encode(),
                {'Content-Type': 'application/json'})
            with self.assertRaises(urllib.error.HTTPError) as refused:
                urllib.request.urlopen(request, timeout=2)
        self.assertEqual(refused.exception.code, 400)
        self.assertFalse(state.L['thoughts'])

    def test_reasoning_only_terminal_reply_is_an_incomplete_response_not_successful_stop(self):
        task = support.running(tasks.create('operator', tasks.SYSTEM, 'inspect', 'Inspect response integrity', [1]),
                               'fixture-agent', worktree=False)
        final = {'reasoning': 'Reasoning reached its boundary.', 'content': '',
                 'tool_calls': [], 'phase': 'writing'}
        for streaming, end in ((False, 'done'), (True, 'done'), (False, 'limit'), (True, 'limit')):
            with self.subTest(stream=streaming, end=end):
                q = queue.Queue(); q.put([1]); q.put({'end': end})
                handler = gateway.Handler.__new__(gateway.Handler)
                handler.wfile = io.BytesIO()
                handler.peer_closed = lambda: False
                handler.send_response = lambda code: None
                handler.send_header = lambda *args: None
                handler.end_headers = lambda: None
                replies = []
                handler.reply = lambda code, body: replies.append((code, body))
                with patch.dict(lanes.RUNS, fixture={'queue': q}), \
                     patch.object(gateway.BACKEND, 'read', return_value=final), \
                     patch.object(gateway, 'log'):
                    handler.reply_thought({'stream': streaming}, 'fixture-agent', state.CONFIG['work_model'],
                                          {'tokens': [1, 2], 'reader': {}}, 'fixture')
                if streaming:
                    frames = [json.loads(line[6:]) for line in handler.wfile.getvalue().decode().splitlines()
                              if line.startswith('data: ') and line != 'data: [DONE]']
                    if end == 'limit':
                        self.assertEqual(frames[-1]['choices'][0]['finish_reason'], 'length')
                    else:
                        self.assertEqual(frames[-1]['error']['code'], 'incomplete_response')
                        self.assertFalse(any(c.get('finish_reason') == 'stop'
                                             for frame in frames for c in frame.get('choices', [])))
                else:
                    if end == 'limit':
                        self.assertEqual(replies[0][1]['choices'][0]['finish_reason'], 'length')
                    else:
                        self.assertEqual(replies[0][0], 502)
                        self.assertEqual(replies[0][1]['error']['code'], 'incomplete_response')
                self.assertEqual((task['status'], task['agent'], task['receipt']),
                                 ('running', 'fixture-agent', None))


class EndedRun(Disconnect):
    def test_a_request_with_an_ended_runs_key_is_refused_not_served_as_the_users(self):
        self.enterContext(patch.object(gateway.keys, "_persist"))
        key = gateway.keys.issue("worker-1", "background")
        gateway.keys.revoke("worker-1")
        self.assertEqual(gateway.keys.owner(key), ("user", "user"), "an unknown key alone would be the user's")
        import urllib.request, urllib.error
        request = urllib.request.Request(f"http://127.0.0.1:{self.server.server_address[1]}/v1/chat/completions",
                                         json.dumps({"model": state.CONFIG["work_model"]}).encode(),
                                         {"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
        with self.assertRaises(urllib.error.HTTPError) as refused:
            urllib.request.urlopen(request, timeout=2)
        self.assertEqual(refused.exception.code, 410)
        self.assertFalse(state.L["thoughts"], "no lane time was spent on it")
