"""Qualify resident pointer selection against real preserved production histories.

Uses qualify.Run's recoverable parked transaction. Never installs the candidate.
"""
import argparse
import json
from pathlib import Path
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from cointos import backend_gufo as gufo, backend_llama, config, repair
from patches.gufo.qualify import Run, atomic_json, available_gb, copy_checked, sha256


def replay_sampling(header):
    """Seed prompt-only snapshots; saved sampler/RNG state remains authoritative."""
    sampling = dict(header.get('sampling') or {})
    if 'rng' not in header and sampling.get('seed', -1) < 0:
        sampling['seed'] = 193
    return sampling


def qualify(run, fixture_paths=()):
    name = run.journal['model']
    run.trial = run.trial_config()
    run.phase('loading candidate for resident-state qualification')
    gufo.launch(run.trial, name)
    info = gufo._call(run.trial, name, 'info')
    if info.get('resident_switch') is not True:
        raise RuntimeError('candidate has no resident selection contract')
    reserve = run.config['memory']['reserve_gb']
    # Avoid speculative allocations: protect the configured workstation reserve
    # using the runner's own per-state resource claim, including scratch.
    need = info['resident_state_bytes'] / 1e9
    if available_gb() < reserve + need * 2:
        raise RuntimeError('two resident states do not fit with the workstation reserve')
    snapshots = run.journal['drained_ledger']['snapshots']
    backups = {Path(e['source']).name: e for e in run.journal['caches'] if e['ready']}
    histories = []
    for owner in sorted({a['task'] for a in run.journal['agents'].values()}):
        choices = [(s['tokens'], key) for key, s in snapshots.items()
                   if s['model'] == name and s['owner'] == owner and s['tier'] == 'memory'
                   and s['tokens'] < info['context'] - 96
                   and backend_llama._snapshot(key) in backups]
        if not choices:
            continue
        _, key = max(choices)
        source = Path(backups[backend_llama._snapshot(key)]['backup'])
        filename = f'resident-input-{len(histories)}'
        destination = Path(run.trial['snapshots']) / 'gufo' / (filename + '.bin')
        copy_checked(source, destination)
        with source.open('rb') as stream:
            header = json.loads(stream.readline())
        histories.append({'owner': owner, 'name': filename, 'tokens': header['tokens'],
                          'sampling': replay_sampling(header)})
    if fixture_paths:
        histories = []
        for index, source in enumerate(fixture_paths):
            source = Path(source)
            filename = f'resident-fixture-{index}'
            destination = Path(run.trial['snapshots']) / 'gufo' / (filename + '.bin')
            copy_checked(source, destination)
            with source.open('rb') as stream:
                header = json.loads(stream.readline())
            histories.append({'owner': filename, 'name': filename, 'tokens': header['tokens'],
                              'sampling': replay_sampling(header)})
    if len(histories) < 2:
        raise RuntimeError('two preserved production histories are required')
    a, b = histories[:2]

    def load(owner, history):
        gufo.select(run.trial, name, 0, owner)
        if not gufo.restore(run.trial, name, 0, history['name']):
            raise RuntimeError('production history import failed')

    def think(tokens, sampling):
        out = gufo.think(run.trial, name, 0, tokens, len(tokens), 32, sampling, lambda *_: None)
        if available_gb() < reserve:
            raise RuntimeError('resident qualification crossed the workstation reserve')
        return out

    run.phase('recording uninterrupted sampled continuation at production context length')
    load('reference', a)
    first = think(a['tokens'], a['sampling'])
    expected = think(first['held'], a['sampling'])
    gufo.release_residents(run.trial, name, ['reference'])
    run.phase('alternating resident production histories without persistence')
    load('a', a)
    replay = think(a['tokens'], a['sampling'])
    atomic_json(run.output / 'resident-initial-vectors.json', {'first': first, 'replay': replay})
    if replay['tokens'] != first['tokens']:
        raise RuntimeError('initial sampled vector changed after identical import')
    load('b', b)
    other = think(b['tokens'], b['sampling'])
    state = {'a': replay['held'], 'b': other['held']}
    elapsed = []
    files_before = {p.name: (p.stat().st_size, p.stat().st_mtime_ns)
                    for p in (Path(run.trial['snapshots']) / 'gufo').iterdir()}
    for owner in ['a', 'b'] * 12 + ['a']:
        start = time.monotonic()
        held = gufo.select(run.trial, name, 0, owner)
        elapsed.append(time.monotonic() - start)
        if held != state[owner]:
            raise RuntimeError('resident selection changed retained tokens')
    actual = think(state['a'], a['sampling'])
    if actual['tokens'] != expected['tokens']:
        raise RuntimeError('resident switch changed sampled continuation/RNG')
    files_after = {p.name: (p.stat().st_size, p.stat().st_mtime_ns)
                   for p in (Path(run.trial['snapshots']) / 'gufo').iterdir()}
    if files_after != files_before:
        raise RuntimeError('resident switching wrote persistence files')
    run.phase('checking real-model persistent sampled continuation')
    gufo.save(run.trial, name, 0, 'resident-roundtrip')
    continued = think(actual['held'], a['sampling'])
    if not gufo.restore(run.trial, name, 0, 'resident-roundtrip'):
        raise RuntimeError('new candidate snapshot import failed')
    restored = think(actual['held'], a['sampling'])
    atomic_json(run.output / 'resident-roundtrip-vectors.json',
                {'continued': continued, 'restored': restored})
    if restored['tokens'] != continued['tokens']:
        raise RuntimeError('persistent sampled continuation changed')
    executable = Path(run.journal['options']['executable']).resolve()
    result = {'passed': True, 'context_tokens': [len(a['tokens']), len(b['tokens'])],
              'executable': str(executable), 'binary_sha256': sha256(executable.with_name('gufo-control.bin')),
              'model': name, 'info': info, 'switches': len(elapsed),
              'switch_seconds': elapsed, 'median_switch_seconds': statistics.median(elapsed),
              'maximum_switch_seconds': max(elapsed), 'sampled_vectors_equal': True,
              'persistence_files_unchanged': True, 'persistent_continuation_equal': True, 'available_gb_after': available_gb(),
              'resident_state_estimate_gb': need}
    atomic_json(run.output / 'resident-result.json', result)
    run.journal['test']['resident'] = result
    run.save()
    print(json.dumps(result), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--executable', type=Path)
    parser.add_argument('--recover', action='store_true')
    args = parser.parse_args()
    installed = Path.home() / '.CointOS'
    with repair.ownership(installed) as acquired:
        if not acquired:
            raise RuntimeError('independent repair owns runtime installation')
        if args.recover:
            Run(args.output).recover()
            return
        if args.executable is None:
            parser.error('--executable required for qualification')
        current = config.load(installed / 'config/cointos.json')
        model = current['work_model']
        options = {**current['models'][model]['gufo'], 'executable': str(args.executable.resolve())}
        run = Run(args.output, current, model, options)
        try:
            run.park(cut_replies=True)
            qualify(run)
        except BaseException as error:
            run.journal['error'] = repr(error)
            run.save()
            raise
        finally:
            run.recover()


if __name__ == '__main__':
    main()
