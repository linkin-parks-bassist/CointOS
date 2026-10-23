"""Generated history must belong to the exact delivered tool cycle and managed run."""
import copy
import io
import queue
import json
import os
import tempfile
import subprocess
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

from cointos import gateway, lanes, state, tasks, tool_history
from tests import support


class ExactHistory(unittest.TestCase):
    def setUp(self):
        self.config = {'models': {'q': {'backend':'gufo','ctx_size':128,'lanes':1}}}
        self.before = {'messages':[{'role':'user','content':'Read café.'}],
                       'tools':[{'function':{'name':'read'}}], 'template':{'enable_thinking':True}}
        self.calls = [{'id':'call-1','type':'function','function':{'name':'read',
                       'arguments':'{"filePath": "/tmp/café.c", "line": 1}'}}]
        self.parsed = {'content':'Inspect.','reasoning':'Check.','tool_calls':self.calls}
        self.delivered = {**self.parsed, 'content':'Inspect.\n'}
        self.after = {**self.before, 'messages': self.before['messages'] + [
            {'role':'assistant','content':'Inspect.\n','reasoning_content':'Check.','tool_calls':self.calls},
            {'role':'tool','tool_call_id':'call-1','content':'🦦 literal <|im_end|>'}]}
        self.raw = ('Check.\n</think>\n\nInspect.\n<tool_call>\n<function=read>\n'
                    '<parameter=filePath>\n/tmp/café.c\n</parameter>\n'
                    '<parameter=line>\n1\n</parameter>\n</function>\n</tool_call>')
        ids = {'<|im_end|>':[1], '<|im_start|>':[2], '<|endoftext|>':[3]}
        self.enterContext(patch.object(tool_history.gufo, '_call', side_effect=lambda *a,**k: {'tokens':ids[k['text']]}))
        self.text = self.enterContext(patch.object(tool_history.gufo, 'text', return_value=self.raw))
        self.render = self.enterContext(patch.object(tool_history.gufo, 'render',
                                                     return_value={'tokens':[10,12,1,2,8]}))
        self.canonical = {'tokens':[10,12,1,5,6], 'reader':{'thinking':True}}

    def capture(self, generated=None, delivered=None):
        return tool_history.capture(self.config,'q',self.before,[10,11],
                                    [20,21] if generated is None else generated,
                                    self.parsed, self.delivered if delivered is None else delivered)

    def test_preserves_emitted_prefix_and_exact_native_suffix_with_both_terminal_forms(self):
        for generated, expected in [([20,21],[10,11,20,21,1,5,6]),
                                    ([20,21,1],[10,11,20,21,1,5,6])]:
            record=self.capture(generated)
            result=tool_history.extend(self.config,'q',record,self.after,self.canonical)
            self.assertEqual(result['tokens'],expected)
            self.assertIs(result['reader'],self.canonical['reader'])
            self.assertEqual(self.canonical['tokens'],[10,12,1,5,6])

    def test_client_json_spacing_and_key_order_are_not_history_changes(self):
        after=copy.deepcopy(self.after)
        after['messages'][1]['tool_calls'][0]['function']['arguments']='{"line":1,"filePath":"/tmp/café.c"}'
        result=tool_history.extend(self.config,'q',self.capture(),after,self.canonical)
        self.assertEqual(result['tokens'],[10,11,20,21,1,5,6])

    def test_already_exact_native_history_needs_no_extra_render(self):
        record=self.capture();rendered={'tokens':record['held']+[1,5,6],'reader':{}}
        result=tool_history.extend(self.config,'q',record,self.after,rendered)
        self.assertIs(result,rendered)
        self.render.assert_not_called()

    def test_interrupted_assistant_continuations_preserve_verified_history_and_native_suffix(self):
        record=self.capture()
        for tail in ([{'role':'assistant','reasoning_content':'The file says'}],
                     [{'role':'assistant','reasoning_content':'The file says'},
                      {'role':'assistant','content':None}],
                     [{'role':'assistant','content':'Inspect the next definition.'}]):
            with self.subTest(tail=tail):
                after=copy.deepcopy(self.after);after['messages'].extend(tail)
                result=tool_history.extend(self.config,'q',record,after,self.canonical)
                self.assertEqual(result['tokens'],[10,11,20,21,1,5,6])
                self.assertIs(result['reader'],self.canonical['reader'])

    def test_incoming_text_turn_retains_verified_history_and_native_suffix(self):
        record=self.capture()
        for tail in ([{'role':'user','content':'Peer update: café 🦦 <|im_end|>'}],
                     [{'role':'assistant','content':'An interrupted reply'},
                      {'role':'user','content':'New request'},
                      {'role':'assistant','reasoning_content':'Considering the update'}]):
            with self.subTest(tail=tail):
                after=copy.deepcopy(self.after);after['messages'].extend(tail)
                result=tool_history.extend(self.config,'q',record,after,self.canonical)
                self.assertEqual(result['tokens'],[10,11,20,21,1,5,6])
                self.assertIs(result['reader'],self.canonical['reader'])

    def test_new_user_turn_that_changes_native_prefix_falls_back(self):
        after=copy.deepcopy(self.after)
        after['messages'].append({'role':'user','content':'New request'})
        with patch.object(tool_history.gufo,'render',return_value={'tokens':[99,1]}):
            self.assertIs(tool_history.extend(self.config,'q',self.capture(),after,self.canonical),self.canonical)

    def test_continuation_does_not_authorize_new_calls_results_or_unsupported_fields(self):
        record=self.capture()
        for message in ({'role':'assistant','tool_calls':self.calls},
                        {'role':'tool','tool_call_id':'call-1','content':'duplicate'},
                        {'role':'user','content':['image or structured content']},
                        {'role':'user','content':None},
                        {'role':'user','content':'New request','name':'unsupported'},
                        {'role':'assistant','content':'Text','refusal':'unsupported'},
                        {'role':'assistant','reasoning_content':['not text']}):
            with self.subTest(message=message):
                after=copy.deepcopy(self.after);after['messages'].append(message)
                self.assertIs(tool_history.extend(self.config,'q',record,after,self.canonical),self.canonical)

    def test_changed_history_contracts_results_or_value_types_fall_back(self):
        for kind in ('history','content','reasoning','argument','number_type','duplicate_key','contract','id','role','duplicate_result'):
            with self.subTest(kind=kind):
                after=copy.deepcopy(self.after)
                if kind=='history': after['messages'][0]['content']='Different request'
                if kind=='content': after['messages'][1]['content']='Inspect.'
                if kind=='reasoning': after['messages'][1]['reasoning_content']='Different reasoning'
                if kind=='argument': after['messages'][1]['tool_calls'][0]['function']['arguments']='{"filePath":"elsewhere","line":1}'
                if kind=='number_type': after['messages'][1]['tool_calls'][0]['function']['arguments']='{"filePath":"/tmp/café.c","line":1.0}'
                if kind=='duplicate_key': after['messages'][1]['tool_calls'][0]['function']['arguments']='{"filePath":"/tmp/café.c","line":1,"line":1}'
                if kind=='contract': after['template']['enable_thinking']=False
                if kind=='id': after['messages'][-1]['tool_call_id']='other'
                if kind=='role': after['messages'][-1]['role']='user'
                if kind=='duplicate_result': after['messages'].append(copy.deepcopy(after['messages'][-1]))
                self.assertIs(tool_history.extend(self.config,'q',self.capture(),after,self.canonical),self.canonical)

    def test_capacity_or_native_closing_mismatch_falls_back(self):
        record=self.capture()
        with patch.object(tool_history.gufo,'render',return_value={'tokens':[99,1]}):
            self.assertIs(tool_history.extend(self.config,'q',record,self.after,self.canonical),self.canonical)
        record['held']=list(range(128))
        self.assertIs(tool_history.extend(self.config,'q',record,self.after,self.canonical),self.canonical)

    def test_ambiguous_generated_framing_incomplete_calls_and_injected_controls_are_not_recorded(self):
        for generated in ([2,20],[20,1,21],[20,3]):
            self.assertIsNone(self.capture(generated))
        for raw in (self.raw.removesuffix('</tool_call>'),self.raw+' ignored junk',
                    self.raw.replace('café.c','<function=other>'),self.raw.replace('café.c','\ufffd')):
            self.text.return_value=raw
            self.assertIsNone(self.capture())
        delivered=copy.deepcopy(self.delivered)
        delivered['tool_calls'][0]['function']['name']='cointos_check_work'
        self.assertIsNone(self.capture(delivered=delivered))


