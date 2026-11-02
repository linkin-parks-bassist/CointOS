"""Activate a qualified resident-state package with parked clients and rollback.

The original config, installed modules, caches, authority and process identities are
retained in the output directory. --recover rolls back an interrupted activation.
"""
import argparse
import copy
import json
from pathlib import Path
import shutil
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from cointos import backend_gufo as gufo, config, repair
from patches.gufo.qualify import Run, atomic_json, sha256, systemctl, service

MODULES = ('lanes.py', 'backend_gufo.py', 'backend_native.py')
INSTALLED = Path.home() / '.CointOS'
SOURCE = Path(__file__).resolve().parents[2]


def rollback(run):
    activation = run.journal.get('activation')
    if activation and activation.get('mutating'):
        systemctl('stop', 'cointosd.service')
        gufo.kill(run.config, run.journal['model'])
        for name in activation.get('modules', MODULES):
            shutil.copy2(run.output / 'installed-backup' / name, INSTALLED / 'cointos' / name)
        config.write_json(INSTALLED / 'config/cointos.json', activation['original_document'])
        run.config = activation['original_config']
        run.journal['config'] = run.config
        activation['mutating'] = False
        run.journal['restored'] = False
        run.journal['daemon_stopped'] = True
        run.save()
    run.recover()


def activate(run, executable, *, modules=MODULES, models=None):
    run.park(cut_replies=True)
    original = json.loads((INSTALLED / 'config/cointos.json').read_text())
    saved = run.output / 'installed-backup'
    saved.mkdir(mode=0o700)
    for name in modules:
        shutil.copy2(INSTALLED / 'cointos' / name, saved / name)
    desired = copy.deepcopy(original)
    for name, shape in desired['models'].items():
        if shape.get('backend') == 'gufo' and (models is None or name in models):
            shape['gufo']['executable'] = str(executable)
    run.journal['activation'] = {'original_document': original, 'original_config': copy.deepcopy(run.config),
                                 'desired_document': desired, 'mutating': True,
                                 'modules': list(modules)}
    run.save()  # rollback intent precedes any installed mutation
    for name in modules:
        shutil.copy2(SOURCE / 'cointos' / name, INSTALLED / 'cointos' / name)
        if sha256(SOURCE / 'cointos' / name) != sha256(INSTALLED / 'cointos' / name):
            raise RuntimeError('installed module differs: ' + name)
    config.write_json(INSTALLED / 'config/cointos.json', desired)
    run.config = config.load(INSTALLED / 'config/cointos.json')
    run.phase('restoring cache hints and warming resident-capable production')
    run.restore_files('caches')
    run.prepare_production()
    info = gufo._call(run.config, run.journal['model'], 'info')
    if info.get('resident_switch') is not True:
        raise RuntimeError('production does not support resident selection')
    systemctl('start', 'cointosd.service')
    deadline = time.monotonic() + run.config['timeouts']['agent_start_seconds']
    while True:
        try:
            run.api('cancel-restart', {})
            after = run.api('ledger')
            break
        except OSError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.2)
    for ident, before in run.journal['drained_ledger']['agents'].items():
        adopted = after['agents'].get(ident)
        if adopted is None or any(adopted.get(k) != before.get(k)
                for k in ('task', 'session', 'pid', 'generation_seconds', 'generation_tokens')):
            raise RuntimeError('adoption changed identity/spend: ' + ident)
    run.check_parked_units()
    run.check_gateway_authority(json.loads((INSTALLED / 'state/keys.json').read_text()))
    for path, expected in run.journal['authority'].items():
        if path.endswith(('/config/cointos.json', '/state/keys.json')):
            continue
        if sha256(path) != expected:
            raise RuntimeError('authority/enrollment changed: ' + path)
    run.journal['activation']['verified'] = {'native': info, 'agents': after['agents'],
        'modules': {name: sha256(INSTALLED / 'cointos' / name) for name in modules}}
    run.save()
    for unit in run.journal['units']:
        systemctl('thaw', unit)
    run.journal.update(restored=True, daemon_stopped=False, draining=False, activated=True)
    run.save()
    run.phase('resident-state activation verified; clients resumed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--executable', type=Path)
    parser.add_argument('--qualification', type=Path)
    parser.add_argument('--recover', action='store_true')
    args = parser.parse_args()
    with repair.ownership(INSTALLED) as acquired:
        if not acquired:
            raise RuntimeError('independent repair owns runtime installation')
        if args.recover:
            run = Run(args.output)
            if run.journal.get('activated'):
                raise RuntimeError('completed activation: retain the running installation')
            rollback(run)
            return
        if not args.executable or not args.qualification:
            parser.error('--executable and --qualification required')
        result = json.loads(args.qualification.read_text())
        if not result.get('passed') or not result.get('sampled_vectors_equal'):
            raise RuntimeError('resident qualification did not pass')
        if (str(args.executable.resolve()) != result.get('executable')
                or sha256(args.executable.resolve().with_name('gufo-control.bin')) != result.get('binary_sha256')):
            raise RuntimeError('candidate executable differs from qualified binary')
        current = config.load(INSTALLED / 'config/cointos.json')
        model = current['work_model']
        if model != result['model']:
            raise RuntimeError('selected model changed since qualification')
        run = Run(args.output, current, model, current['models'][model]['gufo'])
        try:
            activate(run, args.executable.resolve())
        except BaseException as error:
            run.journal['error'] = repr(error)
            run.save()
            rollback(run)
            raise


if __name__ == '__main__':
    main()
