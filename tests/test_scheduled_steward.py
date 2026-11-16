import tempfile
from pathlib import Path
import unittest
from cointos import api,lifecycle,prompts,state,tasks,wakeups
from tests import support

class ScheduledSteward(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self);support.quiet(self)

    def test_schedule_accepts_a_real_steward_and_keeps_its_role(self):
        with tempfile.TemporaryDirectory() as folder:
            record=wakeups.create(Path(folder),1,1,'Review runtime',
                {'kind':'schedule','cron':'0 */2 * * *','timezone':'Australia/Sydney'},
                {'role':'steward','name':'runtime-review','brief':'Inspect the last four hours.'})
            self.assertEqual(record['agent']['role'],'steward')
            self.assertEqual(wakeups.list(Path(folder),1)[0]['agent']['role'],'steward')

    def test_occurrence_replay_and_overlap_do_not_spawn_duplicate_stewards(self):
        body={'role':'steward','name':'runtime-review','brief':'Inspect logs','occurrence':'wake:initial'}
        first=api.run_agent(body)
        self.assertEqual(api.run_agent(body)['task'],first['task'])
        overlap=api.run_agent({**body,'occurrence':'wake:next'})
        self.assertEqual(overlap['task'],first['task'])
        self.assertTrue(overlap['already_running'])
        self.assertEqual(len(state.L['tasks']),1)
        state.L['tasks'][first['task']]['status']='done'
        self.assertNotEqual(api.run_agent({**body,'occurrence':'wake:next'})['task'],first['task'])

    def test_steward_can_dispatch_runtime_diagnosis_and_finish_checked_handoff(self):
        steward=tasks.create('steward',tasks.SYSTEM,'review','Inspect logs',[6])
        support.running(steward,'steward-run',worktree=False)
        brief='Diagnose the repeated 14:00-15:00 backend disconnects in runtime events; dispatch the scoped CointOS fix.'
        result=api.run_agent({'role':'first-responder','name':'backend-disconnects','brief':brief,
                             'caller':{'task':steward['id'],'run':'steward-run'}})
        responder=state.L['tasks'][result['task']]
        self.assertEqual(responder['role'],'first-responder')
        self.assertIn(brief,prompts.launch_text(responder,tasks.SYSTEM))
        self.assertEqual(lifecycle.scout_evidence(steward,{'kind':'recovery_handoff','handoff':responder['id']}),
                         {'kind':'recovery_handoff','handoff':responder['id']})
        responder['status']='failed'
        with self.assertRaises(ValueError):
            lifecycle.scout_evidence(steward,{'kind':'recovery_handoff','handoff':responder['id']})
