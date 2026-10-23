#!/usr/bin/env python3
"""Controlled real-Qwen qualification with recoverable runtime/cache parking."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from cointos import backend_gufo as gufo, backend_llama as llama, memory, repair


def atomic_json(path, value):
    temp = path.with_suffix('.new')
    with temp.open('w') as out:
        os.fchmod(out.fileno(), 0o600)
        json.dump(value, out, indent=2)
        out.write('\n')
        out.flush()
        os.fsync(out.fileno())
    os.replace(temp, path)
    fd = os.open(path.parent, os.O_DIRECTORY | os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as data:
        for block in iter(lambda: data.read(1024 * 1024), b''): digest.update(block)
    return digest.hexdigest()


def copy_checked(source, target, expected=None, mode=0o600):
    """Copy to an atomic destination; the source remains until verified publication."""
    source, target = Path(source), Path(target)
    if not stat.S_ISREG(source.lstat().st_mode): raise ValueError(f'not a regular cache: {source}')
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = target.with_name(target.name + '.copying')
    try:
        with source.open('rb') as incoming, temporary.open('wb') as outgoing:
            os.fchmod(outgoing.fileno(), mode)
            digest = hashlib.sha256()
            for block in iter(lambda: incoming.read(1024 * 1024), b''):
                outgoing.write(block); digest.update(block)
            outgoing.flush(); os.fsync(outgoing.fileno())
        wanted = expected or digest.hexdigest()
        if digest.hexdigest() != wanted or sha256(temporary) != wanted:
            raise ValueError(f'cache checksum mismatch: {source}')
        os.replace(temporary, target)
        return wanted
    finally:
        temporary.unlink(missing_ok=True)


def request(url, body=None, timeout=300):
    req = urllib.request.Request(url, None if body is None else json.dumps(body).encode(),
                                 {'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as result: return json.load(result)


def cgroup_path(unit, group=None):
    if group is None:
        group=subprocess.check_output(['systemctl','--user','show',unit,'-p','ControlGroup','--value'],text=True).strip()
    prefix=f'/user.slice/user-{os.getuid()}.slice/user@{os.getuid()}.service/'
    if not unit.startswith('cointos-') or not group.startswith(prefix): return None
    path=Path('/sys/fs/cgroup')/group.lstrip('/')
    if not (path/'cgroup.freeze').exists() or (path/'cgroup.freeze').stat().st_uid!=os.getuid(): return None
    return path


def service(unit):
    out = subprocess.check_output(['systemctl', '--user', 'show', unit, '-p', 'ActiveState', '-p', 'MainPID', '-p', 'FreezerState', '-p', 'ControlGroup'], text=True)
    fields=dict(line.split('=', 1) for line in out.splitlines() if '=' in line)
    path=cgroup_path(unit,fields.pop('ControlGroup',''))
    if path is not None:
        events=dict(line.split() for line in (path/'cgroup.events').read_text().splitlines())
        fields['FreezerState']='frozen' if events.get('frozen')=='1' else 'running'
    return fields


def systemctl(*args):
    if len(args)==2 and args[0] in ('freeze','thaw'):
        path=cgroup_path(args[1])
        if path is not None:
            # These delegated cgroups are owned by this user. Kernel acknowledgement
            # remains reliable when systemd cannot allocate an inotify watch.
            wanted='1' if args[0]=='freeze' else '0'
            (path/'cgroup.freeze').write_text(wanted)
            deadline=time.monotonic()+30
            while True:
                events=dict(line.split() for line in (path/'cgroup.events').read_text().splitlines())
                if events.get('frozen')==wanted: return
                if time.monotonic()>=deadline: raise TimeoutError('kernel did not acknowledge '+args[0]+': '+args[1])
                time.sleep(0.05)
    subprocess.run(['systemctl', '--user', *args], check=True)


def available_gb():
    for line in Path('/proc/meminfo').read_text().splitlines():
        if line.startswith('MemAvailable:'): return int(line.split()[1]) * 1024 / 1e9
    raise RuntimeError('MemAvailable unavailable')


class Run:
    def __init__(self, output, config=None, model=None, options=None):
        self.output = Path(output).resolve()
        self.output.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.output.stat().st_mode & 0o077: raise ValueError('qualification output must be private')
        self.path = self.output / 'recovery.json'
        if config is None:
            self.journal = json.loads(self.path.read_text())
        else:
            if self.path.exists(): raise ValueError('existing qualification journal; use --recover or a new output')
            self.journal = {'config': config, 'model': model, 'options': options, 'phase': 'prepared',
                            'units': {}, 'caches': [], 'slots': [], 'daemon_stopped': False, 'draining': False,
                            'original_models': [], 'test': {}, 'restored': False}
            self.save()
        self.config = self.journal['config']
        self.gateway = f"http://127.0.0.1:{self.config['port']}/api"
        self.ram = Path(self.config['snapshots'])
        self.stop_watch = threading.Event()
        self.pressure = threading.Event()
        self.watcher = None
        self.trial = None

    def save(self): atomic_json(self.path, self.journal)
    def phase(self, name):
        self.journal['phase'] = name; self.save()
        print(time.strftime('%H:%M:%S'), name, flush=True)
    def api(self, name, body=None):
        return request(self.gateway + '/' + name, body, self.config['timeouts']['command_seconds'])
    def health(self):
        return request(self.config['lemonade'] + '/api/v1/health', timeout=self.config['timeouts']['lemonade_health_seconds'])['all_models_loaded']

    def offload(self, source, collection):
        source = Path(source)
        metadata = source.stat()
        entry = {'source': str(source), 'backup': str(self.output / collection / source.name),
                 'mode': stat.S_IMODE(metadata.st_mode), 'bytes': metadata.st_size, 'ready': False}
        self.journal[collection].append(entry); self.save()
        entry['sha256'] = copy_checked(source, entry['backup'])
        entry['ready'] = True; self.save()
        source.unlink()
        entry['offloaded'] = True; self.save()
        return entry

    def restore_files(self, collection):
        for entry in self.journal[collection]:
            if not entry['ready']: continue  # No source was removed before ready was journaled.
            source = Path(entry['source'])
            if source.exists():
                if sha256(source) != entry['sha256']: raise RuntimeError(f'changed parked cache: {source}')
            else:
                copy_checked(entry['backup'], source, entry['sha256'], entry['mode'])
            entry['returned'] = True; self.save()

    def park(self, cut_replies=False):
        ledger = self.api('ledger')
        if ledger.get('restarting'): raise RuntimeError('another drain is already active')
        if any(t.get('validating') for t in ledger['tasks'].values()): raise RuntimeError('validation is active')
        if service('cointosd.service')['ActiveState'] != 'active': raise RuntimeError('daemon must be active before parking')
        self.journal['original_models'] = self.health()
        native_shape = self.config['models'][self.journal['model']]
        if native_shape.get('backend') == 'gufo':
            self.journal['original_gufo'] = gufo._call(self.config, self.journal['model'], 'info')
            self.save()
        self.journal['authority'] = {str(path): sha256(path) for path in (
            Path.home()/'.CointOS/config/cointos.json', Path.home()/'.CointOS/config/projects.json',
            Path.home()/'.CointOS/state/keys.json')}
        key_data = json.loads((Path.home()/'.CointOS/state/keys.json').read_text())
        self.journal['key_entries'] = sorted(hashlib.sha256(json.dumps([key,value],sort_keys=True).encode()).hexdigest()
                                             for key,value in key_data.items())
        self.journal['agents'] = {name: {k:a.get(k) for k in ('task','session','pid','generation_seconds','generation_tokens')}
                                  for name,a in ledger['agents'].items()}
        self.journal['draining'] = True; self.save()
        self.api('prepare-restart', {})
        self.phase('freezing clients at native step boundaries' if cut_replies else
                   'freezing clients and draining complete replies')
        units = json.loads(subprocess.check_output(['systemctl','--user','list-units','--type=service','--state=running','--output=json'],text=True))
        names = [u['unit'] for u in units if u['unit'].startswith('cointos-agent-')]
        if service('cointos-coin.service')['ActiveState'] == 'active': names.append('cointos-coin.service')
        for name in names:
            before = service(name)
            if before['ActiveState'] != 'active' or before['MainPID'] == '0': continue
            if before['FreezerState'] != 'running': raise RuntimeError(f'{name} already frozen')
            self.journal['units'][name] = before; self.save()
            systemctl('freeze', name)
        deadline = time.monotonic() + self.config['timeouts']['command_seconds']
        while not cut_replies:
            ready = self.api('prepare-restart', {})['ready']
            transfers = any(s['tier']=='moving' for s in self.api('ledger')['snapshots'].values())
            if ready and not transfers: break
            if time.monotonic() >= deadline: raise TimeoutError('existing replies/transfers did not drain')
            time.sleep(self.config['tick_seconds'])
        self.journal['drained_ledger'] = self.api('ledger')
        self.phase('stopping daemon after drain; client processes remain frozen')
        self.journal['daemon_stopped'] = True; self.save()
        systemctl('stop', 'cointosd.service')
        persisted = json.loads((Path.home()/'.CointOS/state/cointos.json').read_text())
        self.journal['drained_ledger'] = persisted; self.save()
        self.phase('parking immutable RAM snapshots on disk')
        for name, snapshot in persisted['snapshots'].items():
            if snapshot['tier'] != 'memory': continue
            source = self.ram / llama._snapshot(name)
            if self.config['models'].get(snapshot['model'], {}).get('backend') == 'gufo':
                source = self.ram / 'gufo' / llama._snapshot(name)
            if source.stat().st_size != snapshot['bytes']: raise RuntimeError('ledger/cache byte mismatch')
            self.offload(source, 'caches')
        self.phase('saving physical model lanes')
        for model_index, entry in enumerate(self.journal['original_models']):
            url = entry['backend_url'].removesuffix('/v1')
            slots = request(url + '/slots')
            if any(s['is_processing'] for s in slots): raise RuntimeError('model still processing after drain')
            for slot in slots:
                filename = f"gufo-qualification-{self.output.name}-{model_index}-{slot['id']}.bin"
                saved = request(url + f"/slots/{slot['id']}?action=save", {'filename': filename})
                if saved['n_saved']:
                    parked = self.offload(self.ram / filename, 'slots')
                    parked.update(model=entry['model_name'], lane=slot['id'], tokens=saved['n_saved'])
                    self.save()
                else:
                    (self.ram / filename).unlink(missing_ok=True)
        if self.journal.get('original_gufo'):
            self.phase('releasing the parked Gufo work model')
            gufo.kill(self.config,self.journal['model'])
        else:
            if not any(e['model_name']==self.journal['model'] for e in self.journal['original_models']): raise RuntimeError('work model was not loaded')
            self.phase('unloading only the parked work model')
            self.journal['unload_attempted'] = True; self.save()
            request(self.config['lemonade'] + '/v1/unload', {'model_name': self.journal['model']}, self.config['timeouts']['model_kill_seconds'])

    def trial_config(self):
        options = self.journal['options']
        shape = self.config['models'][self.journal['model']]
        root = self.output / 'control'; root.mkdir(mode=0o700, exist_ok=True)
        ram = Path('/dev/shm') / ('cointos-gufo-' + hashlib.sha256(str(self.output).encode()).hexdigest()[:12])
        ram.mkdir(mode=0o700, exist_ok=True)
        self.journal['trial_ram'] = str(ram); self.save()
        return {**self.config, 'snapshots': str(ram), 'disk_snapshots': str(root/'disk'),
                'models': {self.journal['model']: {**shape, 'backend':'gufo', 'gufo': {
                    **options, 'socket':str(root/'control.sock')}}}}

    def watch_memory(self):
        minimum = self.config['memory']['reserve_gb']
        executable = Path(self.journal['options']['executable']).resolve()
        executables = {str(executable), str(executable.with_name(executable.name + '.bin'))}
        while not self.stop_watch.wait(0.25):
            current = available_gb()
            self.journal['minimum_available_gb'] = min(self.journal.get('minimum_available_gb', current), current)
            for line in Path('/proc/pressure/memory').read_text().splitlines():
                if line.startswith('full '):
                    psi=float(line.split()[1].split('=')[1])
                    self.journal['maximum_psi']=max(self.journal['maximum_psi'],psi)
                    break
            if current >= minimum: continue
            self.pressure.set()
            # Only this driver's own native Gufo child may be terminated.
            children = Path(f'/proc/{os.getpid()}/task/{os.getpid()}/children').read_text().split()
            for child in children:
                try:
                    command = (Path('/proc')/child/'cmdline').read_bytes().split(b'\0')
                    if command and os.fsdecode(command[0]) in executables:
                        os.kill(int(child), signal.SIGKILL)
                except ProcessLookupError: pass
                except FileNotFoundError: pass
            return

    def prefill(self, tokens, held=0):
        chunk = self.trial['scheduler']['read_chunk_tokens']
        while held < len(tokens):
            end = min(len(tokens), held + chunk)
            gufo.prefill(self.trial, self.journal['model'], 0, tokens[:end], held)
            held = end
            if held % 8192 == 0 or held == len(tokens):
                print('native prefill',held,'/',len(tokens),flush=True)
        return held

    def think(self, tokens, count, sampling):
        return gufo.think(self.trial, self.journal['model'], 0, tokens, len(tokens), count, sampling, lambda _: None)

    def prepare_production(self):
        """Finish native allocation and let host pressure settle before guard adoption."""
        name = self.journal['model']
        if self.journal.get('original_gufo'):
            gufo.launch(self.config, name)
            info = gufo._call(self.config, name, 'info')
            if info['identity'] != self.journal['original_gufo']['identity']:
                raise RuntimeError('restored Gufo identity differs')
            snapshots = self.journal.get('drained_ledger', {}).get('snapshots', {})
            candidates = [(s['bytes'], key) for key, s in snapshots.items()
                          if s['model'] == name and s['tier'] == 'memory' and s['tokens']]
            if candidates and not gufo.restore(self.config, name, 0, max(candidates)[1]):
                raise RuntimeError('production prefix warm restore failed')
        deadline = time.monotonic() + self.config['timeouts']['model_launch_seconds']
        while True:
            measured = memory.measure()
            if (measured['available_gb'] >= self.config['memory']['reserve_gb']
                    and measured['psi'] <= self.config['memory']['max_psi'] / 2):
                self.journal['recovery_memory'] = measured; self.save()
                return
            if time.monotonic() >= deadline:
                raise TimeoutError('host pressure did not settle before production adoption')
            time.sleep(self.config['tick_seconds'])

    def qualify(self, before_qualification=None):
        self.trial = self.trial_config(); name = self.journal['model']
        self.journal['minimum_available_gb'] = available_gb()
        self.journal['maximum_psi'] = 0.0
        self.watcher = threading.Thread(target=self.watch_memory, daemon=True); self.watcher.start()
        self.phase('loading native Gufo at the configured production context size')
        gufo.launch(self.trial, name)
        self.journal['test']['info'] = gufo._call(self.trial, name, 'info'); self.save()
        if before_qualification: before_qualification(self)
        self.phase('restored partial prompt can extend before generation')
        prompt=gufo._call(self.trial,name,'tokenize',text='A scheduler shares finite resources fairly. '*600)['tokens']
        prefix=prompt[:1024]
        self.prefill(prefix)
        gufo.save(self.trial,name,0,'partial')
        self.prefill(prompt,1024)
        expected=self.think(prompt,16,{'temperature':0,'seed':193})
        if not gufo.restore(self.trial,name,0,'partial'): raise RuntimeError('partial prefix restore failed')
        self.prefill(prompt,1024)
        replay=self.think(prompt,16,{'temperature':0,'seed':193})
        if replay['tokens']!=expected['tokens']: raise RuntimeError('restored partial prompt changed generation')
        self.journal['test']['prefix_extension']={'passed':True,'prefix_tokens':1024,'prompt_tokens':len(prompt)};self.save()
        self.phase('native sampled continuation, overwrite, disk spill and process restart')
        conversation = {'messages':[{'role':'user','content':'List the integers from 1 through 100, one per line, with no introduction.'}],
                        'template':{'enable_thinking':False}}
        rendered = gufo.render(self.trial,name,conversation); prompt = rendered['tokens']
        self.prefill(prompt)
        sampling={'temperature':0.7,'seed':193,'top_k':20,'top_p':0.95,'repeat_penalty':1.1}
        first=self.think(prompt,12,sampling); tokens=prompt+first['tokens']
        if len(first['tokens']) != 12: raise RuntimeError('continuation fixture ended early')
        saved=gufo.save(self.trial,name,0,'generated')
        expected=self.think(tokens,24,sampling)
        other=gufo.render(self.trial,name,{'messages':[{'role':'user','content':'Say hello.'}],'template':{'enable_thinking':False}})['tokens']
        self.prefill(other)
        if not gufo.restore(self.trial,name,0,'generated'): raise RuntimeError('native restore failed')
        replay=self.think(tokens,24,sampling)
        if replay['tokens']!=expected['tokens']: raise RuntimeError('native fork changed sampled continuation')
        gufo.spill(self.trial,'generated'); gufo.kill(self.trial,name); gufo.launch(self.trial,name); gufo.unspill(self.trial,'generated')
        if not gufo.restore(self.trial,name,0,'generated'): raise RuntimeError('process/disk restore failed')
        restarted=self.think(tokens,24,sampling)
        if restarted['tokens']!=expected['tokens']: raise RuntimeError('process restart changed sampled continuation')
        self.journal['test']['continuation']={'passed':True,'saved':saved,'tokens':expected['tokens']}; self.save()
        self.phase('native tool call and tool-result history')
        tool={'type':'function','function':{'name':'record','description':'Record an integer.',
              'parameters':{'type':'object','properties':{'value':{'type':'integer'}},'required':['value']}}}
        conversation={'messages':[{'role':'user','content':'Call record exactly once with value 37. After the tool result, reply with the recorded value.'}],
                      'tools':[tool],'template':{'enable_thinking':False}}
        rendered=gufo.render(self.trial,name,conversation); self.prefill(rendered['tokens'])
        generated=self.think(rendered['tokens'],128,{'temperature':0,'seed':193})
        response=gufo.read(self.trial,name,rendered['reader'],generated['tokens'],True)
        calls=response['tool_calls']
        if len(calls)!=1 or calls[0]['function']['name']!='record' or json.loads(calls[0]['function']['arguments'])!={'value':37}:
            raise RuntimeError('native tool call failed: '+json.dumps(response))
        conversation['messages'] += [{'role':'assistant','content':response['content'],'tool_calls':calls},
            {'role':'tool','tool_call_id':calls[0]['id'],'content':'{"recorded":37}'}]
        follow=gufo.render(self.trial,name,conversation); self.prefill(follow['tokens'])
        answer=self.think(follow['tokens'],64,{'temperature':0,'seed':193})
        text=gufo.read(self.trial,name,follow['reader'],answer['tokens'],True)
        if '37' not in text['content']: raise RuntimeError('tool result did not reach the reply')
        self.journal['test']['tools']={'passed':True,'call':calls[0],'reply':text}; self.save()
        self.phase('native reasoning-budget closure at a speculative chunk boundary')
        conversation={'messages':[{'role':'user','content':'Reply with the number 37.'}],
                      'template':{'enable_thinking':True},'reasoning_budget':2}
        rendered=gufo.render(self.trial,name,conversation); prompt=rendered['tokens']
        self.prefill(prompt)
        first=self.think(prompt,2,{'temperature':0,'seed':193})
        held=prompt+first['tokens']
        closing=rendered['reader']['think_close']
        closed=held+closing
        self.prefill(closed,len(held))
        answer=self.think(closed,64,{'temperature':0,'seed':193})
        reply=gufo.read(self.trial,name,rendered['reader'],first['tokens']+closing+answer['tokens'],True)
        if reply['phase']!='writing' or '37' not in reply['content']:
            raise RuntimeError('reasoning budget closure lost the answer')
        self.journal['test']['reasoning_budget']={'passed':True,'reply':reply}; self.save()
        self.phase('full configured context prefill and exact deep snapshot continuation')
        context=self.trial['models'][name]['ctx_size']
        seed=gufo._call(self.trial,name,'tokenize',text='A scheduler shares finite resources fairly. ')['tokens']
        target=context-128
        deep=(seed*((target+len(seed)-1)//len(seed)))[:target]
        self.prefill(deep)
        deep_saved=gufo.save(self.trial,name,0,'deep')
        deep_expected=self.think(deep,16,{'temperature':0,'seed':193})
        if not gufo.restore(self.trial,name,0,'deep'): raise RuntimeError('deep context restore failed')
        deep_replay=self.think(deep,16,{'temperature':0,'seed':193})
        if deep_expected['tokens']!=deep_replay['tokens']: raise RuntimeError('deep snapshot changed native continuation')
        self.journal['test']['deep']={'passed':True,'prompt_tokens':len(deep),'saved':deep_saved,
                                      'generated':len(deep_expected['tokens'])}; self.save()
        self.phase('repeated full-context restore and exact continuation')
        restore_seconds=[]
        for _ in range(5):
            started=time.monotonic()
            if not gufo.restore(self.trial,name,0,'deep'): raise RuntimeError('repeated deep restore failed')
            restore_seconds.append(time.monotonic()-started)
            replay=self.think(deep,16,{'temperature':0,'seed':193})
            if replay['tokens']!=deep_expected['tokens']:
                raise RuntimeError('reused executor changed deep continuation')
        self.journal['test']['repeated_restores']={'passed':True,'count':5,'seconds':restore_seconds};self.save()

    def recover(self):
        if self.journal.get('restored'):
            print('production was already restored', flush=True)
            return
        self.phase('restoring production')
        if self.journal.get('benchmark_lemonade_trial'):
            llama.kill(self.config,self.journal['model'])
            self.journal['benchmark_lemonade_trial']=False; self.save()
        self.stop_watch.set()
        if self.watcher: self.watcher.join()
        trial = self.trial or self.trial_config()
        try: gufo.kill(trial,self.journal['model'])
        except (OSError,RuntimeError) as error:
            self.journal['gufo_cleanup_error']=str(error); self.save()
            raise  # Do not reload production while an unknown trial process might retain RAM.
        shutil.rmtree(self.output/'control',ignore_errors=True)
        if self.journal.get('trial_ram'): shutil.rmtree(self.journal['trial_ram'],ignore_errors=True)
        if not self.journal.get('models_restored'):
            changed=set()
            if self.journal.get('unload_attempted'):
                loaded={m['model_name']:m for m in self.health()}
                for original in self.journal['original_models']:
                    name=original['model_name']; current=loaded.get(name)
                    if current is None:
                        options=original['recipe_options']
                        request(self.config['lemonade']+'/v1/load',{'model_name':name,'ctx_size':options['ctx_size'],
                            'llamacpp_args':options['llamacpp_args'],'merge_args':False,'save_options':False,'pinned':original['pinned']},
                            self.config['timeouts']['model_launch_seconds'])
                        loaded={m['model_name']:m for m in self.health()}; current=loaded[name]
                    if current['backend_url']!=original['backend_url'] or current['launch_command']!=original['launch_command']:
                        raise RuntimeError('restored model identity/port differs: '+name)
                    if current['pid']!=original['pid']: changed.add(name)
            self.restore_files('slots')
            loaded={m['model_name']:m for m in self.health()}
            for entry in self.journal['slots']:
                if entry.get('model') not in changed: continue
                model=loaded[entry['model']]; url=model['backend_url'].removesuffix('/v1')
                restored=request(url+f"/slots/{entry['lane']}?action=restore",{'filename':Path(entry['source']).name})
                if restored['n_restored']!=entry['tokens']: raise RuntimeError('production lane restore count differs')
            for entry in self.journal['slots']:
                if entry.get('ready'): Path(entry['source']).unlink(missing_ok=True)
            self.journal['models_restored']=True; self.save()
        if not self.journal.get('caches_restored'):
            self.restore_files('caches')
            self.journal['caches_restored']=True; self.save()
        if not self.journal.get('unit_identities_checked'):
            self.journal['preserved_units']={name:service(name) for name in self.journal['units']}
            for name,before in self.journal['units'].items():
                if self.journal['preserved_units'][name]['MainPID']!=before['MainPID']: raise RuntimeError('parked process identity changed: '+name)
            self.journal['unit_identities_checked']=True; self.save()
        if self.journal['daemon_stopped']:
            self.phase('warming production model before daemon memory-guard adoption')
            self.prepare_production()
            systemctl('start','cointosd.service')
            deadline=time.monotonic()+self.config['timeouts']['agent_start_seconds']
            while True:
                try: self.api('cancel-restart',{}); break
                except (OSError,ValueError):
                    if time.monotonic()>=deadline: raise
                    time.sleep(self.config['tick_seconds'])
            self.journal['daemon_stopped']=False; self.save()
        elif self.journal['draining']:
            self.api('cancel-restart',{})
        if self.journal.get('drained_ledger'):
            after = self.api('ledger')
            self.journal['adopted_agents'] = after['agents']
            for name,before in self.journal['drained_ledger']['agents'].items():
                adopted = after['agents'].get(name)
                if adopted is None or any(adopted.get(k)!=before.get(k) for k in ('task','session','pid','generation_seconds','generation_tokens')):
                    raise RuntimeError('adopted agent identity or spend changed: '+name)
        if self.journal.get('original_gufo'):
            deadline=time.monotonic()+self.config['timeouts']['model_launch_seconds']
            while True:
                try:
                    info=gufo._call(self.config,self.journal['model'],'info')
                    if info['identity']!=self.journal['original_gufo']['identity']:
                        raise RuntimeError('restored Gufo identity differs')
                    break
                except (FileNotFoundError,ConnectionRefusedError):
                    if time.monotonic()>=deadline: raise
                    time.sleep(self.config['tick_seconds'])
        key_data = json.loads((Path.home()/'.CointOS/state/keys.json').read_text())
        entries = {hashlib.sha256(json.dumps([key,value],sort_keys=True).encode()).hexdigest() for key,value in key_data.items()}
        if not set(self.journal.get('key_entries',[])).issubset(entries): raise RuntimeError('prior gateway authority changed')
        for name in self.journal['units']: systemctl('thaw',name)
        self.journal['draining']=False
        self.journal['authority_after']={path:sha256(path) for path in self.journal.get('authority',{})}
        if any(self.journal['authority_after'][path]!=digest for path,digest in self.journal.get('authority',{}).items()
               if not path.endswith('/keys.json')): raise RuntimeError('runtime configuration or enrollment changed during qualification')
        self.journal['restored']=True
        passed=(not self.journal.get('error') and all(self.journal['test'].get(k,{}).get('passed')
                for k in ('prefix_extension','continuation','tools','reasoning_budget','deep','repeated_restores')))
        self.phase('production restored; test '+('passed' if passed else 'incomplete'))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--recover',action='store_true')
    parser.add_argument('--config',type=Path,default=Path.home()/'.CointOS/config/cointos.json')
    parser.add_argument('--executable',type=Path)
    parser.add_argument('--model-path',type=Path)
    parser.add_argument('--sha256')
    parser.add_argument('--draft-model',type=Path)
    parser.add_argument('--draft-sha256')
    parser.add_argument('--draft-tokens',type=int,default=7,choices=range(1,8))
    parser.add_argument('--draft-policy',choices=('adaptive','fixed'),default='adaptive')
    parser.add_argument('--cut-replies',action='store_true',help='stop at native step boundaries after freezing clients')
    parser.add_argument('--benchmark',action='store_true',help='compare llama MTP, native AR and DFlash before qualification')
    args=parser.parse_args()
    with repair.ownership(Path.home()/'.CointOS') as owned:
        if not owned: raise SystemExit('runtime installation/repair lease is in use')
        if args.recover:
            Run(args.output).recover(); return
        if not all((args.executable,args.model_path,args.sha256)): parser.error('executable, model-path and sha256 required')
        whole=json.loads(args.config.read_text())
        config={k:whole[k] for k in ('lemonade','port','snapshots','disk_snapshots','models','scheduler','timeouts','memory','tick_seconds')}
        name=whole['work_model']
        options={'executable':str(args.executable.resolve()),'model_path':str(args.model_path.resolve()),'sha256':args.sha256}
        if args.draft_model:
            if not args.draft_sha256: parser.error('draft-sha256 required with draft-model')
            options['dflash']={'model_path':str(args.draft_model.resolve()),'sha256':args.draft_sha256,
                              'max_draft_tokens':args.draft_tokens,'policy':args.draft_policy}
        run=Run(args.output,config,name,options)
        def interrupted(signum,frame): raise KeyboardInterrupt()
        signal.signal(signal.SIGTERM,interrupted)
        try:
            run.park(args.cut_replies)
            if args.benchmark:
                from patches.gufo.benchmark import baseline, candidate
                baseline(run)
                run.qualify(candidate)
            else: run.qualify()
        except BaseException as error:
            run.journal['error']=f'{type(error).__name__}: {error}'; run.save()
            raise
        finally:
            run.recover()


if __name__=='__main__': main()
