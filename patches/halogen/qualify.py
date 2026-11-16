#!/usr/bin/env python3
"""Opt-in synthetic native qualification against an already-running Halogen bridge."""
import argparse
import json
import sys
import urllib.request
import urllib.error
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from cointos import backend_halogen as backend

p = argparse.ArgumentParser()
p.add_argument('--config', required=True)
p.add_argument('--output', required=True)
a = p.parse_args()
c = json.loads(Path(a.config).read_text())
# Direct native lane selection bypasses CointOS scheduling. Never run these
# fixtures beside the live daemon; use a gateway fixture for production probes.
try:
    with urllib.request.urlopen(f"http://127.0.0.1:{c['port']}/api/ledger", timeout=2):
        pass
except urllib.error.URLError as error:
    if not isinstance(error.reason, ConnectionRefusedError):
        raise RuntimeError('Cannot establish that the CointOS gateway is stopped') from error
else:
    raise RuntimeError('Stop the CointOS daemon before direct native qualification; the engine may remain running')
model = 'halogen-qualification'
c['models'][model] = {'backend': 'halogen', 'ctx_size': 131072, 'lanes': 1,
                     'halogen': {'url': 'http://127.0.0.1:8731'}}
owners = ['synthetic/halogen-full', 'synthetic/halogen-step', 'synthetic/halogen-other', 'synthetic/halogen-tool']
result = {}

def render(text, tools=None):
    return backend.render(c, model, {'messages': [{'role': 'user', 'content': text}],
                      'tools': tools, 'template': {'enable_thinking': False}})

def run(owner, rendered, count, sampling=None):
    held = backend.select(c, model, 0, owner)
    tokens = rendered['tokens']
    backend.prefill(c, model, 0, tokens, len(held) if tokens[:len(held)] == held else 0)
    return backend.think(c, model, 0, tokens, len(tokens), count,
                         sampling or {'temperature': 0}, lambda new: None)

try:
    prompt = render('Write a complete Python fair multi-tenant scheduler with typed jobs, retries, cancellation and tests. Output Python code only.')
    whole = run(owners[0], prompt, 256)
    stepped = []
    steps = []
    for i in range(4):
        current = {**prompt, 'tokens': prompt['tokens'] + stepped}
        event = run(owners[1], current, 64)
        stepped += event['tokens']
        steps.append(event['rate'])
        if i == 1:
            other = run(owners[2], render('Reply with the word READY.'), 16)
            assert backend.text(c, model, other['tokens']).startswith('READY')
    assert stepped == whole['tokens'], 'interleaved bounded output differs'
    result.update(interleaved_greedy_equal=True, tokens=len(stepped), step_rates=steps, full_rate=whole['rate'])
    tools = [{'type': 'function', 'function': {'name': 'record', 'description': 'Record the supplied values.',
        'parameters': {'type': 'object', 'properties': {'count': {'type': 'integer'}, 'enabled': {'type': 'boolean'}},
                       'required': ['count', 'enabled']}}}]
    rendered = render('Call record with count 7 and enabled true. Do not write anything else.', tools)
    event = run(owners[3], rendered, 128)
    parsed = backend.read(c, model, rendered['reader'], event['tokens'], True)
    call = parsed['tool_calls'][0]
    assert call['function']['name'] == 'record'
    assert json.loads(call['function']['arguments']) == {'count': 7, 'enabled': True}
    result['typed_tool'] = True
    followup = backend.render(c, model, {
        'messages': [
            {'role': 'user', 'content': 'Call record with count 7 and enabled true.'},
            {'role': 'assistant', 'content': '', 'tool_calls': [call]},
            {'role': 'tool', 'tool_call_id': call['id'], 'content': 'Recorded successfully.'},
            {'role': 'user', 'content': 'The tool succeeded. Reply with exactly ROUNDTRIP OK.'}],
        'tools': tools, 'template': {'enable_thinking': False}})
    continued = run(owners[3], followup, 64)
    assert 'ROUNDTRIP OK' in backend.text(c, model, continued['tokens'])
    result['tool_history_continuation'] = True
    # A cold/read-loss condition must refuse bounded generation instead of silently
    # spending an unbounded prefill in a generation step.
    backend.release_residents(c, model, [owners[1]])
    backend.select(c, model, 0, owners[1])
    try:
        backend.think(c, model, 0, prompt['tokens'], len(prompt['tokens']), 16, {'temperature': 0}, lambda new: None)
        raise AssertionError('lost retained state accepted')
    except backend.Lost:
        result['lost_state_refused'] = True
    Path(a.output).write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result), flush=True)
finally:
    backend.release_residents(c, model, owners)
