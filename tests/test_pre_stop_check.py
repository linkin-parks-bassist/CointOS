"""Typed pre-stop validation stays bounded and does not infer a task outcome."""
import copy
import io
import json
import queue
import unittest
from pathlib import Path
from unittest.mock import patch

from cointos import api, gateway, git, lanes, state
from tests import support


class PreStop(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self)
        support.quiet(self)
        self.project=support.project(self,support.repository(self))
        self.task=support.queued(self.project,'work')
        support.running(self.task,'worker')
        self.body={'tools':[{'type':'function','function':{'name':'cointos_check_work'}}]}
        self.final={'content':'All done.','reasoning':'','tool_calls':[],'phase':'writing'}

    def test_one_check_is_requested_without_accepting_the_claim(self):
        first=gateway.pre_stop_check(self.body,'worker',self.final)
        self.assertEqual(first['tool_calls'][0]['function'],{'name':'cointos_check_work','arguments':'{}'})
        self.assertEqual(self.task['status'],'running')
        self.assertIs(gateway.pre_stop_check(self.body,'worker',self.final),self.final)

    def test_real_calls_and_unmanaged_or_terminal_replies_are_unchanged(self):
        called={**self.final,'tool_calls':[{'id':'actual'}]}
        self.assertIs(gateway.pre_stop_check(self.body,'worker',called),called)
        self.assertIs(gateway.pre_stop_check(self.body,'coin',self.final),self.final)
        self.assertIs(gateway.pre_stop_check({**self.body,'tool_choice':'none'},'worker',self.final),self.final)
        for tools in ([],None,[None,{'type':'function','function':None}]):
            self.assertIs(gateway.pre_stop_check({'tools':tools},'worker',self.final),self.final)
        self.task['status']='done'
        self.assertIs(gateway.pre_stop_check(self.body,'worker',self.final),self.final)

    def test_dirty_worker_gets_a_concrete_problem_before_receipt(self):
        (Path(self.task['worktree'])/'artifact').write_text('not committed')
        result=api.check_work({'caller':{'task':self.task['id'],'run':'worker'}})
        self.assertFalse(result['ok'])
        self.assertFalse(result['worktree_clean'])
        self.assertTrue(result['completion_receipt_required'])
        self.assertTrue(any('uncommitted' in item for item in result['problems']))
        self.assertIn('artifact',result['worktree_status'])
        support.commit(self.task['worktree'])
        self.assertTrue(api.check_work({'caller':{'task':self.task['id'],'run':'worker'}})['ok'])
        self.assertEqual(self.task['status'],'running')

    def test_json_and_stream_replies_carry_executable_tool_identity(self):
        for stream in (False,True):
            state.L['agents']['worker'].pop('pre_stop_checked',None)
            q=queue.Queue();q.put([1]);q.put({'end':'done'})
            handler=gateway.Handler.__new__(gateway.Handler)
            handler.wfile=io.BytesIO()
            handler.peer_closed=lambda:False
            handler.send_response=lambda code:None
            handler.send_header=lambda *args:None
            handler.end_headers=lambda:None
            replies=[];handler.reply=lambda code,body:replies.append(body)
            with patch.dict(lanes.RUNS,{'fixture':{'queue':q}}), \
                    patch.object(gateway.BACKEND,'read',side_effect=lambda *args:copy.deepcopy(self.final)):
                handler.reply_thought({**self.body,'stream':stream},'worker',state.CONFIG['work_model'],
                                      {'tokens':[1,2],'reader':{}},'fixture')
            if stream:
                frames=[json.loads(line[6:]) for line in handler.wfile.getvalue().decode().splitlines()
                        if line.startswith('data: ') and line!='data: [DONE]']
                deltas=[frame['choices'][0]['delta'] for frame in frames]
                calls=[d['tool_calls'][0] for d in deltas if 'tool_calls' in d]
                self.assertEqual(calls[0]['function'],{'name':'cointos_check_work','arguments':'{}'})
                self.assertEqual(frames[-1]['choices'][0]['finish_reason'],'tool_calls')
            else:
                choice=replies[0]['choices'][0]
                self.assertEqual(choice['finish_reason'],'tool_calls')
                self.assertEqual(choice['message']['tool_calls'][0]['function']['name'],'cointos_check_work')

    def test_uncommitted_stage_violations_are_named_without_mutation(self):
        rules = {'manifest': 'tests/contracts.json', 'protected': ['tests/**', 'Makefile'],
                 'non_code': ['*.md', '.knowledge/**']}
        self.project['test_policy'] = rules
        root = Path(self.task['worktree'])
        (root / 'src').mkdir()
        (root / 'tests').mkdir()
        (root / 'src/code.c').write_text('baseline')
        (root / 'Makefile').write_text('baseline')
        (root / 'tests/contracts.json').write_text('[]')
        baseline = support.commit(root)
        git.publish(self.project['path'], 'main', baseline, self.task['base_commit'])
        for stage in ('test-contract', 'implementation'):
            with self.subTest(stage=stage):
                self.task['stage'] = stage
                (root / 'src/code.c').write_text('diagnostic production edit')
                (root / 'src/new.c').write_text('untracked production')
                (root / 'Makefile').unlink()
                (root / 'tests/new.py').write_text('untracked test')
                (root / 'notes.md').write_text('allowed non-code')
                git.run(root, 'add', 'src/code.c')
                before = git.run(root, 'status', '--porcelain=v1', '-z')
                result = api.check_work({'caller': support.caller(self.task, 'worker')})
                expected = ['src/code.c', 'src/new.c'] if stage == 'test-contract' else ['Makefile', 'tests/new.py']
                self.assertFalse(result['ok'])
                self.assertEqual(result['out_of_scope_paths'], expected)
                self.assertTrue(any('preserve diagnostic work separately' in p for p in result['problems']))
                self.assertEqual(git.run(root, 'status', '--porcelain=v1', '-z'), before)
                self.assertEqual(self.task['status'], 'running')
                self.assertIsNone(self.task['receipt'])
                git.run(root, 'restore', '--staged', 'src/code.c')
                git.run(root, 'restore', 'src/code.c', 'Makefile')
                for path in ('src/new.c', 'tests/new.py', 'notes.md'):
                    (root / path).unlink()

    def test_integrator_candidate_changes_are_informational(self):
        self.task['role']='integrator'
        state.L['agents']['worker']['role']='integrator'
        (Path(self.task['worktree'])/'candidate').write_text('reviewed candidate')
        result=api.check_work({'caller':{'task':self.task['id'],'run':'worker'}})
        self.assertTrue(result['ok'],result)
        self.assertFalse(result['worktree_clean'])
        self.assertIn('candidate',result['worktree_status'])
        self.assertTrue(result['completion_receipt_required'])

    def test_inspection_and_empty_commits_cannot_create_construction_review(self):
        for case in ('untouched','empty','reverted','report-only'):
            if case == 'empty':
                support.commit(self.task['worktree'],'inspection finished')
            elif case == 'reverted':
                artifact=Path(self.task['worktree'])/'artifact'
                artifact.write_text('temporary edit')
                support.commit(self.task['worktree'])
                artifact.unlink()
                support.commit(self.task['worktree'],'revert edit')
            elif case == 'report-only':
                (Path(self.task['worktree'])/'.work-report.md').write_text('Existing checks pass')
                support.commit(self.task['worktree'],'report without product artifact')
            checked=api.check_work({'caller':{'task':self.task['id'],'run':'worker'}})
            self.assertFalse(checked['ok'])
            self.assertTrue(any('no changed artifact' in p for p in checked['problems']))
            with self.assertRaisesRegex(ValueError,'no changed artifact'):
                api.finishing({'caller':{'task':self.task['id'],'run':'worker'},
                               'outcome':'complete','detail':'The existing suite passes'})
            self.assertEqual(self.task['status'],'running')
            self.assertIsNone(self.task['receipt'])
            self.assertFalse(self.task.get('validating'))
        with patch.object(api,'save'):
            result=api.finishing({'caller':{'task':self.task['id'],'run':'worker'},
                                 'outcome':'blocked','detail':'This assignment is inspection without a construction artifact'})
        self.assertEqual(result['receipt']['disposition'],'blocked')

    def test_real_artifact_already_on_main_can_still_submit_for_incorporation(self):
        (Path(self.task['worktree'])/'artifact').write_text('real authored change')
        commit=support.commit(self.task['worktree'])
        git.publish(self.project['path'],'main',commit,self.task['base_commit'])
        with patch.object(api,'save'):
            result=api.finishing({'caller':{'task':self.task['id'],'run':'worker'},
                                 'outcome':'complete','detail':'The authored artifact is already present on accepted main'})
        self.assertEqual(result['receipt']['evidence']['commit'],commit)
        self.assertEqual(self.task['status'],'review')

