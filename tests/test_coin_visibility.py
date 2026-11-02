"""Coin's dashboard card, activity panel and viewer data."""
import os
import shutil
import subprocess
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from cointos import api, cli, coin, gateway, state, viewers, wakeups
from tests import support


class CoinVisibility(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self)
        support.quiet(self)

    def test_reports_turns_tools_and_live_worker_for_the_card_and_panel(self):
        pid = os.getpid()
        with patch.object(api, 'now', side_effect=[100, 101, 105]):
            api.dispatch('coin', {'busy': True, 'pid': pid})
            api.dispatch('coin', {'busy': True, 'doing': 'status', 'pid': pid})
            api.dispatch('coin', {'busy': False, 'pid': pid})
        coin = state.L['coin']
        self.assertEqual((coin['turns'], coin['last_turn_seconds'], coin['last_turn_at']), (1, 5, 105))
        self.assertEqual(coin['worker_since'], 100)
        self.assertIsNone(coin['turn_started_at'])
        self.assertEqual([entry['event'] for entry in coin['recent']],
                         ['turn started', 'tool', 'turn ended'])
        self.assertEqual(coin['recent'][1]['detail'], 'status')
        view = gateway.coin_view()
        self.assertTrue(view['alive'])
        self.assertEqual(view['model'], state.CONFIG['work_model'])

    def test_trigger_names_what_started_coin_and_persists_as_last_trigger(self):
        pid = os.getpid()
        with patch.object(api, 'now', side_effect=[100, 110]):
            api.dispatch('coin', {'busy': True, 'trigger': 'Issuing a reminder', 'pid': pid})
            api.dispatch('coin', {'busy': False, 'pid': pid})
        self.assertIsNone(state.L['coin']['trigger'])
        self.assertEqual(state.L['coin']['last_trigger'], 'Issuing a reminder')
        self.assertEqual(state.L['coin']['recent'][0]['trigger'], 'Issuing a reminder')
        self.assertEqual(coin.trigger_text(None, ['hello']), 'Answering a message')
        self.assertEqual(coin.trigger_text({'message': 'x', 'condition': {'kind': 'deadline'}}, []), 'Issuing a reminder')
        self.assertEqual(coin.trigger_text({'message': 'x', 'condition': {'kind': 'task-state', 'state': 'done'}}, []),
                         'Following up on finished work')
        self.assertEqual(coin.trigger_text({'message': 'x', 'condition': {'kind': 'process-exit'}}, []),
                         'Checking a process')

    def test_stale_or_missing_worker_is_offline_not_busy(self):
        state.L['coin'].update(busy=True, doing='status', process={
            'pid': 1234, 'start_ticks': 1, 'boot_id': 'fixture-boot'})
        with patch.object(gateway.wakeups, 'process', return_value=None):
            view = gateway.coin_view()
        self.assertFalse(view['alive'])
        self.assertFalse(view['busy'])
        self.assertIsNone(view['doing'])
        self.assertEqual(view['model'], state.CONFIG['work_model'])

    def test_status_and_coin_view_show_the_same_activity(self):
        state.L['coin'].update({
            'alive': True, 'busy': True, 'doing': 'run_command', 'turns': 7,
            'trigger': 'Following up',
            'worker_since': time.time() - 600, 'turn_started_at': time.time() - 65,
            'last_turn_at': time.time() - 300, 'last_turn_seconds': 42,
            'model': state.CONFIG['work_model'],
            'live': {'reasoning': 'Checking the queue.', 'content': ''},
            'recent': [{'at': time.time() - 60, 'event': 'turn started', 'turn': 7, 'trigger': 'Following up'},
                       {'at': time.time() - 50, 'event': 'tool', 'detail': 'run_command'}]})
        status = cli.status_text(state.L)
        self.assertIn('coin     Following up · tools · run_command · 7 turns', status)
        self.assertIn('Following up', cli.coin_banner(state.L))
        self.assertIn('7 turns', " ".join(cli.coin_header(state.L)))
        # A live thought wins over the retained tool name; the UI must not call this answering.
        state.L['thoughts']['thought'] = {
            'agent': 'coin', 'reading': False, 'generated': 12, 'rate': 3.0,
            'prompt': 100, 'read': 100, 'lane': 0, 'id': 'thought'}
        state.L['coin']['live'] = {'phase': 'writing', 'reasoning': '', 'content': 'Writing the reply.'}
        status = cli.status_text(state.L)
        self.assertIn('coin     Following up · writing · 7 turns', status)
        self.assertNotIn('answering', status.lower())
        self.assertIn('Coin · Following up · writing', cli.coin_banner(state.L))

    def test_coin_occupies_an_idle_viewer_slot_only_while_active(self):
        pid = os.getpid()
        native = wakeups.process(pid)
        state.L['coin'].update(busy=True, process={
            'pid': pid, 'start_ticks': native['start_ticks'], 'boot_id': wakeups.boot_id()})
        state.L['viewers'].clear()
        state.L['viewers_showing'] = True
        with patch.object(viewers, 'open_window') as opened:
            viewers.look_after(set())
        self.assertEqual(state.L['viewers'], {'0': 'coin'})
        self.assertTrue(opened.called)
        state.L['coin']['busy'] = False
        viewers.look_after({0})
        self.assertEqual(state.L['viewers'], {})


