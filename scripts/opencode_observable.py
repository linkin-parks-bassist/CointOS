"""One admitted OpenCode process group, with a loopback TUI attachment endpoint.

This supervisor belongs AFTER the existing admission gate. It grants no inference
authority itself. The server inherits the gated anonymous config descriptor; the
attached CLI and viewer do not need that descriptor. JSONL still goes to stdout.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from worker_monitors import identity, show


def stop_child(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def start_server(binary, directory, env, log_path):
    config = env.get('OPENCODE_CONFIG', '')
    match = re.fullmatch(r'/proc/self/fd/([0-9]+)', config)
    descriptors = (int(match[1]),) if match else ()
    if descriptors:
        os.fstat(descriptors[0])
    descriptor = os.open(log_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, 'wb') as log:
        process = subprocess.Popen(
            [binary, 'serve', '--pure', '--hostname', '127.0.0.1', '--port', '0',
             '--mdns=false'], cwd=directory, env=env, stdin=subprocess.DEVNULL,
            stdout=log, stderr=log, pass_fds=descriptors)
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError('OpenCode server exited during startup; see private server log')
            with open(log_path, 'rb') as log:
                content = log.read(65536).decode('utf-8', errors='replace')
            found = re.search(r'opencode server listening on (http://127\.0\.0\.1:[0-9]+)', content)
            if found:
                return process, found[1]
            time.sleep(0.1)
        raise RuntimeError('OpenCode loopback listener not observed within startup budget')
    except BaseException:
        stop_child(process)
        raise


def create_session(url, directory, title):
    query = urllib.parse.urlencode({'directory': str(directory)})
    request = urllib.request.Request(url+'/session?'+query,
        data=json.dumps({'title': title}).encode(), headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=10) as response:
        value = json.load(response)
    identifier = value.get('id')
    if not isinstance(identifier, str) or not re.fullmatch(r'ses_[A-Za-z0-9]+', identifier):
        raise ValueError('invalid OpenCode session identity')
    return identifier


def publish_view(path, url, directory, session, pid):
    record = {'url': url, 'directory': str(directory), 'session_id': session,
              'server_pid': pid,
              'attach_command': shlex.join(['opencode', 'attach', url, '--pure',
                                           '--dir', str(directory), '--session', session])}
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        json.dump(record, stream)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    return record


def finish_client(process):
    """Mirror client output and classify semantic failure and truncation."""
    saw_error = False
    finish_reason = None
    for raw_line in iter(process.stdout.readline, b''):
        sys.stdout.buffer.write(raw_line)
        sys.stdout.buffer.flush()
        try:
            event = json.loads(raw_line.decode('utf-8', errors='replace'))
        except ValueError:
            continue
        if isinstance(event, dict) and event.get('type') == 'error':
            saw_error = True
        part = event.get('part') if isinstance(event, dict) else None
        if (isinstance(event, dict) and event.get('type') == 'step_finish'
                and isinstance(part, dict)):
            finish_reason = part.get('reason')
    process.stdout.close()
    code = process.wait()
    return {
        'returncode': 1 if code == 0 and saw_error else code,
        'length': finish_reason == 'length',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--view-record', required=True, type=Path)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    view_mode = os.environ.get('COINTOS_VIEW_MODE', 'driver')
    if view_mode not in ('driver', 'afk'):
        parser.error('COINTOS_VIEW_MODE must be driver or afk')
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if len(command) < 2 or command[1] != 'run' or '--attach' in command:
        parser.error('expected an unattached opencode run command after --')
    if '--dir' not in command or '--title' not in command:
        parser.error('run must specify --dir and --title')
    directory = Path(command[command.index('--dir')+1]).resolve(strict=True)
    title = command[command.index('--title')+1]
    if args.view_record.exists():
        parser.error('view record exists; inspect the original run, do not overwrite')
    def interrupted(signum, _frame):
        raise SystemExit(128+signum)
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, interrupted)
    server = client = None
    capacity_fd = None
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from ecosystem.opencode_launch import prepare_environment, verify_server_capacity
        server_env, capacity_fd, capacity = prepare_environment(
            command, os.environ, Path(__file__).resolve().parents[1])
        server, url = start_server(command[0], directory, server_env,
                                  args.view_record.with_suffix('.server.log'))
        expected_base = None
        if capacity is not None:
            payload = json.loads(os.pread(capacity_fd, os.fstat(capacity_fd).st_size, 0))
            expected_base = payload['provider']['Lemonade']['options']['baseURL']
            verify_server_capacity(url, directory, capacity,
                                   expected_base,
                                   binary=command[0], root=Path(__file__).resolve().parents[1])
            print(json.dumps({'type': 'worker_capacity_verified',
                              'model': capacity['model_id'],
                              'context_tokens': capacity['opencode_context_tokens'],
                              'output_tokens': capacity['opencode_output_tokens'],
                              'opencode_version': capacity['opencode_version']}),
                  file=sys.stderr, flush=True)
        if '--session' in command:
            session = command[command.index('--session')+1]
        else:
            session = create_session(url, directory, title)
            command.extend(['--session', session])
        record = publish_view(args.view_record, url, directory, session, server.pid)
        print(json.dumps({'type': 'worker_view_ready', **record}), file=sys.stderr, flush=True)
        client_env = dict(os.environ)
        client_env.pop('OPENCODE_CONFIG', None)
        client_env.pop('OPENCODE_CONFIG_CONTENT', None)
        client_command = list(command)
        prompt = command[2] if len(command) > 2 and not command[2].startswith('-') else None
        if prompt is not None:
            del client_command[2]
        try:
            runtime_root = Path(os.environ.get(
                'COINTOS_RUNTIME_ROOT', Path.home()/'.CointOS'))
            monitor_id = show(runtime_root/'state/worker-monitors',
                {**record, 'view_record': str(args.view_record.resolve()),
                 'server': identity(server.pid), 'opencode': command[0], 'title': title},
                view_mode, client_env)
            print(json.dumps({'type': 'worker_monitor', 'monitor_id': monitor_id,
                              'mode': view_mode}), file=sys.stderr, flush=True)
        except (OSError, RuntimeError, subprocess.TimeoutExpired):
            print(json.dumps({'type': 'worker_view_window_unavailable',
                              'attach_command': record['attach_command']}),
                  file=sys.stderr, flush=True)
        length_recoveries = 0
        while True:
            client = subprocess.Popen(client_command+['--attach', url], cwd=directory,
                                      env=client_env, stdin=subprocess.PIPE,
                                      stdout=subprocess.PIPE)
            client.stdin.write((prompt or '').encode())
            client.stdin.close()
            outcome = finish_client(client)
            client = None
            if not outcome['length']:
                return outcome['returncode']
            length_recoveries += 1
            print(json.dumps({
                'type': 'worker_length_recovery',
                'session_id': session,
                'attempt': length_recoveries,
                'output_tokens': capacity.get('opencode_output_tokens')
                    if capacity is not None else None,
            }), file=sys.stderr, flush=True)
            if length_recoveries >= 3:
                print(json.dumps({
                    'type': 'worker_emergency',
                    'reason': 'repeated_output_length',
                    'session_id': session,
                    'attempts': length_recoveries,
                }), file=sys.stderr, flush=True)
                return 75
            if capacity is not None:
                verify_server_capacity(
                    url, directory, capacity, expected_base,
                    binary=command[0], root=Path(__file__).resolve().parents[1])
            prompt = ('Continue the incomplete response in this exact retained session. '
                      'Complete the requested task; do not repeat finished work.')
    finally:
        if client is not None:
            stop_child(client)
        if server is not None:
            stop_child(server)
        if capacity_fd is not None:
            os.close(capacity_fd)


if __name__ == '__main__':
    sys.exit(main())
