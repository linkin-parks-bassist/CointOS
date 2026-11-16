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
    @unittest.skipUnless(shutil.which('node'), 'requires Node for browser JavaScript checks')
    def test_focused_scheduler_control_displays_live_value_and_unknown_is_blank(self):
        script = r"""
const assert = require('node:assert/strict');
const html = require('node:fs').readFileSync('web/dashboard.html','utf8');
const input = {value:'8',options:[{value:'8'},{value:'64'}],disabled:false};
const status = {};
const $ = id => id==='chunk' ? input : status;
const document = {activeElement:input};
const schedulerControls = [{id:'chunk',key:'chunk_tokens',unit:'tokens',saving:false,error:''}];
function renderDefaultModel(){}
let MODEL_FETCHED=0;
function discoverModels(){}
eval(html.slice(html.indexOf('function renderScheduler('),html.indexOf('for (const control of schedulerControls) $(control.id).addEventListener')));
renderScheduler({scheduler:{chunk_tokens:64}});
assert.equal(input.value,'64','focused select hid the live setting');
assert.match(status.textContent,/64/);
renderScheduler({scheduler:{}});
assert.equal(input.value,'','unknown setting must not show the first numeric option');
assert.equal(input.disabled,true);
"""
        result = subprocess.run(['node','-e',script],capture_output=True,text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which('node'), 'requires Node for browser JavaScript checks')
    def test_user_requests_show_scheduler_progress_without_conversation_text(self):
        script = r'''
const assert = require('node:assert/strict');
const html = require('node:fs').readFileSync('web/dashboard.html', 'utf8');
eval(html.slice(html.indexOf('function userRequestsHTML('), html.indexOf('function renderAgents(')));
assert.equal(userRequestsHTML({thoughts: {}}), '');
const text = userRequestsHTML({thoughts: {a: {agent:'user', owner:'private/secret', lane:0,
  reading:true, read:2048, prompt:4096, generated:0, content:'SECRET_PROMPT'},
  b: {agent:'user', owner:'user', lane:null}, c: {agent:'coin', content:'OTHER_SECRET'}}});
assert.match(text, /Private session/);
assert.match(text, /User session/);
assert.match(text, /Reading context/);
assert.match(text, /Waiting for GPU/);
assert.ok(!text.includes('SECRET'));
assert.ok(!text.includes('private/secret'));
eval(html.slice(html.indexOf('function activeClientCount('), html.indexOf('function renderAgents(')));
assert.equal(activeClientCount({agents:{}, thoughts:{a:{agent:'user',owner:'private/a'},b:{agent:'user',owner:'private/b'}}}), 2);
assert.equal(activeClientCount({agents:{a:{id:'a'}}, thoughts:{b:{agent:'a',owner:'task/a'}}}), 1);
'''
        subprocess.run(['node', '-e', script], check=True)

    @unittest.skipUnless(shutil.which('node'), 'requires Node for browser JavaScript checks')
    def test_cancel_on_supervisor_or_recovery_withdraws_the_originating_work(self):
        script = r'''
const assert = require('node:assert/strict');
const html = require('node:fs').readFileSync('web/dashboard.html', 'utf8');
eval(html.slice(html.indexOf('function cancellationTarget('), html.indexOf('// Each control gives')));
const L = {queue: {'p:work': {}}, tasks: {
  worker: {record: 'p:work'}, supervisor: {supervises: 'worker'},
  recovery: {repair_origin: {task: 'supervisor'}}, review: {worker: 'worker'},
  direct: {}, cycle: {supervises: 'cycle'}}};
for (const id of ['p:work', 'worker', 'supervisor', 'recovery', 'review']) {
  assert.equal(cancellationTarget(L, id), 'p:work');
}
assert.equal(cancellationTarget(L, 'direct'), 'direct');
assert.equal(cancellationTarget(L, 'cycle'), 'cycle');
delete L.queue['p:work'];
assert.equal(cancellationTarget(L, 'recovery'), 'recovery');
'''
        subprocess.run(['node', '-e', script], cwd=Path(__file__).resolve().parents[1],
                       check=True, timeout=10, capture_output=True, text=True)

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
  const frame = {memory: {physical_gb: gb(128), available_gb: gb(63)},
    models: {loaded: {up: true}, unloaded: {up: false}},
    model_memory: {loaded: {weights_gb: gb(20), memory_gb: gb(30), weights_reclaimable: reclaimable},
      unloaded: {weights_gb: 40, memory_gb: 60, weights_reclaimable: false}}, saved_bytes: 5 * 2 ** 30};
  const values = Array.from(context.memoryValues(frame));
  values.forEach((v,i) => assert.ok(Math.abs(v - [30,20,10,5,63][i]) < 1e-9));
  assert.equal(values.reduce((a, b) => a + b, 0), 128);
  context.renderMemory(frame);
  assert.equal(tileParts.b.textContent, '51%');
  assert.equal(tileParts.small.textContent, '65 of 128 GB');
  assert.equal(elements['mem-value'].textContent, '65 GB');
}
const mixed = {memory: {physical_gb: gb(128), available_gb: gb(63)},
  models: {gufo: {up: true}, llama: {up: true}}, saved_bytes: 5 * 2 ** 30,
  model_memory: {gufo: {weights_gb: gb(10), memory_gb: gb(15), weights_reclaimable: false},
    llama: {weights_gb: gb(10), memory_gb: gb(15), weights_reclaimable: true}}};
