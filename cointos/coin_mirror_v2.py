"""A passive Coin journal viewer using native OpenCode 2 model/tool events.

The only executable viewer tool retrieves an already recorded result. It has no
Coin controls, CointOS credentials or connection to the model gateway.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import secrets
import shutil
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from cointos.coin_mirror import Mirror as LegacyMirror, PROVIDER, VIEW_ONLY, free_port, _text

try:  # A viewer names the assistant the instance configured; the fallback is the historical name.
    from cointos.config import coin_name, load as _load_config
    NAME = coin_name(_load_config())
except Exception:
    NAME = "Coin"


class Replay(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        if self.headers.get('authorization') != 'Bearer ' + self.server.token:
            self.send_error(403)
            return
        key = self.path.removeprefix('/result/')
        if key not in self.server.results:
            self.send_error(404)
            return
        value = self.server.results[key]
        raw = json.dumps(value).encode()
        self.send_response(200)
        self.send_header('content-type', 'application/json')
        self.send_header('content-length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers.get('content-length') or 0)))
        primary = any(t.get('function', {}).get('name') == 'coin_observation' for t in request.get('tools', []))
        admitted = _text((request.get('messages') or [{}])[-1]) in self.server.expected
        # A subsequent tool response resumes the same admitted replay loop.
        admitted |= (request.get('messages') or [{}])[-1].get('role') == 'tool'
        self.send_response(200)
        self.send_header('content-type', 'text/event-stream')
        self.end_headers()

        def chunk(delta, finish=None):
            value = {'id': 'mirror', 'object': 'chat.completion.chunk', 'created': int(time.time()),
                     'model': 'coin', 'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish}]}
            self.wfile.write(b'data: ' + json.dumps(value).encode() + b'\n\n')
            self.wfile.flush()

        try:
            if not primary or not admitted:
                chunk({'role': 'assistant', 'content': f'This window only shows {self.server.name}. Message {self.server.name} on Telegram.' if primary else getattr(self.server, 'name', NAME)})
                chunk({}, 'stop')
            else:
                chunk({'role': 'assistant'})
                while True:
                    kind, value = self.server.pending.get()
                    if kind == 'stop':
                        chunk({}, 'stop')
                        break
                    if kind == 'tool':
                        chunk({'tool_calls': [{'index': 0, 'id': value['record'], 'type': 'function',
                                              'function': {'name': 'coin_observation', 'arguments': json.dumps({
                                                  'name': value['name'], 'arguments': value['arguments']})}}]})
                        chunk({}, 'tool_calls')
                        break
                    chunk(value)
            self.wfile.write(b'data: [DONE]\n\n')
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass


class Mirror(LegacyMirror):
    def start(self):
        from cointos.config import ROOT
        shutil.rmtree(self.directory, ignore_errors=True)
        for name in ('data', 'config/opencode', 'state', 'cache', 'work'):
            (self.directory / name).mkdir(parents=True, mode=0o700)
        self.stand_in = ThreadingHTTPServer(('127.0.0.1', 0), Replay)
        self.name = getattr(self, "name", NAME)
        self.stand_in.name = self.name
        self.stand_in.expected, self.stand_in.results = set(), {}
        self.stand_in.pending = queue.Queue()
        self.stand_in.token = secrets.token_urlsafe(24)
        threading.Thread(target=self.stand_in.serve_forever, daemon=True).start()
        config = {'model': f'{PROVIDER}/coin', 'small_model': f'{PROVIDER}/coin',
                  'autoupdate': False, 'share': 'disabled', 'mcp': {},
                  'plugin': [str(ROOT / 'cointos/coin_view_plugin')],
                  'permission': {'*': 'deny', 'coin_observation': 'allow'},
                  'provider': {PROVIDER: {'npm': '@ai-sdk/openai-compatible',
                    'models': {'coin': {'name': self.name, 'limit': {'context': 131072, 'output': 16384}}},
                    'options': {'apiKey': 'local', 'baseURL': f'http://127.0.0.1:{self.stand_in.server_port}/v1'}}}}
        config_path = self.directory / 'opencode.json'
        config_path.write_text(json.dumps(config))
        (self.directory / 'models.json').write_text('{}')
        self.password = secrets.token_urlsafe(24)
        self.environment = {**os.environ, 'OPENCODE_PASSWORD': self.password,
                            'OPENCODE_CONFIG': str(config_path), 'PWD': str(self.directory / 'work'),
                            'OPENCODE_DISABLE_MODELS_FETCH': '1',
                            'OPENCODE_MODELS_PATH': str(self.directory / 'models.json'),
                            'COINTOS_COIN_REPLAY_URL': f'http://127.0.0.1:{self.stand_in.server_port}',
                            'COINTOS_COIN_REPLAY_TOKEN': self.stand_in.token,
                            **{f'XDG_{name.upper()}_HOME': str(self.directory / name)
                               for name in ('data', 'config', 'state', 'cache')}}
        self.url = f'http://127.0.0.1:{free_port()}'
        self.server = subprocess.Popen([self.opencode, 'serve', '--hostname', '127.0.0.1',
                                       '--port', self.url.rsplit(':', 1)[1]], cwd=self.directory / 'work',
                                       env=self.environment, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.displayed, self.opened = ('', ''), False
        deadline = time.monotonic() + 30
        while True:
            try:
                self.session = self.call('/api/session', {'title': self.name, 'model': {'providerID': PROVIDER, 'id': 'coin'},
                                                        'location': {'directory': str(self.directory / 'work')}})['data']['id']
                return
            except (OSError, ValueError):
                if self.server.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError('the OpenCode 2 display server did not start')
                time.sleep(.2)

    def attach_command(self):
        return [self.opencode, '--server', self.url, '--session', self.session]

    def window_environment(self):
        return {**os.environ, 'OPENCODE_PASSWORD': self.password}

    def idle(self):
        if self.opened:
            self.stand_in.pending.put(('stop', None))
            self.opened = False

    def open_message(self, text):
        self.idle()
        self.stand_in.expected.add(text)
        self.call(f'/api/session/{self.session}/prompt', {'text': text, 'delivery': 'queue'})
        self.opened, self.message = True, True
        self.displayed, self.finished = ('', ''), ('', '')

    def words(self, reasoning, content, *, final=False):
        if not self.opened or self.finished == (reasoning, content):
            return
        updated = []
        for before, after, field in zip(self.displayed, (reasoning, content), ('reasoning_content', 'content')):
            if after.startswith(before):
                delta, shown = after[len(before):], after
            elif final:
                label = 'reasoning' if field == 'reasoning_content' else 'reply'
                delta = '\n\n[Recorded ' + label + ']\n' + (after or '(empty)')
                shown = after
            elif before.endswith(after):
                delta, shown = '', before
            else:
                overlap = suffix_overlap(before, after)
                delta = after[overlap:] if overlap else ''
                shown = before + delta
            if delta:
                self.stand_in.pending.put(('delta', {field: delta}))
            updated.append(shown)
        self.displayed = tuple(updated)

    def feed(self, entry):
        kind = entry.get('kind')
        if kind == 'user':
            self.open_message(entry.get('text') or '(no text)')
        elif kind in ('assistant', 'tool'):
            if not self.opened:
                self.open_message(entry.get('trigger') or f'{NAME} turn')
            if kind == 'assistant':
                self.finished = None
                self.words(entry.get('reasoning') or '', entry.get('content') or '', final=True)
                self.finished = self.displayed
            else:
                record = secrets.token_hex(16)
                self.stand_in.results[record] = entry.get('output')
                self.stand_in.pending.put(('tool', {'record': record, 'name': entry.get('name') or 'tool',
                                                  'arguments': entry.get('input') or {}}))
                self.displayed = ('', '')

    def stop(self):
        self.idle()
        super().stop()
        self.stand_in.server_close()


def suffix_overlap(before, after):
    """Match a capped live suffix in linear time; final journal text stays authoritative."""
    if not after:
        return 0
    failure = [0] * len(after)
    for index in range(1, len(after)):
        match = failure[index - 1]
        while match and after[index] != after[match]:
            match = failure[match - 1]
        failure[index] = match + (after[index] == after[match])
    match = 0
    for char in before[-len(after):]:
        while match and (match == len(after) or after[match] != char):
            match = failure[match - 1]
        if after[match] == char:
            match += 1
    return match
