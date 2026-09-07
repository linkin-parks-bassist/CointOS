"""Reusable terminal monitors, separate from admitted agent lifetimes."""
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import uuid


def identity(pid):
    try:
        fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        if fields[0] == 'Z':
            return None
        return {'pid': pid, 'start': fields[19],
                'boot': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
    except (OSError, IndexError):
        return None


def alive(value):
    return isinstance(value, dict) and identity(value['pid']) == value


def change(root, operation):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    with (root/'registry.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = root/'registry.json'
        slots = json.loads(path.read_text()) if path.exists() else {}
        result = operation(slots)
        fd, temporary = tempfile.mkstemp(dir=root, prefix='.registry-')
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(slots, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return result


def reserve(root, assignment):
    def update(slots):
        for slot in slots.values():
            if slot['state'] == 'closed':
                continue
            if slot['monitor'] is None:
                if time.time() - slot['created_at'] > 30:
                    slot['state'] = 'closed'
            elif not alive(slot['monitor']):
                slot['state'] = 'closed'
            elif slot['state'] == 'busy' and not alive(slot['assignment']['server']):
                slot['state'] = 'idle'
        for key, slot in slots.items():
            if (slot['state'] in ('starting', 'busy')
                    and slot['assignment']['view_record'] == assignment['view_record']):
                return key, False
        for key, slot in slots.items():
            if slot['state'] == 'idle':
                slot.update(state='busy', assignment=assignment)
                return key, False
        key = uuid.uuid4().hex
        slots[key] = {'state': 'starting', 'monitor': None, 'assignment': assignment,
                      'created_at': time.time()}
        return key, True
    return change(root, update)


def register(root, key):
    def update(slots):
        slot = slots[key]
        if slot['state'] != 'starting':
            return False
        slot.update(state='busy', monitor=identity(os.getpid()))
        return True
    return change(root, update)


def current(root, key):
    path = Path(root)/'registry.json'
    slot = json.loads(path.read_text())[key]
    return slot['assignment'] if slot['state'] == 'busy' else None


def finish(root, key, view_record):
    def update(slots):
        slot = slots[key]
        if slot['state'] == 'busy' and slot['assignment']['view_record'] == view_record:
            slot['state'] = 'idle'
    change(root, update)


def retire(root, key):
    change(root, lambda slots: slots[key].update(state='closed'))


def show(root, assignment, mode, env):
    if mode == 'afk':
        return None
    if mode != 'driver':
        raise ValueError('COINTOS_VIEW_MODE must be driver or afk')
    if not (env.get('DISPLAY') or env.get('WAYLAND_DISPLAY')):
        raise RuntimeError('driver mode requires a graphical monitor')
    key, create = reserve(root, assignment)
    if create:
        try:
            # GNOME owns the window; this process only starts its dedicated monitor.
            result = subprocess.run(
                ['gnome-terminal', '--window', '--role', 'cointos-monitor-'+key,
                 '--title', 'CointOS agent monitor', '--', sys.executable,
                 str(Path(__file__).resolve()), str(Path(root).resolve()), key],
                env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, close_fds=True, start_new_session=True,
                timeout=5)
            if result.returncode:
                raise RuntimeError('GNOME Terminal did not open the monitor')
        except (OSError, subprocess.TimeoutExpired, RuntimeError):
            retire(root, key)
            raise
    return key


def stop_viewer(viewer):
    if viewer is not None and viewer.poll() is None:
        viewer.terminate()
        try:
            viewer.wait(timeout=3)
        except subprocess.TimeoutExpired:
            viewer.kill()
            viewer.wait(timeout=3)


def monitor(root, key):
    if not register(root, key):
        return
    viewer = None
    def interrupted(_signum, _frame):
        raise SystemExit(0)
    for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(sig, interrupted)
    try:
        print('CointOS monitor — waiting for work. Close this window to retire it.', flush=True)
        while True:
            task = current(root, key)
            if task is None:
                time.sleep(0.5)
                continue
            if alive(task['server']):
                print('Watching: '+task['title'], flush=True)
                viewer = subprocess.Popen([task['opencode'], 'attach', task['url'], '--pure',
                    '--dir', task['directory'], '--session', task['session_id']])
                while alive(task['server']):
                    if viewer.poll() is not None:
                        # A user quitting the TUI while work lives retires the slot;
                        # do not silently reassign a still-active agent's window.
                        return
                    time.sleep(0.5)
                stop_viewer(viewer)
                viewer = None
            print('\nRun ended: '+task['title']+'\nView record: '+task['view_record']+
                  '\nMonitor idle; waiting for the next agent.', flush=True)
            finish(root, key, task['view_record'])
    finally:
        stop_viewer(viewer)
        retire(root, key)


if __name__ == '__main__':
    monitor(Path(sys.argv[1]), sys.argv[2])
