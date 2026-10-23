"""Exact Gufo tool-cycle history, conditional on the client's delivered transcript."""
import hashlib
import json
import os
import re

from . import backend_gufo as gufo, privatejson


def _filename(owner):
    if not re.fullmatch(r'[A-Za-z0-9_-]+', owner[0]):
        raise ValueError('invalid cache owner')
    return owner[0] + '.json'


def _validate_cache(value):
    if not isinstance(value, dict) or set(value) != {'format', 'owner', 'record', 'checksum'} or type(value['format']) is not int or value['format'] != 1:
        raise ValueError('invalid tool history cache')
    owner, record = value['owner'], value['record']
    if (not isinstance(owner, (list, tuple)) or len(owner) != 3
            or not all(isinstance(x, str) and x for x in owner[:2])
            or (owner[2] is not None and (type(owner[2]) is not int or owner[2] < 0))):
        raise ValueError('invalid cache ownership')
    if not isinstance(record, dict) or set(record) != {'model','digest','count','ids','end','held','terminal'}:
        raise ValueError('invalid cached transcript')
    if (not isinstance(record['model'], str) or not isinstance(record['digest'], str)
            or not re.fullmatch('[0-9a-f]{64}', record['digest'])
            or type(record['count']) is not int or record['count'] < 1
            or not isinstance(record['ids'], list) or not record['ids']
            or any(not isinstance(x, str) or not x for x in record['ids'])
            or len(set(record['ids'])) != len(record['ids'])
            or type(record['end']) is not int or not 0 <= record['end'] <= 0xffffffff
            or not isinstance(record['held'], list) or not record['held']
            or any(type(x) is not int or not 0 <= x <= 0xffffffff for x in record['held'])
            or type(record['terminal']) is not bool):
        raise ValueError('invalid cached token history')
    payload = {k:v for k,v in value.items() if k != 'checksum'}
    if value['checksum'] != hashlib.sha256(_json(payload).encode()).hexdigest():
        raise ValueError('tool history checksum mismatch')
    return {'owner': tuple(owner), 'record': record}


def load_cache(root, owner):
    path = root / 'state/tool-history'
    if not path.exists() and not path.is_symlink():
        return None
    def read(fd):
        return privatejson.read(fd, _filename(owner), _validate_cache, _fields, None)
    with privatejson.registry(path, read) as (_, cached):
        return cached if cached and cached['owner'] == owner else None


def store_cache(root, owner, record, still_owned):
    path = root / 'state/tool-history'
    if record is None and not path.exists() and not path.is_symlink():
        return
    def read(fd):
        return privatejson.read(fd, _filename(owner), _validate_cache, _fields, None)
    with privatejson.registry(path, read) as (fd, previous):
        if not still_owned():
            return
        if record is None:
            if previous and previous['owner'] == owner:
                os.unlink(_filename(owner), dir_fd=fd); os.fsync(fd)
            return
        payload = {'format': 1, 'owner': owner, 'record': record}
        envelope = {**payload, 'checksum': hashlib.sha256(_json(payload).encode()).hexdigest()}
        privatejson.write(fd, _filename(owner), envelope, _validate_cache)


def discard_cache(root, owner, expected):
    """Discard only the candidate belonging to a failed response, not a newer one."""
    path = root / 'state/tool-history'
    if not path.exists() and not path.is_symlink():
        return
    def read(fd):
        return privatejson.read(fd, _filename(owner), _validate_cache, _fields, None)
    with privatejson.registry(path, read) as (fd, cached):
        if cached and cached['owner'] == owner and cached['record'] == expected:
            os.unlink(_filename(owner), dir_fd=fd); os.fsync(fd)


def prune_cache(root, owner_of):
    """Remove only valid, private cache records no longer owned by a live run."""
    path = root / 'state/tool-history'
    if not path.exists() and not path.is_symlink():
        return
    with privatejson.registry(path, lambda _: None) as (fd, _):
        for filename in os.listdir(fd):
            if not filename.endswith('.json'):
                continue
            try:
                cached = privatejson.read(fd, filename, _validate_cache, _fields, None)
            except (OSError, ValueError):
                continue  # foreign/corrupt files are not ours to delete
            if (cached and filename == _filename(cached['owner'])
                    and owner_of(cached['owner']) != cached['owner']):
                os.unlink(filename, dir_fd=fd)
        os.fsync(fd)


def _fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate tool argument')
        result[key] = value
    return result


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def _assistant(message):
    if set(message) - {'role', 'content', 'reasoning_content', 'tool_calls'} or message.get('role') != 'assistant':
        raise ValueError('unsupported assistant fields')
    if any(message.get(k) is not None and not isinstance(message[k], str)
           for k in ('content', 'reasoning_content')):
        raise ValueError('assistant text required')
    result = {**message, 'content': message.get('content') or '',
              'reasoning_content': message.get('reasoning_content') or '', 'tool_calls': []}
    if not isinstance(result['content'], str) or not isinstance(result['reasoning_content'], str):
        raise ValueError('assistant text required')
    for call in message.get('tool_calls') or []:
        if set(call) != {'id', 'type', 'function'} or call['type'] != 'function':
            raise ValueError('unsupported tool call')
        function = call['function']
        if set(function) != {'name', 'arguments'}:
            raise ValueError('unsupported function fields')
        arguments = json.loads(function['arguments'], object_pairs_hook=_fields)
        result['tool_calls'].append({**call, 'function': {**function, 'arguments': _json(arguments)}})
    return result


