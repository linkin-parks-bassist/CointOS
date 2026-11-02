"""Disk model catalog, default routing and transactional native model replacement."""
from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
import struct
import threading

from cointos import config as configuration, lanes, memory, replacement, snapshots
from cointos.state import ACTIVE, BACKEND, CONFIG, LOCK, L, STOPPING, log, now, save


def metadata(path: Path) -> dict:
    """Read GGUF metadata without loading tensors or large tokenizer arrays."""
    with path.open('rb') as stream:
        def number(fmt):
            size = struct.calcsize(fmt)
            value = stream.read(size)
            if len(value) != size:
                raise ValueError('truncated GGUF metadata')
            return struct.unpack(fmt, value)[0]
        def string(keep=True):
            length = number('<Q')
            if length > path.stat().st_size - stream.tell():
                raise ValueError('truncated GGUF string')
            if keep:
                return stream.read(length).decode('utf-8')
            stream.seek(length, 1)
        def value(kind, keep=True):
            formats = {0: '<B', 1: '<b', 2: '<H', 3: '<h', 4: '<I', 5: '<i',
                       6: '<f', 7: '<?', 10: '<Q', 11: '<q', 12: '<d'}
            if kind in formats:
                return number(formats[kind])
            if kind == 8:
                return string(keep)
            if kind == 9:
                element, count = number('<I'), number('<Q')
                if element in formats:
                    stream.seek(struct.calcsize(formats[element]) * count, 1)
                elif element == 8:
                    for _ in range(count):
                        string(False)
                else:
                    raise ValueError('unsupported GGUF array type')
                return None
            raise ValueError('invalid GGUF value type')
        if stream.read(4) != b'GGUF' or number('<I') not in (2, 3):
            raise ValueError('not a supported GGUF file')
        tensors, count = number('<Q'), number('<Q')
        result = {'tensors': tensors}
        for _ in range(count):
            key, kind = string(), number('<I')
            keep = key in ('general.architecture', 'general.name', 'general.type', 'split.count') or key.endswith('.context_length')
            item = value(kind, keep)
            if keep:
                result[key] = item
        if stream.tell() > path.stat().st_size:
            raise ValueError('truncated GGUF metadata')
        return result


def required() -> set[str]:
    """Only explicit requirements keep another engine loaded."""
    return {CONFIG['work_model']} | ({CONFIG['coin']['model']} if CONFIG['coin'].get('model') else set())


def resolve(requested=None, required_model=None) -> str:
    if required_model is not None:
        if required_model not in required():
            raise ValueError('required model is not configured for concurrent use')
        return required_model
    # Concrete names retained by already-running clients follow the same default.
    if requested in (None, 'default', 'work') or requested in CONFIG['models']:
        return CONFIG['work_model']
    raise ValueError(f'unknown model {requested!r}')


def catalog() -> list[dict]:
    with LOCK:
        recipes = deepcopy(CONFIG['models'])
        roots = list(CONFIG.get('model_directories', []))
    known = {str(Path(s['gufo']['model_path']).expanduser().resolve()): name
             for name, s in recipes.items() if s.get('backend') == 'gufo'}
    roots += [str(Path(path).parent) for path in known]
    paths = set(known)
    entries = []
    for root in set(roots):
        directory = Path(root).expanduser()
        try:
            if directory.is_dir():
                paths.update(str(p.resolve()) for p in directory.rglob('*.gguf') if p.is_file())
        except OSError as error:
            entries.append({'id': str(directory), 'name': str(directory), 'available': False,
                            'reason': f'Cannot inspect directory: {error.strerror}'})
    for filename in sorted(paths):
        path = Path(filename)
        if not path.is_file():
            continue
        try:
            info = metadata(path)
            # Draft and vision-only companions are not chat models.
            if (any(word in path.name.lower() for word in ('dflash', 'mmproj', '-mtp.'))
                    or info.get('general.type') in ('adapter', 'projector')):
                continue
            reason = ''
            if info.get('split.count', 1) != 1:
                reason = 'Split GGUF files need a complete backend recipe'
            elif filename not in known and info.get('general.architecture') != 'qwen35':
                reason = 'No qualified native backend recipe for this architecture'
            entries.append({'id': filename, 'name': path.stem, 'bytes': path.stat().st_size,
                            'model': known.get(filename), 'architecture': info.get('general.architecture'),
                            'available': not reason, 'reason': reason})
        except (OSError, ValueError, struct.error) as error:
            entries.append({'id': filename, 'name': path.stem, 'available': False, 'reason': str(error)})
    return entries


def status() -> dict:
    name = CONFIG['work_model']
    shape = CONFIG['models'][name]
    return {'model': name, 'path': str(Path(shape['gufo']['model_path']).expanduser().resolve())
            if shape.get('backend') == 'gufo' else None,
            'discovery_seconds': CONFIG['dashboard']['model_discovery_seconds'],
            **L.get('model_change', {'phase': 'ready'})}


def choose(body) -> dict:
    """Validate the disk selection now, perform slow I/O outside the ledger lock."""
    if set(body) != {'path'} or not isinstance(body['path'], str):
        raise ValueError('Expected a discovered model path')
    if L.get('model_change', {}).get('phase') in ('checking', 'draining', 'loading', 'restoring'):
        raise ValueError('A default model change is already in progress')
    path = str(Path(body['path']).expanduser().resolve())
    L['model_change'] = {'phase': 'checking', 'requested': path, 'since': now()}
    threading.Thread(target=replace, args=(path,), daemon=True, name='default-model').start()
    return {'ok': True, **status()}