Array.from(context.memoryValues(mixed)).forEach((v,i) => assert.ok(Math.abs(v - [30,20,10,5,63][i]) < 1e-9));
// The reported Flash case must never enlarge a 128-GiB machine to 168 GB.
const flash = {memory: {physical_gb: gb(128), available_gb: gb(25)},
  models: {flash: {up: true}}, saved_bytes: .6 * 2 ** 30,
  model_memory: {flash: {weights_gb: 68.5, memory_gb: 69.5, weights_reclaimable: true}}};
for (const available of [25, 90, 128]) {
  flash.memory.available_gb = gb(available);
  const values = Array.from(context.memoryValues(flash));
  assert.ok(values.every(v => v >= 0));
  assert.ok(Math.abs(values.reduce((a,b) => a+b,0) - 128) < 1e-9);
  assert.ok(Math.abs(values[4] - available) < 1e-9);
}

'''
        subprocess.run(['node', '-e', script], cwd=Path(__file__).resolve().parents[1],
                       check=True, timeout=10, capture_output=True, text=True)

    @unittest.skipUnless(shutil.which('node'), 'requires Node for browser JavaScript checks')
    def test_focused_default_chooser_tracks_the_active_model_without_rebuilding_options(self):
        script = r'''
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const html = fs.readFileSync('web/dashboard.html', 'utf8');
const input = {dataset: {}, value: 'old'}, status = {}, unavailable = {}, unavailableList = {};
let writes = 0;
const context = {$: id => ({'default-model': input, 'default-model-status': status, 'model-unavailable': unavailable, 'model-unavailable-list': unavailableList})[id],
  document: {activeElement: input}, esc: s => s, assistant: () => 'Coin',
  setHTML: (element, value) => {element.innerHTML = value; if (element === input) writes++;}};
vm.createContext(context);
vm.runInContext(html.slice(html.indexOf('let MODEL_CHOICES'), html.indexOf('$("default-model").addEventListener')), context);
vm.runInContext('MODEL_CHOICES = [{id:"lemonade:Flash",name:"Flash",available:true}];', context);
context.renderDefaultModel({model: 'Flash', path: 'lemonade:Flash', phase: 'ready'});
assert.equal(input.value, 'lemonade:Flash');
assert.equal(input.disabled, false);
context.renderDefaultModel({model: 'Flash', path: 'lemonade:Flash', phase: 'ready'});
assert.equal(writes, 1);
vm.runInContext('MODEL_CHOICES.push({id:"normal",name:"Qwen3.8-27B-UD-Q4_K_XL",available:true}, {id:"broken",name:"unsupported",available:false,reason:"No recipe"});', context);
context.renderDefaultModel({model: 'Flash', path: 'lemonade:Flash', phase: 'ready'});
assert.ok(input.innerHTML.indexOf('Standard') < input.innerHTML.indexOf('Flash'));
assert.ok(input.innerHTML.includes('Qwen 3.8 27B · Standard · Q4_K_XL'));
assert.ok(!input.innerHTML.includes('unsupported'));
assert.equal(unavailable.hidden, false);
assert.ok(unavailableList.innerHTML.includes('No recipe'));
assert.equal(input.value, 'lemonade:Flash');
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
      renderScheduler: () => {},
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


