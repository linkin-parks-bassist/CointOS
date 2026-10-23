"""Paired real-model controls, run only inside qualify.py's parked transaction."""
import ast
import copy
import json
from pathlib import Path
import re
import statistics
import subprocess
import sys
import time

from cointos import backend_gufo as gufo, backend_llama as llama


def measure(run, backend, config, prompt, count, sampling):
    name = run.journal['model']
    start = time.monotonic(); held = 0
    while held < len(prompt):
        end = min(held + config['scheduler']['read_chunk_tokens'], len(prompt))
        backend.prefill(config, name, 0, prompt[:end], held)
        held = end
        if held % 4096 == 0 or held == len(prompt):
            print('benchmark prefill',backend.__name__,held,'/',len(prompt),flush=True)
        if available_gb() < config['memory']['reserve_gb']:
            raise RuntimeError('benchmark crossed workstation memory reserve')
    prefill = time.monotonic() - start
    tokens = list(prompt); fresh = []; native = charged = wall = 0
    proposed = accepted = rounds = 0
    while len(fresh) < count:
        start = time.monotonic()
        result = backend.think(config, name, 0, tokens, held,
                               min(96, count-len(fresh)), sampling, lambda _: None)
        wall += time.monotonic() - start
        produced = result['tokens']; fresh += produced; tokens += produced
        held = len(result['held'])
        if result['held'] != tokens[:held]: raise RuntimeError('unknown retained benchmark prefix')
        charged += result['generation_seconds']
        native += len(produced)/result['rate'] if result['rate'] else result['generation_seconds']
        proposed += result.get('draft_tokens', 0)
        accepted += result.get('draft_accepted_tokens', 0)
        rounds += result.get('draft_rounds', 0)
        if available_gb() < config['memory']['reserve_gb']:
            raise RuntimeError('decode crossed workstation memory reserve')
        if result['done']: break
    return {'prompt_tokens':len(prompt), 'generated_tokens':len(fresh), 'tokens':fresh,
            'prefill_wall_seconds':prefill, 'generation_seconds':charged,
            'native_decode_seconds':native, 'adapter_step_wall_seconds':wall,
            'native_tokens_per_second':len(fresh)/native,
            'adapter_tokens_per_second':len(fresh)/wall,
            'total_seconds':prefill+wall, 'draft_tokens':proposed,
            'draft_accepted_tokens':accepted, 'draft_rounds':rounds}


def available_gb():
    from patches.gufo.qualify import available_gb as available
    return available()


def check_code(text):
    """Check a small actual coding result without allowing arbitrary model effects."""
    fence = re.search(r'```(?:python)?\s*\n(.*?)```', text, re.S)
    source = (fence.group(1) if fence else text).strip()
    tree = ast.parse(source)
    if len(tree.body)!=1 or not isinstance(tree.body[0],ast.FunctionDef):
        raise ValueError('coding fixture must contain one function')
    function = tree.body[0]
    if function.name!='dedupe_runs' or function.decorator_list:
        raise ValueError('coding fixture changed the function contract')
    for node in ast.walk(tree):
        if isinstance(node,(ast.Import,ast.ImportFrom,ast.ClassDef,ast.Global,ast.Nonlocal)):
            raise ValueError('coding fixture contains unrelated operations')
        if isinstance(node,ast.Name) and node.id.startswith('__'):
            raise ValueError('coding fixture uses private Python names')
        if isinstance(node,ast.Attribute) and node.attr!='append':
            raise ValueError('coding fixture uses unrelated attributes')
        if isinstance(node,ast.Call) and not (
            isinstance(node.func,ast.Name) and node.func.id in ('list','len','range','enumerate')
            or isinstance(node.func,ast.Attribute) and node.func.attr=='append'):
            raise ValueError('coding fixture calls unrelated functions')
    checker = '''import json,sys,resource
resource.setrlimit(resource.RLIMIT_AS,(256*1024*1024,256*1024*1024))
resource.setrlimit(resource.RLIMIT_CPU,(2,2))
namespace={'__builtins__':{'list':list,'len':len,'range':range,'enumerate':enumerate}}
exec(sys.stdin.read(),namespace)
for values,wanted in [([],[]),([1],[1]),([1,1,2,2,1],[1,2,1]),([None,None,False,False,None],[None,False,None]),([[1],[1],[2]],[[1],[2]])]:
 before=list(values)
 assert namespace['dedupe_runs'](values)==wanted
 assert values==before
print('passed')
'''
    result = subprocess.run([sys.executable,'-I','-c',checker], input=source,
                            capture_output=True,text=True,timeout=3)
    if result.returncode or result.stdout.strip()!='passed':
        raise ValueError('coding fixture failed executable cases: '+result.stderr[-500:])
    return {'passed':True,'source':source,'cases':5}


