"""Stations bound where an agent works and what it reaches; repeating wakes fire once per occurrence."""
from datetime import datetime
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from cointos import api, coin, cron, opencode, prompts, stations, tasks, wakeups
from cointos.config import ROOT
from tests import support


def at(text, zone='Pacific/Auckland'):
    return datetime.fromisoformat(text).replace(tzinfo=ZoneInfo(zone)).timestamp()


def local(instant, zone='Pacific/Auckland'):
    return datetime.fromtimestamp(instant, ZoneInfo(zone)).strftime('%a %Y-%m-%d %H:%M')


class Cron(unittest.TestCase):
    def test_weekdays_at_six_skip_the_weekend(self):
        friday_evening = at('2026-11-06T18:00:00')
        self.assertEqual(local(cron.after('0 18 * * 1-5', 'Pacific/Auckland', friday_evening)), 'Mon 2026-11-09 18:00')

    def test_wall_clock_holds_across_daylight_saving(self):
        # New Zealand moves to daylight time on 2026-09-27.
        first = cron.after('0 18 * * *', 'Pacific/Auckland', at('2026-09-26T18:00:00'))
        second = cron.after('0 18 * * *', 'Pacific/Auckland', first)
        self.assertEqual((local(first), local(second)), ('Sun 2026-09-27 18:00', 'Mon 2026-09-28 18:00'))
        self.assertEqual(second - first, 86400)
        self.assertEqual(first - at('2026-09-26T18:00:00'), 86400 - 3600)

    def test_a_skipped_time_runs_once_after_the_change_and_a_repeated_time_once(self):
        skipped = cron.after('30 2 * * *', 'Pacific/Auckland', at('2026-09-26T12:00:00'))
        self.assertEqual(local(skipped), 'Sun 2026-09-27 03:30')
        repeated = cron.after('30 2 * * *', 'Pacific/Auckland', at('2026-04-04T12:00:00'))
        self.assertEqual(cron.after('30 2 * * *', 'Pacific/Auckland', repeated)- repeated, 86400 + 3600)

    def test_syntax(self):
        after = lambda expression: local(cron.after(expression, 'UTC', at('2026-11-02T00:00:00', 'UTC')), 'UTC')
        self.assertEqual(after('*/15 9 * * *'), 'Mon 2026-11-02 09:00')
        self.assertEqual(after('0 0 1 * *'), 'Tue 2026-12-01 00:00')
        self.assertEqual(after('0 12 * * sun'), 'Sun 2026-11-08 12:00')
        self.assertEqual(after('0 12 * * 7'), 'Sun 2026-11-08 12:00')
        self.assertEqual(after('0 12 13 * fri'), 'Fri 2026-11-06 12:00', 'restricted day fields combine with or')
        self.assertEqual(after('0 0 29 2 *'), 'Tue 2028-02-29 00:00')
        for bad in ('* * * *', '60 * * * *', '0 0 31 2 *', 'x * * * *', '*/0 * * * *', '5-1 * * * *'):
            with self.assertRaises(ValueError, msg=bad):
                cron.after(bad, 'UTC', 0)


