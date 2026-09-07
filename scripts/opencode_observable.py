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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--view-record', required=True, type=Path)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
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
    try:
        server, url = start_server(command[0], directory, dict(os.environ),
                                  args.view_record.with_suffix('.server.log'))
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
        client = subprocess.Popen(command+['--attach', url], cwd=directory, env=client_env)
        if client_env.get('DISPLAY') or client_env.get('WAYLAND_DISPLAY'):
            try:
                subprocess.Popen(
                    ['gnome-terminal', '--window', '--title', title, '--',
                     command[0], 'attach', url, '--pure', '--dir', str(directory),
                     '--session', session], env=client_env,
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, close_fds=True, start_new_session=True)
            except OSError:
                print(json.dumps({'type': 'worker_view_window_unavailable',
                                  'attach_command': record['attach_command']}),
                      file=sys.stderr, flush=True)
        return client.wait()
    finally:
        if client is not None:
            stop_child(client)
        if server is not None:
            stop_child(server)


if __name__ == '__main__':
    sys.exit(main())