def recipe(entry) -> tuple[str, dict]:
    with LOCK:
        if entry.get('model'):
            return entry['model'], deepcopy(CONFIG['models'][entry['model']])
        template = next((deepcopy(s) for s in CONFIG['models'].values() if s.get('backend') == 'gufo'), None)
    if template is None:
        raise ValueError('No native GGUF launch recipe is configured')
    path = Path(entry['id'])
    before = path.stat()
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if path.stat() != before:
        raise ValueError('Model changed while checking its identity')
    name = path.stem
    template['gufo'].update(model_path=str(path), sha256=digest,
                            socket=str(configuration.STATE / 'gufo' / digest[:16] / 'control.sock'))
    template['gufo'].pop('dflash', None)  # draft compatibility must be explicitly qualified
    overhead = template['memory_gb'] - template['weights_gb']
    template['weights_gb'] = before.st_size / memory.GB
    template['memory_gb'] = template['weights_gb'] + overhead
    info = metadata(path)
    context = info.get(info['general.architecture'] + '.context_length', template['ctx_size'])
    template['ctx_size'] = min(template['ctx_size'] // template['lanes'], context)
    template['lanes'] = 1
    return name, template


def _phase(phase, **fields):
    with LOCK:
        L['model_change'].update(phase=phase, **fields)
        LOCK.notify_all()
    save()


def replace(path):
    with replacement.lease(configuration.ROOT, shared=True) as acquired:
        if not acquired:
            _phase('failed', error='Runtime installation in progress; retry the model change')
            return
        _replace(path)


def _replace(path):
    old, candidate, unloaded, persisted, attempted = None, None, False, False, False
    try:
        entry = next((e for e in catalog() if e['id'] == path), None)
        if not entry or not entry['available']:
            raise ValueError(entry['reason'] if entry else 'Model is not a downloaded catalog choice')
        name, shape = recipe(entry)
        with LOCK:
            old = deepcopy(CONFIG)
            if name == old['work_model']:
                L['model_change'] = {'phase': 'ready'}
                return
        _phase('draining')
        # Admission closes before waiting; every current reply and native step finishes.
        with LOCK:
            while ACTIVE['chats'] or any(m['launching'] for m in L['models'].values()):
                if STOPPING.is_set():
                    raise ValueError('Daemon stopped before model replacement')
                LOCK.wait(CONFIG["tick_seconds"])
            if STOPPING.is_set():
                raise ValueError('Daemon stopped before model replacement')
        candidate = deepcopy(old)
        if name in candidate['models'] and candidate['models'][name] != shape:
            raise ValueError('Model name conflicts with another launch recipe')
        candidate['models'][name] = shape
        candidate['work_model'] = name
        _phase('loading')
        # Persist desired identity before touching native processes. Restart can finish it.
        _persist(candidate)
        persisted = True
        if old['work_model'] != old['coin'].get('model'):
            BACKEND.kill(old, old['work_model'])
            unloaded = True
        # Native readiness and shape verification precede publication of the choice.
        with LOCK:
            measured = memory.measure()
            L['memory'].update(measured, headroom_gb=memory.headroom_gb(candidate, measured, BACKEND.budget(candidate)))
            already_up = L['models'].get(name, {}).get('up', False)
            if not already_up and not snapshots.make_room(shape['memory_gb']):
                raise ValueError('Not enough memory headroom for the selected model')
        attempted = not already_up
        BACKEND.launch(candidate, name)
        with LOCK:
            CONFIG['models'][name] = shape
            CONFIG['work_model'] = name
            if name not in L['models']:
                L['models'][name] = {'up': False, 'launching': False, 'problems': []}
                L['model_memory'][name] = {k: shape[k] for k in ('memory_gb', 'weights_gb')}
                L['model_memory'][name]['weights_reclaimable'] = shape.get('backend', 'llama') != 'gufo'
                for index in range(shape['lanes']):
                    position = len(L['lanes'])
                    L['lanes'].append({'model': name, 'index': index, 'up': False, 'holder': None,
                        'resident': None, 'free_since': now(), 'held_for': None, 'held_class': None,
                        'held_until': 0, 'turn_agent': None, 'turn_since': 0})
                    threading.Thread(target=lanes.worker, args=(position,), daemon=True).start()
            if unloaded:
                L['models'][old['work_model']].update(up=False, problems=[])
                lanes.lanes_down(old['work_model'])
            L['models'][name].update(up=True, problems=[])
            lanes.lanes_up(name)
            for agent in L['agents'].values():
                agent['last_activity'] = now()  # loading time is not an agent stall
            log('default model changed', previous=old['work_model'], model=name)
        _phase('ready', error=None)
    except Exception as error:
        detail = str(error)
        if attempted:
            try:
                BACKEND.kill(candidate, candidate['work_model'])
            except Exception as cleanup:
                detail += f'; new model cleanup: {cleanup}'
        if persisted:
            try:
                _persist(old)
            except Exception as persistence:
                detail += f'; previous selection persistence: {persistence}'
        if unloaded:
            _phase('restoring')
            try:
                BACKEND.launch(old, old['work_model'])
            except Exception as restore:
                detail += f'; previous model restore: {restore}'
        _phase('failed', error=detail)
    finally:
        with LOCK:
            LOCK.notify_all()
        save()


def _persist(config):
    with LOCK:
        path = configuration.CONFIG
        document = configuration.read_owned_json(path)
        document.update(models=config['models'], work_model=config['work_model'])
        configuration.write_json(path, document, mode=path.stat().st_mode & 0o777)


def retire_unused():
    """Finish crash-interrupted replacement: only desired engines may survive startup."""
    for name in CONFIG['models']:
        if name not in required():
            BACKEND.kill(CONFIG, name)


def changing() -> bool:
    return L.get('model_change', {}).get('phase') in ('draining', 'loading', 'restoring')
