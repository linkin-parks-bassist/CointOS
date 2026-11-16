"""OpenCode 2 protocol boundary. Session history remains owned by OpenCode.

Private servers, explicit locations, native inbox controls and durable events are
used instead of V1 message mutation or a shared desktop service.
"""
from __future__ import annotations

import json
import base64
from contextvars import ContextVar
import urllib.parse
import urllib.request

AUTH = ContextVar('opencode2_password', default=None)


def headers():
    result = {'Content-Type': 'application/json'}
    if AUTH.get():
        result['Authorization'] = 'Basic ' + base64.b64encode(('opencode:' + AUTH.get()).encode()).decode()
    return result


def request(url, path, body=None, *, timeout=None):
    req = urllib.request.Request(url + '/api/' + path,
                                 None if body is None else json.dumps(body).encode(),
                                 headers())
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read()
    return json.loads(raw) if raw else None


def path(session, action=''):
    return 'session/' + urllib.parse.quote(session, safe='') + ('/' + action if action else '')


def messages(url, session):
    """Export returns the complete chronological projection, without page truncation."""
    return request(url, 'experimental/' + path(session, 'export'))['data']['messages']


def unfinished(history):
    """Distinguish unfinished work from a new review/reorientation turn."""
    user = next((i for i in range(len(history) - 1, -1, -1)
                 if history[i]['type'] == 'user'), None)
    if user is None:
        return False
    tail = history[user + 1:]
    if any(m['type'] == 'compaction' for m in tail):
        return False
    assistants = [m for m in tail if m['type'] == 'assistant']
    if not assistants:
        return True
    last = assistants[-1]
    return (last.get('finish') in (None, 'tool-calls', 'unknown')
            or last.get('error', {}).get('type') == 'aborted')


def finish_compaction(url, session):
    history = messages(url, session)
    at = next((i for i in range(len(history) - 1, -1, -1)
               if history[i]['type'] == 'compaction'), None)
    if (at is None or history[at].get('status') == 'completed'
            or any(m['type'] == 'user' for m in history[at + 1:])):
        return False
    request(url, path(session, 'compact'), {})
    request(url, 'experimental/' + path(session, 'wait'), {})
    latest = next((m for m in reversed(messages(url, session)) if m['type'] == 'compaction'), None)
    if not latest or latest.get('status') != 'completed':
        raise RuntimeError('OpenCode 2 compaction did not complete; recovery input withheld')
    return True


def event(value, tools=None):
    """Project native V2 notifications into the daemon's execution-fact format."""
    kind, data = value.get('type'), value.get('data', {})
    session = data.get('sessionID')
    if not session:
        return None
    part = {'id': value['id'], 'sessionID': session,
            'messageID': data.get('assistantMessageID')}
    typ = None
    tools = {} if tools is None else tools
    if kind == 'session.tool.input.started':
        tools[data['id']] = {'tool': data['name']}
    if kind == 'session.step.started':
        typ, part['type'] = 'step_start', 'step-start'
    elif kind == 'session.step.ended':
        typ, part['type'] = 'step_finish', 'step-finish'
        part.update(reason=data['finish'], cost=data.get('cost', 0), tokens=data.get('tokens', {}))
    elif kind in ('session.text.ended', 'session.reasoning.ended'):
        typ = part['type'] = 'reasoning' if 'reasoning' in kind else 'text'
        part['text'] = data['text']
    elif kind in ('session.tool.called', 'session.tool.success', 'session.tool.failed'):
        typ = part['type'] = 'tool'
        prior = tools.setdefault(data['id'], {})
        if 'input' in data:
            prior['input'] = data['input']
        part.update(tool=prior.get('tool'), callID=data['id'])
        part['state'] = {'status': {'session.tool.called': 'running', 'session.tool.success': 'completed',
                                    'session.tool.failed': 'error'}[kind],
                         'input': prior.get('input', {}),
                         'output': '\n'.join(c.get('text', '') for c in data.get('content', [])),
                         'error': data.get('error')}
    elif kind in ('session.execution.failed', 'session.step.failed'):
        return {'type': 'error', 'sessionID': session, 'error': data.get('error', data)}
    if typ:
        return {'type': typ, 'sessionID': session, 'timestamp': value.get('created'), 'part': part}
    return None


def resume(url, session, output):
    """Wake an interrupted native loop without creating another user message.

    Re-admitting an already delivered user ID is idempotent but does not resume
    model work in 2.2.6. A native synthetic control records recovery explicitly.
    Subscribe first so a fast local response cannot outrun the observer.
    """
    tools = {}
    with urllib.request.urlopen(urllib.request.Request(url + '/api/event', headers=headers()), timeout=None) as stream:
        # Receiving the connection event establishes the subscription before admission.
        for line in stream:
            if line.startswith(b'data:'):
                break
        request(url, path(session, 'synthetic'), {
            'text': 'Continue the interrupted turn.', 'description': 'CointOS recovery', 'resume': True})
        for line in stream:
            if not line.startswith(b'data:'):
                continue
            native = json.loads(line[5:])
            if native.get('data', {}).get('sessionID') != session:
                continue
            projected = event(native, tools)
            if projected:
                output.write((json.dumps(projected) + '\n').encode())
                output.flush()
            if native['type'] == 'session.execution.succeeded':
                return 0
            if native['type'] in ('session.execution.failed', 'session.execution.interrupted'):
                return 1
    raise RuntimeError('OpenCode 2 event stream ended before execution became terminal')
