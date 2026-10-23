"""Per-model native backend dispatch; CointOS retains lane and snapshot ownership."""
from pathlib import Path
from . import backend_gufo, backend_llama

Lost = backend_llama.Lost


def _backend(config, model):
    name = config['models'][model].get('backend', 'llama')
    return {'llama': backend_llama, 'gufo': backend_gufo}[name]


def models(config):
    found = {}
    for backend in (backend_llama, backend_gufo):
        shapes = {name: shape for name, shape in config['models'].items() if _backend(config, name) is backend}
        if shapes:
            found.update(backend.models({**config, 'models': shapes}))
    return found


def budget(config):
    return backend_llama.budget(config) if any(_backend(config, name) is backend_llama for name in config['models']) else None


def launch(config, model): return _backend(config, model).launch(config, model)
def kill(config, model): return _backend(config, model).kill(config, model)
def render(config, model, conversation): return _backend(config, model).render(config, model, conversation)
def can_continue(config, model, held, tokens): return _backend(config, model).can_continue(config, model, held, tokens)
def prefill(config, model, lane, tokens, held): return _backend(config, model).prefill(config, model, lane, tokens, held)
def think(config, model, lane, tokens, held, max_new, sampling, on_tokens):
    return _backend(config, model).think(config, model, lane, tokens, held, max_new, sampling, on_tokens)
def text(config, model, tokens): return _backend(config, model).text(config, model, tokens)
def read(config, model, reader, tokens, final): return _backend(config, model).read(config, model, reader, tokens, final)
def save(config, model, lane, name): return _backend(config, model).save(config, model, lane, name)
def restore(config, model, lane, name): return _backend(config, model).restore(config, model, lane, name)


def _stored(config, name, tier):
    path = Path(config[tier]).expanduser() / 'gufo' / backend_llama._snapshot(name)
    return backend_gufo if path.exists() else backend_llama


def spill(config, name): _stored(config, name, 'snapshots').spill(config, name)
def unspill(config, name): _stored(config, name, 'disk_snapshots').unspill(config, name)
def copy_back(config, name): _stored(config, name, 'disk_snapshots').copy_back(config, name)
def forget(config, name):
    for backend in (backend_llama, backend_gufo): backend.forget(config, name)


def cache_kind(config, model):
    return _backend(config, model).cache_kind(config, model) if model in config['models'] else None


def snapshot_files(config, tier=None):
    return [entry for backend in (backend_llama, backend_gufo) for entry in backend.snapshot_files(config, tier)]


def delete_snapshot_file(config, entry):
    return {'llama': backend_llama, 'gufo': backend_gufo}[entry['backend']].delete_snapshot_file(config, entry)


def recover_transfer(config, model, name, expected_bytes):
    if model not in config['models']:
        return None
    return _backend(config, model).recover_transfer(config, name, expected_bytes)


def forget_untracked(config, memory_names, disk_names):
    return [path for backend in (backend_llama, backend_gufo)
            for path in backend.forget_untracked(config, memory_names, disk_names)]