class RepeatingWakes(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store = self.root / 'wakes'
        self.store.mkdir(mode=0o700)
        self.now = at('2026-11-02T12:00:00')
        self.enterContext(patch.object(wakeups, 'clock', side_effect=lambda: self.now))

    def schedule(self, **fields):
        return wakeups.create(self.store, 1, -5, 'Weekly', {'kind': 'schedule', 'cron': '0 18 * * 1-5',
                                                            'timezone': 'Pacific/Auckland'}, **fields)

    def test_a_schedule_refires_and_rearms_after_each_acknowledgement(self):
        record = self.schedule()
        self.assertTrue(record['next_run'].startswith('2026-11-02T18:00:00+13:00'))
        self.assertEqual(wakeups.ready(self.store), [])
        self.now = at('2026-11-02T18:00:00')
        event = wakeups.ready(self.store)[0]
        self.assertIn('2026-11-02T18:00:00+13:00', event['event']['detail'])
        self.assertEqual(wakeups.ready(self.store), [event], 'replays until acknowledged')
        self.assertTrue(wakeups.ack(self.store, 1, record['id'], {'task': 'system:operator-x-1'}))
        self.assertEqual(wakeups.ready(self.store), [])
        saved = wakeups.list(self.store, 1)[0]
        self.assertEqual((saved['runs'], saved['last_run']['task']), (1, 'system:operator-x-1'))
        self.assertTrue(saved['next_run'].startswith('2026-11-03T18:00:00'))

    def test_downtime_collapses_missed_occurrences_and_names_the_scheduled_time(self):
        record = self.schedule()
        self.now = at('2026-11-06T09:00:00')
        events = wakeups.ready(self.store)
        self.assertEqual(len(events), 1)
        self.assertIn('2026-11-02T18:00', events[0]['event']['detail'])
        wakeups.ack(self.store, 1, record['id'])
        self.assertTrue(wakeups.list(self.store, 1)[0]['next_run'].startswith('2026-11-06T18:00'))

    def test_the_registry_survives_reload_and_rejects_damage(self):
        self.schedule()
        self.assertEqual(len(wakeups.list(Path(str(self.store)), 1)), 1)
        data = json.loads((self.store / 'wakeups.json').read_text())
        next(iter(data['wakeups'].values())).pop('cursor')
        (self.store / 'wakeups.json').write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            wakeups.list(self.store, 1)

    def test_pause_drops_the_pending_occurrence_and_resume_counts_only_later_ones(self):
        record = self.schedule()
        wakeups.pause(self.store, 1, record['id'], True)
        self.now = at('2026-11-04T18:30:00')
        self.assertEqual(wakeups.ready(self.store), [])
        resumed = wakeups.pause(self.store, 1, record['id'], False)
        self.assertTrue(resumed['next_run'].startswith('2026-11-05T18:00'))
        self.assertEqual(wakeups.ready(self.store), [])
        once = wakeups.create(self.store, 1, -5, 'Once', {'kind': 'deadline', 'after_seconds': 5})
        with self.assertRaises(ValueError):
            wakeups.pause(self.store, 1, once['id'], True)

    def test_cancel_ends_a_repeating_wake(self):
        record = self.schedule()
        self.assertTrue(wakeups.cancel(self.store, 1, record['id']))
        self.assertEqual(wakeups.list(self.store, 1), [])

    def test_a_unit_change_fires_on_the_transition_not_while_the_state_holds(self):
        state = {'LoadState': 'loaded', 'ActiveState': 'failed'}
        with patch.object(wakeups, 'unit_state', side_effect=lambda unit: dict(state)):
            record = wakeups.create(self.store, 1, -5, 'Look', {'kind': 'unit-change', 'unit': 'a.service', 'state': 'failed'})
            self.assertEqual(wakeups.ready(self.store), [], 'already failed at registration is not a change')
            state['ActiveState'] = 'active'
            self.assertEqual(wakeups.ready(self.store), [])
            state['ActiveState'] = 'failed'
            self.assertEqual(len(wakeups.ready(self.store)), 1)
            wakeups.ack(self.store, 1, record['id'])
            self.assertEqual(wakeups.ready(self.store), [], 're-arming does not refire on a held state')

    def test_a_task_change_sees_each_new_task_and_ignores_its_own_agents(self):
        ledger = {'old': {'status': 'failed', 'place': 'p'}}
        with patch.object(wakeups, 'task_records', side_effect=lambda: dict(ledger)):
            record = wakeups.create(self.store, 1, -5, 'Look', {'kind': 'task-change', 'state': 'failed', 'project': 'p'})
            self.assertEqual(wakeups.ready(self.store), [])
            ledger['other'] = {'status': 'failed', 'place': 'q'}
            ledger['mine'] = {'status': 'failed', 'place': 'p', 'occurrence': 'x'}
            self.assertEqual(wakeups.ready(self.store), [])
            ledger['new'] = {'status': 'failed', 'place': 'p'}
            self.assertIn('new', wakeups.ready(self.store)[0]['event']['detail'])
            wakeups.ack(self.store, 1, record['id'])
            self.assertEqual(wakeups.ready(self.store), [])

    def test_a_path_change_watches_a_file_or_a_directory_listing(self):
        folder = self.root / 'inbox'
        folder.mkdir()
        record = wakeups.create(self.store, 1, -5, 'Look', {'kind': 'path-change', 'path': str(folder)})
        self.assertEqual(wakeups.ready(self.store), [])
        (folder / 'a').write_text('1')
        self.assertEqual(len(wakeups.ready(self.store)), 1)
        wakeups.ack(self.store, 1, record['id'])
        self.assertEqual(wakeups.ready(self.store), [])
        (folder / 'a').unlink()
        self.assertEqual(len(wakeups.ready(self.store)), 1)

    def test_one_shot_records_are_unchanged(self):
        record = wakeups.create(self.store, 1, -5, 'Once', {'kind': 'deadline', 'after_seconds': 0})
        self.assertEqual(set(record), {'id', 'user', 'chat', 'message', 'condition', 'created_at'})
        wakeups.ready(self.store)
        wakeups.ack(self.store, 1, record['id'])
        self.assertEqual(wakeups.list(self.store, 1), [])


class WakeAgents(unittest.TestCase):
    wake = {'id': 'a' * 32, 'message': 'Report', 'agent': {'name': 'report', 'brief': 'Do it.', 'station': {'directory': '~/x'}},
            'event': {'at': 5.0, 'detail': 'Scheduled for 2026-11-02T18:00:00+13:00.'}}

    def test_the_agent_starts_with_its_trigger_and_a_replay_key(self):
        with patch.object(coin, 'call', return_value={'ok': True, 'task': 'system:operator-report-1'}) as called:
            self.assertEqual(coin.start_wake_agent(self.wake), {'task': 'system:operator-report-1'})
        action, body = called.call_args.args
        self.assertEqual(action, 'run-agent')
        self.assertEqual(body['occurrence'], 'a' * 32 + ':5.0')
        self.assertIn('2026-11-02T18:00', body['brief'])
        self.assertEqual(body['station'], {'directory': '~/x'})

    def test_a_refusal_is_returned_but_an_unreachable_daemon_retries(self):
        with patch.object(coin, 'call', side_effect=ValueError('gone')):
            self.assertEqual(coin.start_wake_agent(self.wake), {'refused': 'gone'})
        with patch.object(coin, 'call', side_effect=coin.Unreachable('down')), self.assertRaises(coin.Unreachable):
            coin.start_wake_agent(self.wake)

    def test_a_bad_agent_is_refused_at_registration(self):
        with tempfile.TemporaryDirectory() as root, patch.object(coin, 'COIN_STATE', Path(root)), \
                patch.object(coin, 'call', side_effect=ValueError('unknown station tools')):
            (Path(root) / 'wakes').mkdir(mode=0o700)
            with self.assertRaisesRegex(ValueError, 'unknown station tools'):
                coin.wake_tool('wake', {'message': 'm', 'condition': {'kind': 'schedule', 'cron': '0 18 * * *'},
                                        'agent': {'name': 'r', 'brief': 'b'}}, 1, -5)
            self.assertEqual(wakeups.list(Path(root) / 'wakes', 1), [])

    def test_the_conversation_originals_reach_the_saved_brief(self):
        with patch.object(coin, 'wake_tool', return_value={'ok': True}) as saved:
            coin.invoke('wake', {'message': 'm', 'condition': {}, 'agent': {'name': 'r', 'brief': 'b'}}, 't', 1, -5, None,
                        inputs=[{'id': 7, 'text': 'every weekday please'}])
        self.assertIn('every weekday please', saved.call_args.args[1]['agent']['brief'])


class WorkerFiring(unittest.TestCase):
    """The service loop: a fired wake with an agent needs no model, and re-arms."""

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(coin, 'COIN_STATE', self.root))
        self.enterContext(patch.object(coin.kt_mcp, 'open_session', return_value=None))
        self.enterContext(patch.object(coin, 'report'))
        self.enterContext(patch.object(coin.traceback, 'print_exc'))
        self.model = self.enterContext(patch.object(coin, 'turn'))
        self.now = at('2026-11-02T12:00:00')
        self.enterContext(patch.object(wakeups, 'clock', side_effect=lambda: self.now))
        self.wake = wakeups.create(self.root / 'wakes', 7, 70, 'Weekly report',
                                   {'kind': 'schedule', 'cron': '0 18 * * 1-5', 'timezone': 'Pacific/Auckland'},
                                   {'name': 'report', 'brief': 'Do it.'})
        self.now = at('2026-11-02T18:00:00')

    def run_worker(self):
        inbox = Mock()
        inbox.get.side_effect = [queue.Empty(), KeyboardInterrupt()]
        with self.assertRaises(KeyboardInterrupt):
            coin.worker('token', inbox, {7})

    def saved(self):
        return wakeups.list(self.root / 'wakes', 7)[0]

    def test_it_starts_the_agent_without_a_model_turn_and_rearms(self):
        with patch.object(coin, 'call', return_value={'ok': True, 'task': 'system:operator-report-1'}) as called:
            self.run_worker()
        self.model.assert_not_called()
        self.assertEqual(called.call_args.args[0], 'run-agent')
        self.assertEqual((self.saved()['runs'], self.saved()['last_run']['task']), (1, 'system:operator-report-1'))
        self.assertTrue(self.saved()['next_run'].startswith('2026-11-03T18:00'))

    def test_a_previous_run_still_going_is_recorded_not_doubled(self):
        with patch.object(coin, 'call', return_value={'ok': True, 'task': 't', 'already_running': True}):
            self.run_worker()
        self.model.assert_not_called()
        self.assertTrue(self.saved()['last_run']['already_running'])

    def test_a_refusal_tells_the_user_through_a_model_turn_and_keeps_the_schedule(self):
        with patch.object(coin, 'call', side_effect=ValueError('station directory does not exist')):
            self.run_worker()
        self.assertIn('station directory does not exist', self.model.call_args.kwargs['wake']['message'])
        self.assertEqual(self.saved()['runs'], 1)
        self.assertIn('refused', self.saved()['last_run'])

    def test_an_unreachable_daemon_keeps_the_occurrence_pending(self):
        with patch.object(coin, 'call', side_effect=coin.Unreachable('down')):
            self.run_worker()
        self.model.assert_not_called()
        self.assertEqual(self.saved()['runs'], 0)
        self.assertIn('event', self.saved())


