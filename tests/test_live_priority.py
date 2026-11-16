import copy
import unittest
from unittest.mock import patch
from cointos import settings, scheduler, state, api
from tests import support


class LivePriority(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self)
        support.quiet(self)
        self.task = {'id':'repair', 'role':'first-responder','status':'running','agent':'repair-run','session':'kept','budget':{'generation_tokens':30000}}
        state.L['tasks']['repair'] = self.task
        self.thought = {'id':'t','agent':'repair-run','owner':'repair','model':'work','weight':1,'lane':None}
        state.L['thoughts'] = {'t':self.thought, 'peer':{'id':'peer','agent':'peer','owner':'peer','model':'work','weight':4,'lane':0}}
        self.schedule = self.enterContext(patch.object(settings.lanes,'schedule'))

    def test_change_is_live_and_preserves_run(self):
        before = copy.deepcopy(self.task)
        result = api.agent_priority({'task':'repair','weight':100})
        self.assertEqual(result['weight'],100)
        self.assertEqual(self.thought['weight'],100)
        self.assertEqual((self.task['session'],self.task['agent'],self.task['budget']), (before['session'],before['agent'],before['budget']))
        self.schedule.assert_called_once()

    def test_reset_restores_role_priority_and_future_requests(self):
        settings.set_priority('repair',100)
        result=settings.set_priority('repair',None)
        self.assertEqual(result['weight'],4)
        self.assertNotIn('scheduling_weight',self.task)
        self.assertEqual(self.thought['weight'],4)

    def test_invalid_weight_never_mutates_authority(self):
        before=copy.deepcopy(state.L)
        for value in (0,-1,True,'100',float('nan'),float('inf')):
            with self.subTest(value=value),self.assertRaises(ValueError):settings.set_priority('repair',value)
            self.assertEqual(state.L,before)
        self.schedule.assert_not_called()

    def test_override_in_tools_applies_to_future_request_weight(self):
        del state.L['thoughts']['t']
        settings.set_priority('repair',1000)
        self.assertEqual(self.task['scheduling_weight'],1000)
        self.assertNotIn('scheduler_service', state.L)

    def test_finished_task_is_not_rewritten(self):
        self.task['status']='done'
        with self.assertRaises(ValueError):settings.set_priority('repair',10)
