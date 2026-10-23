import gzip
import http.client
import json
from pathlib import Path
import shutil
import socket
import subprocess
import threading
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer

from cointos import gateway, state
from tests import support


class DashboardTransport(unittest.TestCase):
    def test_model_memory_classifies_anonymous_gufo_weights(self):
        shapes = {name: {'lanes': 1, 'memory_gb': 30, 'weights_gb': 20, **extra}
                  for name, extra in [('gufo', {'backend': 'gufo'}),
                                      ('llama', {'backend': 'llama'}), ('default', {})]}
        with patch.dict(state.CONFIG, models=shapes):
            models = state.fresh({})['model_memory']
        self.assertFalse(models['gufo']['weights_reclaimable'])
        self.assertTrue(models['llama']['weights_reclaimable'])
        self.assertTrue(models['default']['weights_reclaimable'])

    @unittest.skipUnless(shutil.which('node'), 'requires Node for browser JavaScript checks')
    def test_memory_chart_counts_weights_once_for_each_backing_type(self):
        script = r'''
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync('web/dashboard.html', 'utf8');
const tileParts = {'b': {}, 'small': {}, '.meter i': {style: {}}};
const elements = {'membar': {}, 'memfacts': {}, 'mem-value': {}, 'mem-label': {},
  'tile-mem': {querySelector: selector => tileParts[selector]}};
const context = {$: id => elements[id], document: {querySelectorAll: () => []},
  setText: (element, text) => element.textContent = text,
  setHTML: (element, html) => element.innerHTML = html};
vm.createContext(context);
vm.runInContext(html.slice(html.indexOf('const MEMORY_COLOURS'), html.indexOf('function renderChecks(')), context);
const gb = gib => gib * 2 ** 30 / 1e9;
for (const reclaimable of [true, false]) {
  const frame = {memory: {physical_gb: gb(128), available_gb: gb(reclaimable ? 83 : 63)},
    models: {loaded: {up: true}, unloaded: {up: false}},
    model_memory: {loaded: {weights_gb: 20, memory_gb: 30, weights_reclaimable: reclaimable},
      unloaded: {weights_gb: 40, memory_gb: 60, weights_reclaimable: false}}, saved_bytes: 5 * 2 ** 30};
  const values = Array.from(context.memoryValues(frame));
  assert.deepEqual(values, [30, 20, 10, 5, 63], 'same physical allocation regardless of backing type');
  assert.equal(values.reduce((a, b) => a + b, 0), 128);
  context.renderMemory(frame);
  assert.equal(tileParts.b.textContent, '51%');
  assert.equal(tileParts.small.textContent, '65 of 128 GB');
  assert.equal(elements['mem-value'].textContent, '65 GB');
}
const mixed = {memory: {physical_gb: gb(128), available_gb: gb(73)},
  models: {gufo: {up: true}, llama: {up: true}}, saved_bytes: 5 * 2 ** 30,
  model_memory: {gufo: {weights_gb: 10, memory_gb: 15, weights_reclaimable: false},
    llama: {weights_gb: 10, memory_gb: 15, weights_reclaimable: true}}};
assert.deepEqual(Array.from(context.memoryValues(mixed)), [30, 20, 10, 5, 63]);
'''
        subprocess.run(['node', '-e', script], cwd=Path(__file__).resolve().parents[1],
                       check=True, timeout=10, capture_output=True, text=True)

    def test_slow_snapshot_reader_does_not_hold_daemon_lock(self):
        support.fresh_ledger(self)
        state.L['system_contexts']['padding'] = 'x' * (8 * 1024 * 1024)
        server = ThreadingHTTPServer(('127.0.0.1', 0), gateway.Handler)
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        connection = http.client.HTTPConnection(*server.server_address, timeout=3)
        connection.connect()
        connection.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024)
        self.addCleanup(connection.close)
        connection.request('GET', '/api/ledger')
        response = connection.getresponse()
        self.addCleanup(response.close)
        self.assertEqual(response.status, 200)
        self.assertGreater(int(response.getheader('Content-Length')), 8 * 1024 * 1024)
        # Leave the body unread: the response exceeds the socket buffers.
        acquired = state.LOCK.acquire(timeout=.5)
        if acquired:
            state.LOCK.release()
        self.assertTrue(acquired, 'a slow snapshot reader held the daemon lock')

    def test_snapshot_remains_consistent_when_ledger_changes_before_encoding(self):
        support.fresh_ledger(self)
        state.L['tasks']['old'] = {'note': 'original', 'nested': ['original']}
        handler = gateway.Handler.__new__(gateway.Handler)
        handler.path = '/api/ledger'
        sent = []

        def reply(status, snapshot):
            # A scheduler/control update after capture must not alter this response.
            with state.LOCK:
                state.L['tasks']['old']['note'] = 'updated'
                state.L['tasks']['old']['nested'].append('updated')
                state.L['tasks']['new'] = {'note': 'added later'}
            sent.append((status, json.loads(json.dumps(snapshot))))

        handler.reply = reply
        handler.do_GET()
        self.assertEqual(sent[0][0], 200)
        self.assertEqual(sent[0][1]['tasks'], {'old': {'note': 'original', 'nested': ['original']}})
        self.assertEqual(state.L['tasks']['old']['note'], 'updated')

    def test_negotiated_compression_preserves_large_snapshot_and_html(self):
        payload = {'brief': 'a large archived task ' * 1000}

        class Handler(gateway.Handler):
            def do_GET(self):
                if self.path == '/':
                    self.reply(200, b'<html>' + b'x' * 2048 + b'</html>', 'text/html; charset=utf-8')
                else:
                    self.reply(200, payload)

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        for encoding, compressed in [('', False), ('br, gzip', True), ('gzip;q=0', False),
                                     ('gzip;q=0.5', True), ('gzip;q=bad', False)]:
            with self.subTest(encoding=encoding):
                connection = http.client.HTTPConnection(*server.server_address, timeout=2)
                self.addCleanup(connection.close)
                connection.request('GET', '/api/ledger', headers={'Accept-Encoding': encoding})
                response = connection.getresponse()
                body = response.read()
                self.assertEqual(response.status, 200)
                self.assertEqual(response.getheader('Vary'), 'Accept-Encoding')
                self.assertEqual(int(response.getheader('Content-Length')), len(body))
                self.assertEqual(response.getheader('Content-Encoding'), 'gzip' if compressed else None)
                if compressed:
                    self.assertLess(len(body), len(json.dumps(payload)) // 10)
                    body = gzip.decompress(body)
                self.assertEqual(json.loads(body), payload)
        connection.request('GET', '/', headers={'Accept-Encoding': 'gzip'})
        response = connection.getresponse()
        self.assertEqual(response.getheader('Content-Type'), 'text/html; charset=utf-8')
        self.assertEqual(gzip.decompress(response.read()), b'<html>' + b'x' * 2048 + b'</html>')

    @unittest.skipUnless(shutil.which('node'), 'requires Node for browser JavaScript checks')
    def test_poll_reports_request_and_render_failures_and_retries(self):
        script = r'''
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync('web/dashboard.html', 'utf8');
const poll = html.slice(html.indexOf('async function poll()'), html.indexOf('\npoll();'));
(async () => {
  for (const mode of ['ok', 'http', 'json', 'render', 'timeout']) {
    const stamp = {textContent: ''}, timers = [], cleared = [], rendered = [];
    const context = {AbortController, location: {host: 'ddriver.test'}, console: {error() {}},
      $: () => stamp, setTimeout: (fn, ms) => (timers.push({fn, ms}), timers.length),
      clearTimeout: id => cleared.push(id),
      render: data => {if (mode === 'render') throw new Error('bad task field'); rendered.push(data);},
      fetch: async (url, options) => {
        assert.equal(url, '/api/ledger');
        assert.equal(options.cache, 'no-store');
        assert.ok(options.signal);
        if (mode === 'timeout') {
          return new Promise((resolve, reject) => {
            options.signal.addEventListener('abort', () => reject(Object.assign(new Error('aborted'), {name: 'AbortError'})));
            timers[0].fn();
          });
        }
        return {ok: mode !== 'http', status: 502, json: async () => {
          if (mode === 'json') throw new Error('invalid JSON');
          return {agents: {}};
        }};
      }};
    vm.createContext(context);
    vm.runInContext(poll, context);
    await context.poll();
    assert.equal(timers[0].ms, 30000);
    assert.deepEqual(cleared, [1]);
    assert.equal(timers[1].ms, 1000, 'each outcome schedules another poll');
    if (mode === 'ok') assert.equal(rendered.length, 1);
    else if (mode === 'render') assert.match(stamp.textContent, /Dashboard display failed: bad task field/);
    else {
      assert.equal(rendered.length, 0);
      assert.match(stamp.textContent, /Connection to ddriver.test failed:.*retrying/);
      assert.ok(stamp.textContent.includes({http: 'HTTP 502', json: 'invalid JSON', timeout: 'timed out'}[mode]));
    }
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
'''
        subprocess.run(['node', '-e', script], cwd=Path(__file__).resolve().parents[1],
                       check=True, timeout=10, capture_output=True, text=True)