class CoinStation(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        server = self.root / 'server.py'
        server.write_text("""
import json, sys, time
for line in sys.stdin:
    m = json.loads(line)
    if 'id' not in m: continue
    if m['method'] == 'initialize': r = {'instructions': ''}
    elif m['method'] == 'tools/list': r = {'tools': [{'name': 'echo', 'description': 'd'}, {'name': 'slow'}]}
    else:
        if m['params']['name'] == 'slow': time.sleep(60)
        r = {'content': [{'type': 'text', 'text': json.dumps(m['params']['arguments'])}]}
    print(json.dumps({'jsonrpc': '2.0', 'id': m['id'], 'result': r}), flush=True)
""")
        config = self.root / 'opencode.json'
        config.write_text(json.dumps({'mcp': {
            'knowledgetrees': {'type': 'local', 'command': ['false']},
            'demo': {'type': 'local', 'command': [sys.executable, str(server)], 'timeout': 300},
            'hosted': {'type': 'remote', 'url': 'https://example.invalid'}}}))
        self.enterContext(patch.object(stations, 'GLOBAL_CONFIG', config))
        self.addCleanup(self.close_sessions)

    def close_sessions(self):
        for session in coin.MCP_SESSIONS.values():
            session['process'].kill()
            coin.kt_mcp.close(session)
            session['process'].stdout.close()
        coin.MCP_SESSIONS.clear()

    def test_coin_reaches_every_configured_server_except_kts_withheld_route(self):
        self.assertEqual(coin.mcp_tools({})['servers'], ['demo', 'hosted'])
        self.assertEqual([t['name'] for t in coin.mcp_tools({'server': 'demo'})['tools']], ['echo', 'slow'])
        self.assertEqual(coin.mcp_call({'server': 'demo', 'tool': 'echo', 'arguments': {'a': 1}}), {'ok': True, 'output': '{"a": 1}'})
        for server in ('knowledgetrees', 'absent', 'hosted'):
            with self.assertRaises(ValueError, msg=server):
                coin.mcp_call({'server': server, 'tool': 'x'})

    def test_a_hung_tool_is_bounded_and_the_server_comes_back(self):
        with self.assertRaises(RuntimeError):
            coin.mcp_call({'server': 'demo', 'tool': 'slow'})
        self.assertTrue(coin.mcp_call({'server': 'demo', 'tool': 'echo'})['ok'])


class Stations(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self, {'paused': False})
        support.quiet(self)
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.desk = self.root / 'desk'
        self.desk.mkdir()
        self.project = support.project(self, support.repository(self, 'owner'))
        config = self.root / 'opencode.json'
        config.write_text(json.dumps({'mcp': {
            'knowledgetrees': {'type': 'local', 'command': ['kt'], 'enabled': True},
            'mail': {'type': 'local', 'command': ['mail'], 'enabled': True},
            'cad': {'type': 'local', 'command': ['cad'], 'enabled': True}}}))
        self.enterContext(patch.object(stations, 'GLOBAL_CONFIG', config))

    def stationed(self, name='desk', **fields):
        return tasks.request_operator(name, 'Work.', None, None, None, None,
                                      station={'directory': str(self.desk), 'tools': ['mail']}, **fields)

    def enabled(self, task):
        servers = opencode.settings(tasks.CONFIG, 'key', task, [])['mcp']
        return {name for name, server in servers.items() if server.get('enabled')}

    def test_every_agent_has_a_station(self):
        factory = tasks.create('operator', self.project, 'operator-x', 'Work.', [1], abilities=['standard'])
        self.assertEqual(stations.of(factory), {'directory': factory['worktree'], 'tools': []})
        system = tasks.request_operator('sys', 'Work.', None, None, None, None)
        self.assertEqual(stations.of(system), {'directory': str(ROOT), 'tools': []})
        self.assertEqual(stations.of(self.stationed()), {'directory': str(self.desk), 'tools': ['mail']})
        self.assertEqual(stations.COIN, {'directory': str(Path.home()), 'tools': ['*']})

    def test_tools_enable_only_named_servers_and_star_enables_all(self):
        self.assertEqual(self.enabled(self.stationed()), {'mail', 'cointos'})
        everything = tasks.request_operator('all', 'Work.', None, None, None, None, station={'tools': ['*']})
        self.assertEqual(self.enabled(everything), {'mail', 'cad', 'cointos'})
        self.assertEqual(self.enabled(tasks.request_operator('none', 'Work.', None, None, None, None)), {'cointos'})

    def test_the_knowledge_server_stays_on_for_every_agent(self):
        servers = opencode.settings(tasks.CONFIG, 'key', self.stationed(), [])['mcp']
        self.assertNotIn('knowledgetrees', servers, 'it inherits the enabled global definition')

    def test_requests_are_refused_with_what_would_work(self):
        with self.assertRaisesRegex(ValueError, r"configured: \['cad', 'mail'\]"):
            tasks.request_operator('a', 'Work.', None, None, None, None, station={'tools': ['nope']})
        with self.assertRaisesRegex(ValueError, 'does not exist'):
            tasks.request_operator('a', 'Work.', None, None, None, None, station={'directory': str(self.root / 'nope')})
        with self.assertRaisesRegex(ValueError, 'absolute'):
            tasks.request_operator('a', 'Work.', None, None, None, None, station={'directory': 'relative'})
        with self.assertRaisesRegex(ValueError, 'not both'):
            tasks.request_operator('a', 'Work.', self.project['name'], None, None, None, station={'directory': str(self.desk)})
        with self.assertRaisesRegex(ValueError, 'control'):
            tasks.request_operator('a', 'Work.', None, ['control'], None, None, station={'directory': str(self.desk)})

    def test_a_check_validates_without_creating(self):
        before = dict(tasks.L['tasks'])
        self.assertEqual(api.run_agent({'name': 'a', 'brief': 'b', 'check_only': True,
                                        'station': {'directory': str(self.desk)}}), {'ok': True})
        self.assertEqual(tasks.L['tasks'], before)

    def test_a_stationed_agent_is_confined_and_told_where_it_is(self):
        task = self.stationed()
        self.assertTrue(opencode.confined_writes(task))
        permission = opencode.settings(tasks.CONFIG, 'key', task, [])['permission']
        self.assertEqual(permission['edit'], {'*': 'deny', f'{self.desk}/**': 'allow'})
        self.assertIsNone(task['branch'])
        text = prompts.location(task, tasks.place(task))
        self.assertIn(str(self.desk), text)
        self.assertIn('mail', text)
        self.assertFalse(opencode.confined_writes(tasks.request_operator('sys', 'Work.', None, None, None, None)))

    def test_a_system_operators_prompt_is_unchanged(self):
        task = tasks.request_operator('sys', 'Work.', None, None, None, None)
        self.assertEqual(prompts.location(task, tasks.place(task)),
                         f"Scope: the installed CointOS runtime ({task['worktree']}) and the explicitly named accessible paths. "
                         'This is a system task with no project, branch or worktree.')

    def test_landlock_confines_writes_to_a_non_git_station(self):
        task = self.stationed()
        run = self.root / 'run'
        run.mkdir()
        with patch.object(opencode.kt, 'prepare'), patch.object(opencode, 'STATE', self.root):
            paths = opencode.write_paths(task, run)
        # The temporary directories are writable for every confined agent, so test outside them.
        outside = Path(self.enterContext(tempfile.TemporaryDirectory(dir=Path.home()))) / 'outside'
        script = (f"from pathlib import Path\nPath({str(self.desk / 'ok')!r}).write_text('1')\n"
                  f"try:\n Path({str(outside)!r}).write_text('1')\nexcept PermissionError: print('denied')\n")
        result = subprocess.run([sys.executable, str(Path(opencode.__file__).with_name('worktree_guard.py')), json.dumps(paths),
                                 sys.executable, '-c', script], capture_output=True, text=True)
        self.assertEqual(result.stdout.strip(), 'denied', result.stderr)
        self.assertTrue((self.desk / 'ok').exists())
        self.assertFalse(outside.exists())

    def test_an_occurrence_starts_once_and_never_overlaps_its_previous_run(self):
        first = self.stationed(occurrence='w:1')
        self.assertIs(self.stationed(occurrence='w:1'), first, 'a replay returns the same task')
        answer = api.run_agent({'name': 'desk', 'brief': 'b', 'occurrence': 'w:2', 'station': {'directory': str(self.desk)}})
        self.assertEqual(answer, {'ok': True, 'task': first['id'], 'already_running': True})
        with self.assertRaisesRegex(ValueError, 'already active'):
            self.stationed()

    def test_a_stationed_agent_cannot_widen_what_it_spawns(self):
        parent = support.running(self.stationed(), 'run-1', worktree=False)
        agent = tasks.L['agents']['run-1']
        budget = {'generation_seconds': 1, 'generation_tokens': 1}
        child = tasks.request_operator('child', 'Work.', None, None, None, budget, (parent, agent))
        self.assertEqual(child['worktree'], str(self.desk), 'no directory given stays home')
        self.assertTrue(opencode.confined_writes(child))
        with self.assertRaisesRegex(ValueError, 'no station tool'):
            tasks.request_operator('x', 'Work.', None, None, None, budget, (parent, agent), station={'tools': ['cad']})
        with self.assertRaisesRegex(ValueError, 'inside'):
            tasks.request_operator('x', 'Work.', None, None, None, budget, (parent, agent), station={'directory': str(self.root)})

    def test_a_settled_stationed_agent_leaves_its_directory_alone(self):
        (self.desk / 'keep').write_text('1')
        task = self.stationed()
        task['status'] = 'done'
        from cointos import lifecycle
        self.assertFalse(lifecycle.retire(task))
        self.assertTrue((self.desk / 'keep').exists())


if __name__ == '__main__':
    unittest.main()
