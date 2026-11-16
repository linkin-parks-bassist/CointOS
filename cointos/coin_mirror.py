"""Show Coin in OpenCode's own viewer: a private display session fed from Coin's turn journal.

Coin is not an OpenCode session. A loopback `opencode serve` holds a mirror of its turns, so the
window is the same `opencode attach` every agent gets. Each user message creates a real assistant
message through a stand-in provider, because only those reach an attached window live; reasoning,
words and tool calls are then written onto it as parts. The server runs only while a window is open
and never drives Coin: the stand-in never calls a tool, and typed text gets a plain refusal.
"""
from __future__ import annotations

import base64
import json
import os
import secrets
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:  # The mirror names the configured assistant, defaulting to the historical name.
    from cointos.config import coin_name as _coin_name, load as _load_config
    NAME = _coin_name(_load_config())
except Exception:
    NAME = 'Coin'
VIEW_ONLY = f'This window only shows {NAME}. Message {NAME} on Telegram.'
PROVIDER = 'mirror'
BACKFILL_ENTRIES = 60


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


class StandIn(BaseHTTPRequestHandler):
    """An OpenAI-compatible model that says one fixed thing, so OpenCode opens a message."""
    def log_message(self, *_):
        pass

    def do_POST(self):
        length = int(self.headers.get('content-length') or 0)
        request = json.loads(self.rfile.read(length) or b'{}')
        expected = self.server.expected
        typed = not any(_text(m) in expected for m in (request.get('messages') or [])[-1:])
        words = VIEW_ONLY if typed else ' '
        self.send_response(200)
        self.send_header('content-type', 'text/event-stream')
        self.end_headers()
        for delta, finish in (({'role': 'assistant', 'content': words}, None), ({}, 'stop')):
            chunk = {'id': 'mirror', 'object': 'chat.completion.chunk', 'created': int(time.time()), 'model': 'coin',
                     'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish}]}
            self.wfile.write(b'data: ' + json.dumps(chunk).encode() + b'\n\n')
        self.wfile.write(b'data: [DONE]\n\n')


def _text(message: dict) -> str:
    content = message.get('content')
    if isinstance(content, list):
        return ''.join(part.get('text', '') for part in content if isinstance(part, dict))
    return content or ''


class Mirror:
    """A display session. `feed` applies one journal entry; `words` shows text still being written."""
    def __init__(self, directory: Path, opencode: str):
        self.directory, self.opencode = directory, opencode
        self.counter = 0
        self.message = None
        self.live = None  # the reply part still being written
        self.live_reasoning = None  # the reasoning part still being written
        self.live_started = 0
        self.finished = ('', '')  # the last finished step's reasoning and words, never re-shown as live
        self.calls = {}

    def start(self) -> None:
        shutil.rmtree(self.directory, ignore_errors=True)  # the journal owns history; this is only a view
        for name in ('data', 'config/opencode', 'state', 'cache', 'work'):
            (self.directory / name).mkdir(parents=True, mode=0o700)
        self.stand_in = ThreadingHTTPServer(('127.0.0.1', 0), StandIn)
        self.stand_in.expected = set()
        threading.Thread(target=self.stand_in.serve_forever, daemon=True).start()
        model = {'name': 'Coin', 'limit': {'context': 131072, 'output': 16384}}
        (self.directory / 'config/opencode/opencode.json').write_text(json.dumps({
            'model': f'{PROVIDER}/coin', 'small_model': f'{PROVIDER}/coin', 'autoupdate': False, 'share': 'disabled',
            'provider': {PROVIDER: {'npm': '@ai-sdk/openai-compatible', 'name': 'Coin', 'models': {'coin': model},
                                    'options': {'apiKey': 'local',
                                                'baseURL': f'http://127.0.0.1:{self.stand_in.server_port}/v1'}}}}))
        self.password = secrets.token_urlsafe(24)
        self.environment = {**os.environ, 'OPENCODE_SERVER_PASSWORD': self.password,
                            **{f'XDG_{name.upper()}_HOME': str(self.directory / name)
                               for name in ('data', 'config', 'state', 'cache')}}
        port = free_port()
        self.url = f'http://127.0.0.1:{port}'
        self.server = subprocess.Popen([self.opencode, 'serve', '--pure', '--hostname', '127.0.0.1', '--port', str(port), '--mdns=false'],
                                       cwd=self.directory / 'work', env=self.environment, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 30
        while True:
            try:
                self.session = self.call('/session', {'title': 'Coin'})['id']
                return
            except (OSError, ValueError):
                if self.server.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError('the display server did not start')
                time.sleep(0.2)

    def stop(self) -> None:
        self.server.terminate()
        try:
            self.server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.server.kill()
        self.stand_in.shutdown()
        shutil.rmtree(self.directory, ignore_errors=True)

    def attach_command(self) -> list[str]:
        return [self.opencode, 'attach', self.url, '--session', self.session]

    def window_environment(self) -> dict:
        """Only the server's data is private: the window keeps the user's own OpenCode settings."""
        return {**os.environ, 'OPENCODE_SERVER_PASSWORD': self.password}

    def call(self, path: str, body=None, method: str | None = None):
        token = base64.b64encode(f'opencode:{self.password}'.encode()).decode()
        request = urllib.request.Request(self.url + path, None if body is None else json.dumps(body).encode(),
                                         {'content-type': 'application/json', 'authorization': f'Basic {token}'},
                                         method=method or ('POST' if body is not None else 'GET'))
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read()
        return json.loads(raw) if raw else None

    def ident(self, kind: str) -> str:
        """OpenCode orders parts by id, so ids must rise with time."""
        self.counter += 1
        stamp = (int(time.time() * 1000) * 4096 + self.counter) & ((1 << 48) - 1)
        return f'{kind}_{stamp:012x}{secrets.token_hex(7)}'

    def part(self, identifier: str | None = None, **fields) -> str:
        identifier = identifier or self.ident('prt')
        self.call(f'/session/{self.session}/message/{self.message}/part/{identifier}',
                  {'id': identifier, 'sessionID': self.session, 'messageID': self.message, **fields}, 'PATCH')
        return identifier

    def open_message(self, text: str) -> None:
        self.stand_in.expected.add(text)
        known = {m['info']['id'] for m in self.call(f'/session/{self.session}/message')}
        self.call(f'/session/{self.session}/prompt_async', {'parts': [{'type': 'text', 'text': text}]})
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            for message in self.call(f'/session/{self.session}/message'):
                info = message['info']
                if info['id'] not in known and info['role'] == 'assistant' and info.get('finish'):
                    self.message, self.live, self.live_reasoning, self.finished = info['id'], None, None, ('', '')
                    # The stand-in's single space would otherwise sit above Coin's words.
                    for part in message['parts']:
                        if part['type'] == 'text':
                            self.call(f"/session/{self.session}/message/{self.message}/part/{part['id']}", method='DELETE')
                    return
            time.sleep(0.1)
        raise RuntimeError('the display server did not open a message')

    def words(self, reasoning: str, content: str) -> None:
        """Text still being generated, each kind in its own part: reasoning stays in the thinking
        block and only content is shown as the reply. The next assistant entry replaces both."""
        if not self.message:
            return
        done_reasoning, done_content = self.finished
        if done_reasoning.endswith(reasoning) and done_content.endswith(content):
            return  # the live record still holds the step that has just been finished
        if reasoning:
            if self.live_reasoning is None:
                self.live_started = int(time.time() * 1000)
            self.live_reasoning = self.part(self.live_reasoning, type='reasoning', text=reasoning,
                                            time={'start': self.live_started})
        if content:
            self.live = self.part(self.live, type='text', text=content)

    def feed(self, entry: dict) -> None:
        kind, now = entry.get('kind'), int(time.time() * 1000)
        if kind == 'user':
            self.open_message(entry.get('text') or '(no text)')
            return
        if not self.message:
            self.open_message(entry.get('trigger') or 'Coin turn')
        span = {'start': now, 'end': now}
        if kind == 'assistant':
            if entry.get('reasoning'):
                self.part(self.live_reasoning, type='reasoning', text=entry['reasoning'], time=span)
            elif self.live_reasoning:
                self.call(f'/session/{self.session}/message/{self.message}/part/{self.live_reasoning}', method='DELETE')
            self.live_reasoning = None
            self.finished = (entry.get('reasoning') or '', entry.get('content') or '')
            if entry.get('content'):
                self.live = self.part(self.live, type='text', text=entry['content'], time=span)
            elif self.live:
                self.call(f'/session/{self.session}/message/{self.message}/part/{self.live}', method='DELETE')
            self.live = None
        elif kind == 'tool':
            output = entry.get('output')
            self.part(type='tool', callID=entry.get('id') or self.ident('call'), tool=entry.get('name') or 'tool',
                      state={'status': 'completed', 'input': entry.get('input') or {}, 'metadata': {}, 'time': span,
                             'title': str(entry.get('name') or 'tool'),
                             'output': output if isinstance(output, str) else json.dumps(output)})


def journal_lines(path: Path, position: int) -> tuple[list[dict], int]:
    """Complete entries past `position`, and the new position. A short file means it rotated."""
    try:
        with path.open('rb') as stream:
            stream.seek(0, 2)
            if stream.tell() < position:
                position = 0
            stream.seek(position)
            raw = stream.read()
    except OSError:
        return [], position
    complete = raw[:raw.rfind(b'\n') + 1]
    entries = []
    for line in complete.splitlines():
        try:
            entries.append(json.loads(line))
        except ValueError:
            pass  # a damaged line cannot stop the view
    return entries, position + len(complete)


def show(journal: Path, directory: Path, opencode: str, states, stop=None, *, name=None) -> None:
    """Run the mirror and its window until `stop` says the slot moved or the window closes."""
    from cointos.config import load
    if load().get('opencode_v2'):
        from cointos.coin_mirror_v2 import Mirror as NativeMirror
        from cointos.opencode import OPENCODE2
        mirror = NativeMirror(directory, OPENCODE2)
    else:
        mirror = Mirror(directory, opencode)
    mirror.name = name or NAME
    mirror.start()
    window = None
    latest = {}
    finished = threading.Event()
    def follow():
        try:
            for state in states:
                if finished.is_set():
                    break
                latest.update(state)
        finally:
            close = getattr(states, 'close', None)
            if close is not None:
                close()
    follower = threading.Thread(target=follow, daemon=True, name='coin-view-live')
    follower.start()
    try:
        window = subprocess.Popen(mirror.attach_command(), env=mirror.window_environment(), cwd=directory / 'work')
        entries, position = journal_lines(journal, 0)
        entries = entries[-BACKFILL_ENTRIES:]  # recent history fills in behind the open window
        while window.poll() is None and not (stop and stop()):
            for entry in entries:
                mirror.feed(entry)
                if stop and stop():
                    return
            entries, position = journal_lines(journal, position)
            live = (latest.get('coin') or {}).get('live') or {}
            if not entries and (latest.get('coin') or {}).get('busy'):
                mirror.words(live.get('reasoning') or '', live.get('content') or '')
            elif not entries and hasattr(mirror, 'idle'):
                mirror.idle()
            time.sleep(0.5)
    finally:
        finished.set()
        if window is not None and window.poll() is None:
            window.terminate()
            try:
                window.wait(timeout=5)
            except subprocess.TimeoutExpired:
                window.kill()
        try:
            mirror.stop()
        finally:
            follower.join(timeout=load()['timeouts']['api_seconds'])