class OperatorPreview(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'requires Node for browser JavaScript checks')
    def test_scrolled_snapshot_stays_fixed_until_return_to_live(self):
        script = r"""
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const html = fs.readFileSync('web/dashboard.html', 'utf8');
const output = {dataset: {}, innerHTML: ''}, events = {}, button = {hidden: true};
let top = 0;
const viewport = {firstElementChild: output, clientHeight: 100, setAttribute() {}, focus() {},
  addEventListener: (kind, fn) => events[kind] = fn,
  get scrollHeight() { return Math.max(100, output.innerHTML.length); },
  get scrollTop() { return top; }, set scrollTop(value) { top = Math.max(0, Math.min(value, this.scrollHeight - 100)); }};
const wrap = {querySelector: name => name === '.live' ? viewport : button};
const context = {setHTML: (el, value) => { el.innerHTML = value; }};
vm.createContext(context);
vm.runInContext(html.slice(html.indexOf('function updateLivePreview('), html.indexOf('// Balance rows')), context);
context.updateLivePreview(wrap, 'a'.repeat(1000));
assert.equal(top, 900);
viewport.scrollTop = 300; events.scroll();
assert.equal(button.hidden, false);
context.updateLivePreview(wrap, 'b'.repeat(1500));
assert.equal(output.innerHTML, 'a'.repeat(1000), 'stream updates preserve the snapshot being read');
assert.equal(top, 300);
context.updateLivePreview(wrap, '');
assert.equal(output.innerHTML, 'a'.repeat(1000), 'a cleared stream preserves the snapshot too');
context.updateLivePreview(wrap, 'latest'.repeat(300));
button.onclick({preventDefault() {}, stopPropagation() {}});
assert.equal(output.innerHTML, 'latest'.repeat(300));
assert.equal(top, 1700);
assert.equal(button.hidden, true);
context.updateLivePreview(wrap, 'newest'.repeat(400));
assert.equal(top, 2300, 'live following resumes');
"""
        subprocess.run(['node', '-e', script], cwd=Path(__file__).resolve().parents[1],
                       check=True, capture_output=True, text=True, timeout=10)


class WorkflowStages(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'requires Node for browser JavaScript checks')
    def test_mapping_review_authorship_and_artifact_review_stay_distinct(self):
        script = r"""
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const html = fs.readFileSync('web/dashboard.html', 'utf8');
const elements = {workflow: {}, flow: {}};
const context = {assert, elements, console, ROUTE: {project: 'p'}, $: id => elements[id], esc: value => String(value ?? ''), ago: () => '1m',
  setHTML: (el, value) => el.innerHTML = value};
vm.createContext(context);
const source = html.slice(html.indexOf('const WORKFLOW_STAGES'), html.indexOf('// One card per registered project'));
vm.runInContext(source + `
const state = {queue: {
 'p:map-pipeline-tests': {project:'p', item:'map-pipeline-tests', kind:'command', status:'done', depends:[]},
 'p:review-pipeline-test-map': {project:'p', item:'review-pipeline-test-map', kind:'command', status:'queued', depends:['map-pipeline-tests']},
 'p:scenario': {project:'p', item:'scenario', kind:'queued', stage:'test-contract', status:'queued', depends:['review-pipeline-test-map']},
 'p:packet': {project:'p', item:'packet', kind:'queued', stage:'test-contract', status:'queued', depends:[]},
 'p:held': {project:'p', item:'held', kind:'queued', stage:'implementation', status:'queued', depends:[]}
}, tasks: {
 'p:map-pipeline-tests': {id:'p:map-pipeline-tests',kind:'breakdown',role:'manager',place:'p',title:'map-pipeline-tests',status:'done'},
 'p:review-pipeline-test-map': {id:'p:review-pipeline-test-map',kind:'breakdown',role:'manager',place:'p',title:'review-pipeline-test-map',status:'running'},
 'p:packet': {id:'p:packet',kind:'item',role:'worker',stage:'test-contract',place:'p',title:'packet',status:'review'},
 'p:integrator': {id:'p:integrator',kind:'integrate',role:'integrator',worker:'p:packet',status:'running'},
 'p:held': {id:'p:held',kind:'item',role:'worker',stage:'implementation',place:'p',status:'waiting',admission_hold:'paused by user'}
}};
FLOW = computeFlow(state);
assert.equal(FLOW.items.get('p:review-pipeline-test-map').step, 'building');
assert.equal(workflowPosition(FLOW.items.get('p:review-pipeline-test-map')), 'map-review');
assert.equal(FLOW.items.get('p:scenario').step, 'blocked');
assert.equal(workflowPosition(FLOW.items.get('p:scenario')), 'test-contract');
assert.equal(workflowPosition(FLOW.items.get('p:packet')), 'test-review');
assert.equal(FLOW.items.get('p:held').step, 'blocked');
assert.equal(landedKind(FLOW.items.get('p:map-pipeline-tests')), 'test-mapping');
assert.equal(workflowStage({role:'manager',brief:'Workflow stage: map-review',title:'custom-title'}), 'map-review');
assert.ok(stageBadge(state.tasks['p:review-pipeline-test-map']).includes('Review test map'));
assert.ok(stageBadge(state.tasks['p:integrator'],state.tasks['p:packet']).includes('Review tests'));
renderFlow(state);
assert.equal((elements.workflow.innerHTML.match(/data-workflow=/g) || []).length, 9);
for (const stage of WORKFLOW_STAGES) assert.ok(elements.workflow.innerHTML.includes(stage[1]), stage[1]);
assert.ok(elements.flow.innerHTML.includes('Review map'));
`, context);
"""
        subprocess.run(['node', '-e', script], cwd=Path(__file__).resolve().parents[1],
                       check=True, capture_output=True, text=True, timeout=10)