class GatewayDelivery(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self)
        self.root=Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(gateway,'ROOT',self.root))
        self.task=support.running(tasks.create('operator',tasks.SYSTEM,'inspect','Inspect',[1]),'fixture-agent',worktree=False)
        self.enterContext(patch.dict(gateway.TOOL_HISTORY,clear=True))
        self.calls=[{'id':'c','type':'function','function':{'name':'read','arguments':'{}'}}]
        self.partial={'reasoning':'Check.','content':'Inspect.\n','tool_calls':[], 'phase':'writing'}
        self.final={**self.partial,'content':'Inspect.','tool_calls':self.calls}
        self.context={'owner':('fixture-agent',self.task['id'],self.task['record_version']),
                      'conversation':{'messages':[]}}

    def reply(self, broken=False, writer=None):
        q=queue.Queue();q.put([20,21]);q.put({'end':'done'})
        handler=gateway.Handler.__new__(gateway.Handler)
        handler.wfile=io.BytesIO() if writer is None else writer;handler.peer_closed=lambda:False
        handler.send_response=lambda *a:None;handler.send_header=lambda *a:None;handler.end_headers=lambda:None
        if broken:
            handler.wfile.close()
            def failed(*a): raise BrokenPipeError()
            handler.send_new=failed
        with patch.dict(lanes.RUNS,fixture={'queue':q}), \
             patch.object(gateway.BACKEND,'read',side_effect=[self.partial,self.final]):
            handler.reply_thought({'stream':True},'fixture-agent',state.CONFIG['work_model'],
                                  {'tokens':[10], 'reader':{}, '_tool_history':self.context},'fixture')

    def test_records_actual_streamed_text_instead_of_trimmed_final_parser_output(self):
        with patch.object(gateway.tool_history,'capture',return_value={'held':[10,20,21]}) as capture:
            self.reply()
        self.assertEqual(capture.call_args.args[-2]['content'],'Inspect.')
        self.assertEqual(capture.call_args.args[-1]['content'],'Inspect.\n')
        self.assertIn('fixture-agent',gateway.TOOL_HISTORY)

    def test_failed_delivery_does_not_create_a_record(self):
        with patch.object(gateway.tool_history,'capture') as capture:
            self.reply(broken=True)
        capture.assert_not_called();self.assertFalse(gateway.TOOL_HISTORY)

    def test_gateway_rehydrates_its_record_after_process_memory_is_lost(self):
        fixture=ExactHistory();fixture.setUp();self.addCleanup(fixture.doCleanups)
        with patch.dict(state.CONFIG,models=fixture.config['models']),patch.object(gateway,'log'):
            rendered={'tokens':[10,11],'_tool_history':{**self.context,'conversation':fixture.before}}
            gateway._remember_tool_history('fixture-agent','q',rendered,[20,21],fixture.parsed,fixture.delivered,'done')
            self.assertIn('fixture-agent',gateway.TOOL_HISTORY)
            gateway.TOOL_HISTORY.clear()
            result=gateway._prepare_tool_history('fixture-agent','q',fixture.after,fixture.canonical)
            self.assertEqual(result['tokens'],[10,11,20,21,1,5,6])
            self.assertEqual(gateway.TOOL_HISTORY['fixture-agent']['owner'],self.context['owner'])
            gateway.TOOL_HISTORY.clear()
            continuation=copy.deepcopy(fixture.after)
            continuation['messages'].append({'role':'assistant','reasoning_content':'An interrupted thought'})
            result=gateway._prepare_tool_history('fixture-agent','q',continuation,fixture.canonical)
            self.assertEqual(result['tokens'],[10,11,20,21,1,5,6])

    def test_cache_is_ready_before_done_and_rolled_back_if_final_delivery_fails(self):
        fixture=ExactHistory();fixture.setUp();self.addCleanup(fixture.doCleanups)
        record=fixture.capture();test=self
        class BrokenDone(io.BytesIO):
            def write(self,data):
                if data==b'data: [DONE]\n\n':
                    test.assertIn('fixture-agent',gateway.TOOL_HISTORY)
                    test.assertIsNotNone(tool_history.load_cache(test.root,test.context['owner']))
                    raise BrokenPipeError()
                return super().write(data)
        with patch.object(gateway.tool_history,'capture',return_value=record),patch.object(gateway,'log'):
            self.reply(writer=BrokenDone())
        self.assertFalse(gateway.TOOL_HISTORY)
        self.assertIsNone(tool_history.load_cache(self.root,self.context['owner']))

    def test_startup_pruning_keeps_runs_whose_processes_are_not_yet_adopted(self):
        fixture=ExactHistory();fixture.setUp();self.addCleanup(fixture.doCleanups)
        other=support.running(tasks.create('operator',tasks.SYSTEM,'other','Other',[1]),'other-agent',worktree=False)
        with patch.dict(state.CONFIG,models=fixture.config['models']),patch.object(gateway,'log'):
            rendered={'tokens':[10,11],'_tool_history':{**self.context,'conversation':fixture.before}}
            gateway._remember_tool_history('fixture-agent','q',rendered,[20,21],fixture.parsed,fixture.delivered,'done')
            gateway.TOOL_HISTORY.clear()
            saved=state.L['agents'].pop('fixture-agent')
            gateway._prepare_tool_history('other-agent','q',fixture.before,fixture.canonical)
            self.assertIsNotNone(tool_history.load_cache(self.root,self.context['owner']))
            state.L['agents']['fixture-agent']=saved
            result=gateway._prepare_tool_history('fixture-agent','q',fixture.after,fixture.canonical)
        self.assertEqual(result['tokens'],[10,11,20,21,1,5,6])

    def test_displaced_assignment_during_capture_cannot_publish_stale_history(self):
        def displaced(*args):
            self.task['record_version']=1
            return {'held':[10,20,21]}
        with patch.object(gateway.tool_history,'capture',side_effect=displaced):
            self.reply()
        self.assertFalse(gateway.TOOL_HISTORY)

    def test_limited_reply_clears_reuse_instead_of_recording_partial_output(self):
        gateway.TOOL_HISTORY['fixture-agent']={'owner':self.context['owner'],'record':{}}
        with patch.object(gateway.tool_history,'capture') as capture:
            gateway._remember_tool_history('fixture-agent',state.CONFIG['work_model'],
                {'_tool_history':self.context},[1],self.final,self.final,'limit')
        capture.assert_not_called();self.assertFalse(gateway.TOOL_HISTORY)

    def test_other_agent_never_receives_this_runs_record(self):
        model=state.CONFIG['work_model']
        other=support.running(tasks.create('operator',tasks.SYSTEM,'other','Other',[1]),'other-agent',worktree=False)
        gateway.TOOL_HISTORY['fixture-agent']={'owner':self.context['owner'],'record':{'held':[10]}}
        rendered={'tokens':[10,12],'reader':{}}
        with patch.dict(state.CONFIG['models'][model],backend='gufo'), \
             patch.object(gateway.tool_history,'extend',return_value=rendered) as extend:
            result=gateway._prepare_tool_history('other-agent',model,{'messages':[]},rendered)
        self.assertIsNone(extend.call_args.args[2])
        self.assertEqual(result['_tool_history']['owner'][1],other['id'])
        self.assertIn('fixture-agent',gateway.TOOL_HISTORY)

    def test_stale_record_is_removed_and_optional_render_failure_falls_back(self):
        model=state.CONFIG['work_model'];rendered={'tokens':[10,12],'reader':{}}
        gateway.TOOL_HISTORY['fixture-agent']={'owner':('fixture-agent',self.task['id'],-1),'record':{}}
        with patch.dict(state.CONFIG['models'][model],backend='gufo'), \
             patch.object(gateway.tool_history,'extend',side_effect=RuntimeError('metadata unavailable')), \
             patch.object(gateway,'log'):
            result=gateway._prepare_tool_history('fixture-agent',model,{'messages':[]},rendered)
        self.assertEqual(result['tokens'],rendered['tokens'])
        self.assertFalse(gateway.TOOL_HISTORY)