def baseline(run):
    name = run.journal['model']
    if available_gb() < run.config['memory']['reserve_gb']+run.config['models'][name]['memory_gb']:
        raise RuntimeError('insufficient headroom for paired baseline')
    run.phase('paired benchmark: loading previous llama MTP configuration')
    run.journal['benchmark_lemonade_trial']=True; run.save()
    try:
        llama.launch(run.config,name)
        repetitive={'messages':[{'role':'user','content':('Reference: the integers have a natural increasing order.\n'*200)+'\nList integers from 1 to 10000, one per line, without explanations. Continue until stopped.'}], 'template':{'enable_thinking':False}}
        reference='\n'.join((Path(__file__).resolve().parents[2]/'cointos'/part).read_text()
                            for part in ('scheduler.py','memory.py'))
        code={'messages':[{'role':'user','content':'Reference source, unrelated to the requested function:\n'+reference*3+'\nEnd reference.\nWrite only Python code, with no imports, annotations or explanation. Define dedupe_runs(values): return a new list with consecutive equal entries collapsed to one, preserving order and non-consecutive repetitions. Support empty lists, None values and unhashable entries; do not mutate the input. Use simple loops and equality comparisons.'}], 'template':{'enable_thinking':False}}
        prompts={key:llama.render(run.config,name,value) for key,value in [('repetitive',repetitive),('code',code)]}
        sampling={'temperature':0,'seed':193,'top_k':20,'top_p':.95,'min_p':.05}
        result={'prompts':prompts,'sampling':sampling,'llama':{}}
        for key in prompts:
            rows=[]
            for trial in range(4 if key=='repetitive' else 2):
                params={**sampling,'temperature':1 if key=='code' and trial else 0}
                row=measure(run,llama,run.config,prompts[key]['tokens'],32 if key=='repetitive' and not trial else 256 if key=='repetitive' else 512,params)
                row['sampling']=params; row['warmup']=key=='repetitive' and not trial
                if key=='code':
                    text=llama.read(run.config,name,prompts[key]['reader'],row['tokens'],True)['content']
                    row['code_check']=check_code(text)
                rows.append(row)
                print('llama benchmark',key,{k:v for k,v in row.items() if k not in ('tokens','code_check')},flush=True)
            result['llama'][key]=rows
        run.journal['benchmark']=result; run.save()
    finally:
        llama.kill(run.config,name)
        run.journal['benchmark_lemonade_trial']=False; run.save()
    # Same native target runner as the candidate, with speculation disabled,
    # provides an exact greedy token reference for the new speculative bridge.
    run.phase('paired benchmark: native Gufo AR greedy reference')
    ar=run.trial_config(); ar['models'][name]['gufo'].pop('dflash',None)
    try:
        gufo.launch(ar,name)
        row=measure(run,gufo,ar,prompts['repetitive']['tokens'],256,sampling)
        run.journal['benchmark']['gufo_ar_reference']=row; run.save()
    finally: gufo.kill(ar,name)


def candidate(run):
    run.phase('paired benchmark: native Gufo DFlash2')
    data=run.journal['benchmark']; name=run.journal['model']; result={}
    for key,prompt in data['prompts'].items():
        rows=[]
        for baseline_row in data['llama'][key]:
            row=measure(run,gufo,run.trial,prompt['tokens'],32 if baseline_row['warmup'] else 256 if key=='repetitive' else 512,baseline_row['sampling'])
            row['warmup']=baseline_row['warmup']; row['sampling']=baseline_row['sampling']
            if key=='code':
                text=gufo.read(run.trial,name,prompt['reader'],row['tokens'],True)['content']
                row['code_check']=check_code(text)
            rows.append(row)
            print('Gufo DFlash benchmark',key,{k:v for k,v in row.items() if k not in ('tokens','code_check')},flush=True)
        result[key]=rows
    greedy=data['gufo_ar_reference']['tokens']
    if result['repetitive'][1]['tokens']!=greedy:
        raise RuntimeError('DFlash greedy output differs from the AR reference')
    old=statistics.median(x['native_tokens_per_second'] for x in data['llama']['repetitive'] if not x['warmup'])
    new=statistics.median(x['native_tokens_per_second'] for x in result['repetitive'] if not x['warmup'])
    data['gufo_dflash']=result
    data['summary']={'llama_repetitive_tps':old,'gufo_dflash_repetitive_tps':new,
                     'native_ar_greedy_equal':True,
                     'code_total_seconds':{'llama':[x['total_seconds'] for x in data['llama']['code']],
                                           'gufo':[x['total_seconds'] for x in result['code']]}}
    run.save()
    from patches.gufo.qualify import atomic_json
    atomic_json(run.output/'benchmark.json',data)
    if new<=old: raise RuntimeError('DFlash candidate did not improve the prior decode baseline')