def _digest(conversation):
    messages = [_assistant(m) if m.get('role') == 'assistant' else m for m in conversation['messages']]
    return hashlib.sha256(_json({**conversation, 'messages': messages}).encode()).hexdigest()


def _model(config, model):
    return _json(config['models'][model])


def _complete_markup(text, count):
    """Reject ambiguous/partial syntax rather than preserving parser-discarded bytes."""
    _, found, markup = text.partition('<tool_call>')
    if not found:
        return False
    markup = found + markup
    calls = list(re.finditer(r'<tool_call>\s*<function=([^>\n]+)>\n(.*?)</function>\s*</tool_call>', markup, re.S))
    end = 0
    for call in calls:
        if markup[end:call.start()].strip():
            return False
        body, names, position = call[2], set(), 0
        for parameter in re.finditer(r'<parameter=([^>\n]+)>\n(.*?)\n</parameter>', body, re.S):
            if body[position:parameter.start()].strip() or parameter[1] in names:
                return False
            if any(marker in parameter[2] for marker in ('<tool_call>', '</tool_call>', '<function=',
                                                         '</function>', '<parameter=', '</parameter>')):
                return False
            names.add(parameter[1]); position = parameter.end()
        if body[position:].strip():
            return False
        end = call.end()
    return len(calls) == count and not markup[end:].strip()


def capture(config, model, conversation, prompt, generated, parsed, delivered):
    """Capture only a complete native call with unchanged public calls and framing."""
    if config['models'][model].get('backend') != 'gufo' or not parsed.get('tool_calls') or not generated:
        return None
    try:
        assistant = _assistant({'role': 'assistant', 'content': delivered['content'],
                                'reasoning_content': delivered['reasoning'], 'tool_calls': delivered['tool_calls']})
        if _json(assistant['tool_calls']) != _json(_assistant({'role': 'assistant',
                'tool_calls': parsed['tool_calls']})['tool_calls']):
            return None  # injected pre-stop controls are not native generated history
        ids = [c['id'] for c in assistant['tool_calls']]
        names = {t['function']['name'] for t in conversation.get('tools') or []}
        if len(ids) != len(set(ids)) or any(c['function']['name'] not in names for c in assistant['tool_calls']):
            return None
        markers = [gufo._call(config, model, 'tokenize', text=s)['tokens']
                   for s in ('<|im_end|>', '<|im_start|>', '<|endoftext|>')]
        if any(len(m) != 1 for m in markers):
            return None
        end, start, other = (m[0] for m in markers)
        if start in generated or other in generated or end in generated[:-1]:
            return None
        text = gufo.text(config, model, generated).removesuffix('<|im_end|>')
        if '\ufffd' in text or not _complete_markup(text, len(ids)):
            return None
        closed_conversation = {**conversation, 'messages': [*conversation['messages'], assistant]}
        return {'model': _model(config, model), 'digest': _digest(closed_conversation),
                'count': len(closed_conversation['messages']), 'ids': ids,
                'end': end, 'held': list(prompt) + list(generated),
                'terminal': generated[-1] == end}
    except (KeyError, TypeError, ValueError):
        return None


def extend(config, model, record, conversation, rendered):
    """Use native suffix tokens only for the exact delivered tool-cycle prefix."""
    try:
        if not record or record['model'] != _model(config, model):
            return rendered
        n = record['count']; messages = conversation['messages']
        prefix = {**conversation, 'messages': messages[:n]}
        results = messages[n:]
        if _digest(prefix) != record['digest'] or not results:
            return rendered
        k = len(record['ids'])
        if (len(results) < k or any(r.get('role') != 'tool' for r in results[:k])
                or sorted(r.get('tool_call_id', '') for r in results[:k]) != sorted(record['ids'])):
            return rendered
        # Interrupted assistants and incoming text messages can follow a completed
        # tool cycle. Retain only the digest-verified older history; render the
        # entire suffix natively. The closing-prefix check below also rejects
        # templates that rewrite earlier history when a new user turn arrives.
        for message in results[k:]:
            if message.get('role') == 'user':
                if set(message) != {'role', 'content'} or not isinstance(message['content'], str):
                    return rendered
            elif _assistant(message)['tool_calls']:
                return rendered
        if rendered['tokens'][:len(record['held'])] == record['held']:
            return rendered  # the native template already preserves this cycle
        closed = gufo.render(config, model, prefix)['tokens']
        cut = max(i+1 for i,t in enumerate(closed) if t == record['end'])
        if rendered['tokens'][:cut] != closed[:cut]:
            return rendered
        suffix = rendered['tokens'][cut if record['terminal'] else cut-1:]
        tokens = record['held'] + suffix
        shape = config['models'][model]
        if len(tokens) > shape['ctx_size'] // shape['lanes']:
            return rendered
        return {**rendered, 'tokens': tokens}
    except (KeyError, TypeError, ValueError):
        return rendered