class CachePersistence(unittest.TestCase):
    def setUp(self):
        self.fixture=ExactHistory()
        self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.root=Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.owner=('worker-a','p:one',1)
        self.record=self.fixture.capture()

    def store(self, owner=None, record=None):
        tool_history.store_cache(self.root,owner or self.owner,
                                 self.record if record is None else record,lambda:True)

    def test_roundtrip_after_memory_loss_retains_exact_native_prefix(self):
        self.store()
        loaded=tool_history.load_cache(self.root,self.owner)
        self.assertEqual(loaded,{'owner':self.owner,'record':self.record})
        result=tool_history.extend(self.fixture.config,'q',loaded['record'],self.fixture.after,self.fixture.canonical)
        self.assertEqual(result['tokens'],[10,11,20,21,1,5,6])
        path=self.root/'state/tool-history/worker-a.json'
        self.assertEqual(path.stat().st_mode&0o777,0o600)
        self.assertEqual(path.parent.stat().st_mode&0o777,0o700)

    def test_new_python_process_loads_the_same_validated_record(self):
        self.store()
        code=('import json,sys; from pathlib import Path; from cointos import tool_history; '
              'print(json.dumps(tool_history.load_cache(Path(sys.argv[1]),tuple(json.loads(sys.argv[2])))))')
        value=json.loads(subprocess.check_output([sys.executable,'-c',code,str(self.root),json.dumps(self.owner)],
                                               cwd=Path(__file__).resolve().parents[1],text=True))
        self.assertEqual(value['record'],self.record)
        self.assertEqual(tuple(value['owner']),self.owner)

    def test_directory_link_is_refused_without_touching_its_target(self):
        (self.root/'state').mkdir()
        outside=self.root/'outside';outside.mkdir(mode=0o700)
        (outside/'keep').write_text('preserve')
        (self.root/'state/tool-history').symlink_to(outside,target_is_directory=True)
        with self.assertRaises(OSError):self.store()
        with self.assertRaises(OSError):tool_history.load_cache(self.root,self.owner)
        self.assertEqual([p.name for p in outside.iterdir()],['keep'])

    def test_stale_owner_and_checksum_corruption_refuse_reuse(self):
        self.store()
        self.assertIsNone(tool_history.load_cache(self.root,('worker-a','p:one',2)))
        path=self.root/'state/tool-history/worker-a.json'
        data=json.loads(path.read_text());data['record']['held'][0]=999
        path.write_text(json.dumps(data))
        with self.assertRaises(ValueError):tool_history.load_cache(self.root,self.owner)

    def test_file_links_and_nonregular_files_are_not_followed_or_overwritten(self):
        self.store();path=self.root/'state/tool-history/worker-a.json';path.unlink()
        outside=self.root/'outside';outside.write_text('preserve')
        path.symlink_to(outside)
        with self.assertRaises(OSError):tool_history.load_cache(self.root,self.owner)
        with self.assertRaises(OSError):self.store()
        self.assertEqual(outside.read_text(),'preserve')
        path.unlink();os.mkfifo(path,0o600)
        with self.assertRaises(ValueError):tool_history.load_cache(self.root,self.owner)

    def test_failed_atomic_publication_preserves_previous_record(self):
        self.store()
        other={**self.record,'held':[40,41]}
        with patch('cointos.privatejson.os.replace',side_effect=OSError('disk unavailable')):
            with self.assertRaises(OSError):self.store(record=other)
        self.assertEqual(tool_history.load_cache(self.root,self.owner)['record'],self.record)
        self.assertFalse(list((self.root/'state/tool-history').glob('*.tmp')))

    def test_failed_response_cleanup_cannot_remove_a_newer_record(self):
        self.store()
        newer={**self.record,'held':[40,41]};self.store(record=newer)
        tool_history.discard_cache(self.root,self.owner,self.record)
        self.assertEqual(tool_history.load_cache(self.root,self.owner)['record'],newer)

    def test_displaced_publication_is_refused_and_pruning_preserves_foreign_files(self):
        self.store()
        tool_history.store_cache(self.root,self.owner,{**self.record,'held':[40]},lambda:False)
        self.assertEqual(tool_history.load_cache(self.root,self.owner)['record'],self.record)
        path=self.root/'state/tool-history';foreign=path/'notes.json';foreign.write_text('private notes')
        tool_history.prune_cache(self.root,lambda agent:self.owner)
        self.assertIsNotNone(tool_history.load_cache(self.root,self.owner))
        tool_history.prune_cache(self.root,lambda agent:None)
        self.assertIsNone(tool_history.load_cache(self.root,self.owner))
        self.assertEqual(foreign.read_text(),'private notes')

