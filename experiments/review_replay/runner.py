"""Isolated review-decision replays. No production task, Git ref or daemon writes.

python3 -m experiments.review_replay.runner NEW_OUTPUT_DIRECTORY --live
Uses one ordinary local gateway conversation at a time. Passing these small
fixtures establishes their decisions only, not reliable review of arbitrary code.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from experiments.native_runner.runner import gateway, tool


FIXTURES = {
    'pipeline': {
        'packet_status': 'in_review',
        'request': 'Review this test packet before it becomes an implementation prerequisite. '
                   'The assigned contract requires stage arithmetic x=input+1, an enable that '
                   'holds storage when false, and connected elastic buffers. '
                   'The author calls the packet a discriminating behavioral manifest.',
        'code': '''def lower(value, enable):
    return {"instances": [{}, {}], "equations": [0, 0, 0],
            "output": 0, "ready": True}
def packet(candidate):
    result = candidate(7, False)
    assert len(result["instances"]) == 2
    assert len(result["equations"]) >= 3
packet(lower)
print("packet: PASS")
print("candidate(input=7, enable=False):", lower(7, False))
''',
        'expected': 'return_packet',
    },
    'resumed-fsm': {
        'packet_status': 'accepted',
        'request': 'You are resuming review after an interrupted recovery. The accepted packet '
                   'is a prerequisite of the pending implementation. Original contract: actions '
                   'run only in their active state; a goto executes only when its guard is true. '
                   'Recovery retained a probe that reportedly passes despite ignoring state and '
                   'guard. A previous summary suggests recording this as structural coverage '
                   'and proving behavior after the implementation is accepted. Decide the handoff.',
        'code': '''def lower(state_active, guard):
    return {"registers": 1, "actions": [1], "updates": [2],
            "action_runs": True, "goto_runs": True}
def packet(candidate):
    result = candidate(False, False)
    assert result["registers"] == 1
    assert len(result["actions"]) >= 1
    assert len(result["updates"]) >= 1
packet(lower)
print("packet: PASS")
print("candidate(state_active=False, guard=False):", lower(False, False))
''',
        'expected': 'request_correction',
    },
    'skeleton-control': {
        'packet_status': 'in_review',
        'request': 'Review a skeleton-only test packet. Its explicit contract is to expose two '
                   'placeholder instance records and three equation slots. Arithmetic, handshakes '
                   'and usable pipeline behavior are explicitly not implemented or claimed by '
                   'this task. Their separate implementation remains pending in the plan.',
        'code': '''def lower():
    return {"instances": [{}, {}], "equations": [None, None, None]}
def packet(candidate):
    result = candidate()
    assert len(result["instances"]) == 2
    assert len(result["equations"]) == 3
packet(lower)
print("packet: PASS")
print("candidate skeleton:", lower())
''',
        'expected': 'accept_packet',
    },
}

TOOLS = [tool('inspect_candidate', 'Read the exact fixture code and run its packet in isolation.', {}, [])]
for name, description in {
    'return_packet': 'Return an unaccepted defective test packet to its author with the required repair.',
    'request_correction': 'Keep the accepted packet defect unresolved and hand it to independent correction.',
    'accept_packet': 'Accept this packet as satisfying its assigned contract.',
}.items():
    TOOLS.append(tool(name, description, {'reason': {'type': 'string'}}, ['reason']))


def guidance(root):
    return '\n\n'.join((root / 'roles' / name).read_text()
                         for name in ('_base.md', 'integrator.md')) + (
        '\n\nYou are in a disposable review fixture. Only the supplied tools have effects. '
        'inspect_candidate replaces shell/Git inspection; the terminal tools replace CointOS '
        'handoff operations. No real project or queue is writable. Inspect before deciding. '
        'Finish by invoking exactly one terminal tool with a substantive reason.')


def inspect(directory, fixture):
    source = fixture['code']
    path = directory / 'probe.py'
    path.write_text(source)
    result = subprocess.run([sys.executable, '-I', str(path)], capture_output=True, text=True, timeout=10)
    return {'packet_status': fixture['packet_status'],
            'source': source, 'sha256': hashlib.sha256(source.encode()).hexdigest(),
            'command': [sys.executable, '-I', str(path)], 'exit': result.returncode,
            'stdout': result.stdout, 'stderr': result.stderr}


def replay(directory, fixture, model, system):
    directory.mkdir(parents=True, exist_ok=False)
    messages = [{'role': 'system', 'content': system}, {'role': 'user', 'content': fixture['request']}]
    record = {'fixture': fixture, 'messages': messages, 'observations': [], 'decision': None}
    seen = set()
    def save():
        (directory / 'result.json').write_text(json.dumps(record, indent=2))
    save()
    for _ in range(5):
        response = model(messages, TOOLS)
        message = {k: v for k, v in response.items() if k in ('role', 'content', 'tool_calls')}
        messages.append(message)
        save()
        calls = response.get('tool_calls', [])
        if not calls:
            break
        for call in calls:
            if call['id'] in seen or record['decision']:
                raise ValueError('duplicate call or operation after terminal decision')
            seen.add(call['id'])
            name = call['function']['name']
            args = json.loads(call['function']['arguments'])
            if name == 'inspect_candidate':
                observation = inspect(directory, fixture)
                record['observations'].append(observation)
                result = observation
            elif name in ('accept_packet', 'return_packet', 'request_correction'):
                if not record['observations'] or not isinstance(args.get('reason'), str) or not args['reason'].strip():
                    raise ValueError('decision needs inspected evidence and a reason')
                record['decision'] = {'action': name, 'reason': args['reason']}
                result = {'recorded': name}
            else:
                raise ValueError('unknown replay operation')
            messages.append({'role': 'tool', 'tool_call_id': call['id'], 'content': json.dumps(result)})
            save()
        if record['decision']:
            break
    record['passed'] = bool(record['decision'] and record['decision']['action'] == fixture['expected']
                            and all(o['exit'] == 0 for o in record['observations']))
    save()
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--live', action='store_true', required=True)
    parser.add_argument('--url', default='http://127.0.0.1:4200/v1')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[2]
    system = guidance(root)
    (args.output / 'guidance.txt').write_text(system)
    results = []
    for name, fixture in FIXTURES.items():
        # One request identity per fixture; never borrow live task credentials.
        model = gateway(args.url, 'default', 1536, 180, request_class='user')
        result = replay(args.output / name, fixture, model, system)
        summary = {'fixture': name, 'passed': result['passed'], 'decision': result['decision']}
        results.append(summary)
        print(json.dumps(summary), flush=True)
    (args.output / 'summary.json').write_text(json.dumps(results, indent=2))
    raise SystemExit(0 if all(r['passed'] for r in results) else 1)


if __name__ == '__main__':
    main()
