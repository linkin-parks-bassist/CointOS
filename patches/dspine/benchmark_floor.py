#!/usr/bin/env python3
"""Private captured-prefix decode comparison, with recoverable production parking.

Results are assisted backend experiments, never autonomous acceptance evidence.
Use --recover OUTPUT after interruption. Captures and outputs remain private.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import statistics
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("qualification", ROOT / "patches/gufo/qualify.py")
q = importlib.util.module_from_spec(spec)
spec.loader.exec_module(q)


def summarize(rows):
    """Keep phase denominators matched; the minimum sample is not a guaranteed floor."""
    result = {}
    for arm in dict.fromkeys(row['arm'] for row in rows):
        group = [row for row in rows if row['arm'] == arm]
        rate = lambda row: row['timings']['predicted_n'] * 1000 / row['timings']['predicted_ms']
        proposed = sum(row['timings'].get('draft_n', 0) for row in group)
        accepted = sum(row['timings'].get('draft_n_accepted', 0) for row in group)
        result[arm] = {
            'samples': len(group),
            'pooled_decode_tps': sum(row['timings']['predicted_n'] for row in group) * 1000 /
                                 sum(row['timings']['predicted_ms'] for row in group),
            'draft_acceptance': accepted / proposed if proposed else None,
            'prefixes': {str(pos): {
                'median_decode_tps': statistics.median(rate(row) for row in group if row['position'] == pos),
                'minimum_sample_decode_tps': min(rate(row) for row in group if row['position'] == pos),
                'maximum_sample_decode_tps': max(rate(row) for row in group if row['position'] == pos),
            } for pos in sorted({row['position'] for row in group})},
        }
    return result


def terminate_build(run):
    unit = run.journal.get('floor_build_unit')
    if not unit:
        return
    state = subprocess.check_output(['systemctl', '--user', 'show', unit, '-p', 'LoadState', '--value'], text=True).strip()
    if state != 'not-found':
        q.systemctl('stop', unit)
    run.journal.pop('floor_build_unit', None)
    run.save()


def terminate_trial(run):
    child = run.journal.get("floor_trial")
    if not child:
        return
    proc = Path('/proc') / str(child['pid'])
    try:
        current_start = (proc / 'stat').read_text().split(') ', 1)[1].split()[19]
        if current_start == child['start'] and str((proc / 'exe').resolve()) == child['executable']:
            os.kill(child['pid'], signal.SIGTERM)
            deadline = time.monotonic() + 30
            while proc.exists():
                # A reaped-by-parent zombie has already released GPU allocations.
                if (proc / 'stat').read_text().split(') ', 1)[1].startswith('Z '):
                    break
                if time.monotonic() > deadline:
                    raise TimeoutError('private trial did not exit; production remains parked')
                time.sleep(.2)
    except FileNotFoundError:
        pass
    run.journal.pop('floor_trial', None)
    run.save()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path)
    ap.add_argument('--recover', type=Path)
    ap.add_argument('--summarize', type=Path, help='summarize an existing private output directory without touching production')
    ap.add_argument('--capture', type=Path)
    ap.add_argument('--positions', default='9195,9515,9835,10155')
    ap.add_argument('--seeds', default='193,321,777')
    ap.add_argument('--arms', default='mtp,dsp15')
    ap.add_argument('--cut-replies', action='store_true', help='park at completed native steps, retaining partial replies')
    ap.add_argument('--binary', type=Path, default=Path('/tmp/opencode/llama-dspine/build-static/bin/llama-server'))
    ap.add_argument('--control-binary', type=Path)
    ap.add_argument('--build-dir', type=Path, help='build llama-server after parking, before timing any trial')
    ap.add_argument('--build-jobs', type=int, default=2)
    ap.add_argument('--weights', type=Path)
    ap.add_argument('--draft', type=Path)
    ap.add_argument('--draft-q8', type=Path)
    ap.add_argument('--vector', type=Path)
    ap.add_argument('--target-kv', choices=['q8_0', 'f16'], default='q8_0')
    args = ap.parse_args()
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    if args.summarize:
        rows = json.loads((args.summarize/'results.json').read_text())
        report = summarize(rows)
        q.atomic_json(args.summarize/'summary.json', report)
        print(json.dumps(report, indent=2))
        return
    if args.recover:
        run = q.Run(args.recover)
        terminate_build(run)
        terminate_trial(run)
        run.recover()
        return
    if not args.output or not args.capture:
        ap.error('--output and --capture required')
    config = json.loads((Path.home()/'.CointOS/config/cointos.json').read_text())
    capture = json.loads(args.capture.read_text())
    tokens = capture['tokens']
    positions = [int(n) for n in args.positions.split(',')]
    seeds = [int(n) for n in args.seeds.split(',')]
    if not positions or min(positions) < 1 or max(positions) > len(tokens):
        raise ValueError('positions must select captured prefixes')
    arms = {
        'mtp': ['--spec-type', 'draft-mtp'],
        'mtp-prob': ['--spec-type', 'draft-mtp', '--spec-draft-sampling', 'probabilistic'],
        'mtp-prob-f16': ['--spec-type', 'draft-mtp', '--spec-draft-sampling', 'probabilistic'],
        'control-mtp-prob': ['--spec-type', 'draft-mtp', '--spec-draft-sampling', 'probabilistic'],
        'control-mtp-prob-repeat': ['--spec-type', 'draft-mtp', '--spec-draft-sampling', 'probabilistic'],
        'mtp-prob1': ['--spec-type', 'draft-mtp', '--spec-draft-n-max', '1', '--spec-draft-sampling', 'probabilistic'],
        'mtp-prob2': ['--spec-type', 'draft-mtp', '--spec-draft-n-max', '2', '--spec-draft-sampling', 'probabilistic'],
        'mtp-prob7': ['--spec-type', 'draft-mtp', '--spec-draft-n-max', '7', '--spec-draft-sampling', 'probabilistic'],
        'mtp-prob-p20': ['--spec-type', 'draft-mtp', '--spec-draft-sampling', 'probabilistic', '--spec-draft-p-min', '.2'],
        'none': [],
        'dsp15': ['--spec-type', 'draft-dflash', '--spec-draft-n-max', '15'],
        'dsp15-f16': ['--spec-type', 'draft-dflash', '--spec-draft-n-max', '15'],
        'dsp2': ['--spec-type', 'draft-dflash', '--spec-draft-n-max', '2'],
        'dsp3': ['--spec-type', 'draft-dflash', '--spec-draft-n-max', '3'],
        'dsp3-f16': ['--spec-type', 'draft-dflash', '--spec-draft-n-max', '3'],
        'dsp4': ['--spec-type', 'draft-dflash', '--spec-draft-n-max', '4'],
        'dsp7': ['--spec-type', 'draft-dflash', '--spec-draft-n-max', '7'],
        'dsp11': ['--spec-type', 'draft-dflash', '--spec-draft-n-max', '11'],
        'dsp8': ['--spec-type', 'draft-dflash', '--spec-draft-n-max', '15'],
        'dsp15-p50': ['--spec-type', 'draft-dflash', '--spec-draft-n-max', '15', '--spec-draft-p-min', '.5'],
        'dsp15-p10': ['--spec-type', 'draft-dflash', '--spec-draft-n-max', '15', '--spec-draft-p-min', '.1'],
        'dsp15-p20': ['--spec-type', 'draft-dflash', '--spec-draft-n-max', '15', '--spec-draft-p-min', '.2'],
    }
    selected = args.arms.split(',')
    if any(a not in arms for a in selected):
        raise ValueError('unknown arm')
    if any(a.startswith('control-') for a in selected) and (not args.control_binary or not args.control_binary.is_file()):
        raise ValueError('control arms require --control-binary')
    if 'dsp8' in selected and (not args.draft_q8 or not args.draft_q8.is_file()):
        raise ValueError('dsp8 requires --draft-q8')
    loaded = q.request(config['lemonade']+'/api/v1/health')['all_models_loaded']
    original = next(m for m in loaded if m['model_name'] == config['work_model'])
    launch = original['launch_command']
    weight = str(args.weights or launch[launch.index('-m')+1])
    draft = str(args.draft or launch[launch.index('--model-draft')+1])
    vector = str(args.vector or launch[launch.index('--control-vector')+1])
    base = [str(args.binary.resolve()), '-m', weight, '-ngl', '999', '-fa', 'on',
            '-c', str(max(positions)+1024), '-np', '1', '--jinja', '--metrics',
            '--batch-size', '512', '--ubatch-size', '128', '--cache-type-k', args.target_kv,
            '--cache-type-v', args.target_kv, '--control-vector', vector,
            '--control-vector-layer-range', '28', '36', '--no-prefill-assistant',
            '--host', '127.0.0.1', '--port', '8093']
    # Resolve every input and reserve the private endpoint before touching production.
    import socket
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 8093))
    if args.build_dir and not (args.build_dir/'CMakeCache.txt').is_file():
        raise ValueError('--build-dir must be configured before parking')
    if args.build_jobs < 1:
        raise ValueError('--build-jobs must be positive')
    for path in (*([] if args.build_dir else [args.binary]), Path(weight), Path(draft), Path(vector)):
        if not path.is_file():
            raise FileNotFoundError(path)
    args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
    run = q.Run(args.output, config, config['work_model'], {'executable': str(args.binary.resolve())})
    run.journal['floor_recipe'] = {'capture': str(args.capture.resolve()),
        'capture_sha256': q.sha256(args.capture), 'binary_sha256': None if args.build_dir else q.sha256(args.binary),
        'build_dir': str(args.build_dir.resolve()) if args.build_dir else None,
        'build_jobs': args.build_jobs if args.build_dir else None,
        'control_binary': str(args.control_binary.resolve()) if args.control_binary else None,
        'control_binary_sha256': q.sha256(args.control_binary) if args.control_binary else None,
        'inputs': {path: q.sha256(path) for path in (weight, draft, vector, *([str(args.draft_q8)] if args.draft_q8 else []))},
        'positions': positions, 'seeds': seeds, 'arms': selected,
        'commands': {}, 'harness_sha256': q.sha256(__file__),
        'sampling': {'temperature': 1, 'top_k': 20, 'top_p': .95, 'min_p': .05},
        'boundary': 'assisted private benchmark; no product tools executed'}
    run.save()
    q.copy_checked(args.capture, args.output/'fixture.json', run.journal['floor_recipe']['capture_sha256'])
    if args.build_dir:
        cache = (args.build_dir/'CMakeCache.txt').read_text()
        source = next(line.split('=', 1)[1] for line in cache.splitlines() if line.startswith('CMAKE_HOME_DIRECTORY:'))
        diff = subprocess.check_output(['git', '-C', source, 'diff', '--binary'])
        (args.output/'source.patch').write_bytes(diff)
        run.journal['floor_recipe']['source_revision'] = subprocess.check_output(['git', '-C', source, 'rev-parse', 'HEAD'], text=True).strip()
        run.journal['floor_recipe']['source_patch_sha256'] = hashlib.sha256(diff).hexdigest()
        run.save()
    rows = []
    try:
        run.park(cut_replies=args.cut_replies)
        if args.build_dir:
            run.phase('building private server before timed trials')
            unit = 'cointos-dspine-floor-build-' + hashlib.sha256(str(args.output.resolve()).encode()).hexdigest()[:12] + '.scope'
            run.journal['floor_build_unit'] = unit
            run.save()
            try:
                with (args.output/'build.log').open('w') as log:
                    subprocess.run(['systemd-run', '--user', '--scope', '--collect', '--quiet', '--unit', unit,
                                    'cmake', '--build', str(args.build_dir), '--target', 'llama-server', '-j', str(args.build_jobs)],
                                   stdout=log, stderr=subprocess.STDOUT, check=True)
            finally:
                terminate_build(run)
            run.journal['floor_recipe']['binary_sha256'] = q.sha256(args.binary)
            run.journal['floor_recipe']['cmake_cache_sha256'] = q.sha256(args.build_dir/'CMakeCache.txt')
            run.save()
        for arm in selected:
            command = base + arms[arm]
            if arm.endswith('-f16'):
                command[command.index('--cache-type-k')+1] = 'f16'
                command[command.index('--cache-type-v')+1] = 'f16'
            if arm.startswith('control-'):
                command[0] = str(args.control_binary.resolve())
            if arm.startswith('dsp'):
                arm_draft = str(args.draft_q8) if arm == 'dsp8' else draft
                command += ['-md', arm_draft, '--spec-draft-ngl', '999', '--spec-draft-type-k',
                            'q8_0', '--spec-draft-type-v', 'q8_0', '--spec-draft-sampling', 'probabilistic']
            run.journal['floor_recipe']['commands'][arm] = command
            run.save()
            run.phase('floor benchmark '+arm)
            with (args.output/(arm+'.log')).open('w') as log:
                process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
                try:
                    run.journal['floor_trial'] = {'pid': process.pid, 'executable': command[0],
                        'start': (Path('/proc')/str(process.pid)/'stat').read_text().split(') ',1)[1].split()[19]}
                    run.save()
                    deadline = time.monotonic()+config['timeouts']['model_launch_seconds']
                    while True:
                        if process.poll() is not None:
                            raise RuntimeError('private server failed: '+arm)
                        try:
                            q.request('http://127.0.0.1:8093/health', timeout=2)
                            break
                        except OSError:
                            if time.monotonic() > deadline:
                                raise TimeoutError('private server load')
                            time.sleep(1)
                    for pos in positions:
                        body = dict(run.journal['floor_recipe']['sampling'], prompt=tokens[:pos],
                                    cache_prompt=True, ignore_eos=True, stream=False, return_tokens=True)
                        q.request('http://127.0.0.1:8093/completion', dict(body, n_predict=32, seed=1), timeout=900)
                        for seed in seeds:
                            started=time.monotonic()
                            result=q.request('http://127.0.0.1:8093/completion', dict(body, n_predict=64, seed=seed), timeout=900)
                            timing=result['timings']
                            if timing['predicted_n'] != 64 or len(result.get('tokens', [])) != 64 or timing['predicted_ms'] <= 0:
                                raise RuntimeError('private trial did not return a complete timed 64-token sample')
                            row={'arm':arm,'position':pos,'seed':seed,'wall_seconds':time.monotonic()-started,
                                 'timings':timing, 'content':result.get('content'), 'tokens':result.get('tokens')}
                            rows.append(row)
                            q.atomic_json(args.output/'results.json', rows)
                            q.atomic_json(args.output/'summary.json', summarize(rows))
                            print(arm,pos,seed,round(timing['predicted_n']*1000/timing['predicted_ms'],2),
                                  'accepted',timing.get('draft_n_accepted'), '/',timing.get('draft_n'),flush=True)
                finally:
                    terminate_trial(run)
                    process.wait(timeout=5)
        run.journal['floor_finished']=True
        run.save()
    except BaseException as error:
        run.journal['error']=repr(error)
        run.save()
        raise
    finally:
        terminate_build(run)
        terminate_trial(run)
        run.recover()
    print('Captured-prefix benchmark complete; production restored. See results.json.', flush=True)


if __name__ == '__main__':
    main()