class CoinPanel(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'requires Node for browser JavaScript checks')
    def test_coin_panel_renders_busy_idle_and_offline_states(self):
        script = r'''
const assert = require('node:assert/strict');
const fs = require('node:fs');
const html = fs.readFileSync('web/dashboard.html', 'utf8');
const detail = {dataset: {}, innerHTML: ''};
const $ = id => id === 'coin-detail' ? detail : null;
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const short = m => String(m || '').replace(/-GGUF$/, '');
const duration = seconds => { const s = Math.floor(Math.max(0, seconds)); return s < 120 ? s + 's' : s < 7200 ? (s / 60 | 0) + 'm' : (s / 3600 | 0) + 'h'; };
const ago = t => duration(Date.now() / 1000 - t);
const setHTML = (el, value) => { el.innerHTML = value; };
const source = html.slice(html.indexOf('function renderCoinPanel'), html.indexOf('\n// The pipeline a work item'));
eval(source);
const now = Date.now() / 1000;
const busy = {coin: {alive: true, busy: true, doing: 'run_command', turns: 7, worker_since: now - 600,
  turn_started_at: now - 65, last_turn_at: now - 300, last_turn_seconds: 42, model: 'Qwen3.8-27B-GGUF',
  gpu_seconds: 5, process: {pid: 123}, live: {reasoning: 'Checking the queue.', content: ''},
  recent: [{at: now - 60, event: 'turn started', turn: 7}, {at: now - 50, event: 'tool', detail: 'run_command'}]},
  thoughts: {}};
renderCoinPanel(busy);
for (const text of ['Tools', 'run_command', '7', 'Last words', 'Checking the queue.', 'turn started', 'tool'])
  assert.ok(detail.innerHTML.includes(text), text);
renderCoinPanel({...busy, thoughts: {t: {agent: 'coin', generated: 423, rate: 18.4, reading: false, prompt: 100, read: 100}}});
assert.ok(detail.innerHTML.includes('Reasoning'));
assert.ok(detail.innerHTML.includes('Saying'));
assert.ok(detail.innerHTML.includes('423'));
assert.ok(!detail.innerHTML.includes('Tools'), 'a live thought must hide the retained tool state');
renderCoinPanel({coin: {alive: true, busy: false, turns: 2, last_turn_at: now - 30, model: 'm'}, thoughts: {}});
assert.ok(detail.innerHTML.includes('Idle'));
renderCoinPanel({coin: {alive: false, turns: 0}, thoughts: {}});
assert.ok(detail.innerHTML.includes('Offline'));
'''
        subprocess.run(['node', '-e', script], cwd=Path(__file__).resolve().parents[1],
                       check=True, timeout=10, capture_output=True, text=True)


class CoinMonitorReplay(unittest.TestCase):
    def test_reply_survives_tool_and_reconnect_at_narrow_terminal_width(self):
        from cointos.coin_view import Monitor
        from rich.console import Console
        import io
        monitor = Monitor()
        base = {'worker_since': 10, 'turns': 2, 'busy': True, 'alive': True,
                'model': 'Qwen', 'trigger': 'Answering a message'}
        monitor.update({'coin': {**base, 'live': {'content': '**Saved** the requested entry.'}}})
        monitor.update({'coin': {**base, 'doing': 'dispatch', 'live': {}}})
        monitor.update({'_error': 'Temporary disconnect'})
        output = io.StringIO()
        console = Console(file=output, width=52, color_system=None)
        console.print(monitor.render(52, 32))
        rendered = output.getvalue()
        self.assertIn('Saved', rendered)
        self.assertIn('dispatch', rendered)
        self.assertIn('Reconnecting', rendered)
        self.assertTrue(all(len(line) <= 52 for line in rendered.splitlines()))
        monitor.update({'coin': {**base, 'busy': False, 'live': {}}})
        self.assertIsNone(monitor.error)
        self.assertEqual(len(monitor.turns), 1)
