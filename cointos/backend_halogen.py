"""Experimental bounded Halogen steps with RAM-only retained-cache switching."""
import json
import base64
import math
import subprocess
import urllib.request
from pathlib import Path
from . import backend_chat, backend_llama

Lost = backend_llama.Lost
_EPOCH = {}


def _options(config, model):
    return config['models'][model]['halogen']


def _call(config, model, op, **body):
    options = _options(config, model)
    req = urllib.request.Request(options['url'] + '/cointos/control',
        json.dumps({'op': op, **body}).encode(), {'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=config['timeouts']['server_seconds']) as response:
        event = json.load(response)
    if 'error' in event:
        if event['error'].startswith('lost:'):
            raise Lost(event['error'])
        raise RuntimeError(event['error'])
    return event['result']


def _call_stream(config, model, on_tokens, **body):
    options = _options(config, model)
    req = urllib.request.Request(options['url'] + '/cointos/control',
        json.dumps({'op': 'think', 'stream': True, **body}).encode(),
        {'Content-Type': 'application/json'})
    delivered = []
    with urllib.request.urlopen(req, timeout=config['timeouts']['server_seconds']) as response:
        if response.headers.get_content_type() != 'application/x-ndjson':
            # Allows the daemon and frontend to be replaced independently.
            event = json.load(response)
        else:
            for line in response:
                event = json.loads(line)
                if 'stream' not in event:
                    break
                frame = event['stream']
                tokens, pieces = frame.get('tokens'), frame.get('pieces')
                if (not isinstance(tokens, list) or not tokens
                        or any(type(t) is not int or not 0 <= t < 248077 for t in tokens)
                        or len(delivered) + len(tokens) > body['max_new']
                        or not isinstance(pieces, str)):
                    raise RuntimeError('Halogen returned an invalid token frame')
                try:
                    raw = base64.b64decode(pieces, validate=True)
                except ValueError as error:
                    raise RuntimeError('Halogen returned invalid token bytes') from error
                delivered.extend(tokens)
                on_tokens(tokens, raw)
            else:
                raise RuntimeError('Halogen stream ended without a terminal response')
    if 'error' in event:
        if event['error'].startswith('lost:'):
            raise Lost(event['error'])
        raise RuntimeError(event['error'])
    result = event['result']
    if delivered and delivered != result.get('tokens'):
        raise RuntimeError('Halogen streamed tokens differ from its completed step')
    return result, bool(delivered)


def models(config):
    found = {}
    for model, shape in config['models'].items():
        try:
            info = _call(config, model, 'info')
            if (info['protocol'] != 1 or info['version'] != '0.20.5'
                    or info['context'] != shape['ctx_size'] or shape['lanes'] != 1
                    or info['experimental_cache_switch'] is not True):
                raise RuntimeError('Halogen native identity/shape mismatch')
            _EPOCH[model] = info['epoch']
            found[model] = {'lanes': 1, 'resident_state_bytes': info['resident_state_bytes']}
        except (OSError, ValueError, RuntimeError) as error:
            _EPOCH.pop(model, None)
            found[model] = {'problems': [str(error)]}
    return found


def budget(config):
    # SVM-pinned file-backed weights still appear reclaimable in MemAvailable.
    # Subtract the configured, verified payload before granting more allocations.
    values = {line.split(':')[0]: int(line.split()[1]) * 1024
              for line in Path('/proc/meminfo').read_text().splitlines()}
    weights = sum(s['weights_gb'] for m, s in config['models'].items()
                  if s.get('backend') == 'halogen' and m in _EPOCH)
    return {'used_gb': weights,
            'limit_gb': values['MemAvailable'] / 1e9 - config['memory']['reserve_gb']}


def launch(config, model):
    options = _options(config, model)
    try:
        _call(config, model, 'info')
    except OSError:
        from .halogen_runtime import start
        start(config, model)
    problems = models({**config, 'models': {model: config['models'][model]}})[model].get('problems')
    if problems:
        raise RuntimeError('; '.join(problems))
    room = budget(config)
    if room['limit_gb'] - room['used_gb'] < 0:
        raise RuntimeError('Halogen would consume the preserved host memory reserve')


def kill(config, model):
    if subprocess.run(['podman', 'container', 'exists', _options(config, model)['container']]).returncode:
        _EPOCH.pop(model, None)
        return
    subprocess.run(['podman', 'stop', '--time', '60', _options(config, model)['container']], check=True,
                   stdout=subprocess.DEVNULL)
    subprocess.run(['podman', 'rm', _options(config, model)['container']], check=True,
                   stdout=subprocess.DEVNULL)
    _EPOCH.pop(model, None)


IMAGE_OMITTED = ('[image omitted: this CointOS model lane does not receive image pixels; '
                 'use a text alternative such as a page snapshot]')


def _textual(part):
    """Replace a non-text content part with a note. The control render sends no pixels,
    so a rendered image placeholder would make the engine refuse every later turn."""
    if isinstance(part, dict) and part.get('type') == 'text':
        return part
    return {'type': 'text', 'text': IMAGE_OMITTED}


def render(config, model, conversation):
    body = backend_chat.prepare(conversation)
    messages = []
    for message in body['messages']:
        if message.get('tool_calls'):
            calls = []
            for call in message['tool_calls']:
                function = call['function']
                arguments = function.get('arguments', {})
                if isinstance(arguments, str):
                    arguments = json.loads(arguments)
                if not isinstance(arguments, dict):
                    raise ValueError('Halogen tool-call arguments must be a JSON object')
                calls.append({**call, 'function': {**function, 'arguments': arguments}})
            message = {**message, 'tool_calls': calls}
        if isinstance(message.get('content'), list):
            message = {**message, 'content': [_textual(part) for part in message['content']]}
        messages.append(message)
    result = _call(config, model, 'render', **{**body, 'messages': messages})
    def tokenize(value):
        return _http(config, model, '/tokenize', {'content': value, 'add_special': False})['tokens']
    return {'tokens': result['tokens'], 'reader': backend_chat.reader(conversation, result['prompt'], tokenize)}


def _http(config, model, route, body):
    req = urllib.request.Request(_options(config, model)['url'] + route,
        json.dumps(body).encode(), {'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=config['timeouts']['server_seconds']) as response:
        return json.load(response)


def can_continue(config, model, held, tokens):
    return bool(held) and len(held) <= len(tokens) and tokens[:len(held)] == held


def resident_states(config, model): return True

def resident_capacity(config, model): return None

def eviction(config, model, owner): return None


def select(config, model, lane, owner):
    result = _call(config, model, 'select', lane=lane, owner=owner)
    return result['tokens']


def release_residents(config, model, owners):
    _call(config, model, 'release_residents', owners=owners)


def residents(config, model): return _call(config, model, 'info')['owners']

def resident_bytes(config, model): return _call(config, model, 'info')['resident_state_bytes']


def prefill(config, model, lane, tokens, held):
    result = _call(config, model, 'prefill', lane=lane, tokens=tokens, held=held,
                   max_input_tokens=config['scheduler']['read_chunk_tokens'])
    if result['held'] != len(tokens) or result['tokens']:
        raise RuntimeError('Halogen prefill retained an unknown token vector')
    return result


def think(config, model, lane, tokens, held, max_new, sampling, on_tokens):
    event, streamed = _call_stream(config, model, on_tokens, lane=lane, tokens=tokens, held=held,
                  max_new=max_new, sampling=sampling,
                  max_input_tokens=config['scheduler']['read_chunk_tokens'])
    new = event['tokens']
    if (not isinstance(new, list) or any(type(t) is not int or not 0 <= t < 248077 for t in new)
            or len(new) > max_new or event['held'] != len(tokens) + len(new)
            or type(event['done']) is not bool or (not new and not event['done'])
            or type(event['generation_seconds']) not in (int, float)
            or not math.isfinite(event['generation_seconds']) or event['generation_seconds'] < 0):
        raise RuntimeError('Halogen returned an incomplete bounded step')
    if new and not streamed:
        on_tokens(new)
    seconds = event['generation_seconds']
    return {**event, 'held': tokens + new, 'sampling': sampling,
            'rate': len(new) / seconds if seconds and len(new) >= 16 else None}


def text(config, model, tokens):
    return _http(config, model, '/detokenize', {'tokens': tokens})['content'] if tokens else ''


def read(config, model, reader, tokens, final):
    return backend_chat.read(reader, text(config, model, tokens), final)


def cache_kind(config, model): return None

def restore(config, model, lane, name): return False

def save(config, model, lane, name): raise RuntimeError('Halogen retained caches are not durable snapshots')

def snapshot_files(config, tier=None): return []

def forget(config, name): pass

def forget_untracked(config, memory_names, disk_names): return []


def recover_transfer(config, name, expected_bytes): return None
