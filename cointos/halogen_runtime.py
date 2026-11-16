"""Own the pinned Halogen container and its small native-control frontend extension."""
import json
import subprocess
import time
import urllib.request
from pathlib import Path


def start(config, model):
    options = config['models'][model]['halogen']
    exists = subprocess.run(['podman', 'container', 'exists', options['container']]).returncode == 0
    if exists:
        previous = json.loads(subprocess.check_output(['podman', 'inspect', options['container']]))[0]
        wanted = json.loads(subprocess.check_output(['podman', 'image', 'inspect', options['image']]))[0]['Id']
        if previous['Image'] != wanted or previous['State']['Running']:
            raise RuntimeError('Halogen container exists but cannot be safely adopted')
        subprocess.run(['podman', 'rm', options['container']], check=True, stdout=subprocess.DEVNULL)
    root = Path(options['state']).expanduser()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    frontend = root / 'serve_api.py'
    original = subprocess.check_output(['podman', 'run', '--rm', '--entrypoint', 'cat',
                                       options['image'], '/halogen/tools/serve_api.py']).decode()
    needle = '    app.state.raw_tokens = raw_tokens\n'
    if original.count(needle) != 1:
        raise RuntimeError('Pinned Halogen frontend extension point changed')
    frontend.write_text(original.replace(needle,
        needle + '    from control import install\n    install(app, tok, engine)\n'))
    command = ['podman', 'run', '-d', '--name', options['container'],
        '--device', '/dev/kfd', '--device', '/dev/dri', '--group-add', 'keep-groups',
        '--ipc=host', '--ulimit', 'memlock=-1:-1',
        '-p', '127.0.0.1:8731:8731',
        '-v', str(Path(options['weights']).expanduser()) + ':/models:ro',
        '-v', str(frontend) + ':/halogen/tools/serve_api.py:ro',
        '-v', str(Path(__file__).with_name('halogen_control.py')) + ':/halogen/tools/control.py:ro']
    for key, value in {'HALOGEN_CTX': config['models'][model]['ctx_size'],
            'HALOGEN_KV_POOL_POSITIONS': 2 * config['models'][model]['ctx_size'],
            'HALOGEN_KV_SLOTS': 1, 'HALOGEN_MAX_TOK': 8192,
            'HALOGEN_PROMPT_CACHE': 2, 'HALOGEN_ENABLE_THINKING': 0,
            'HF_HUB_OFFLINE': 1}.items():
        command += ['-e', f'{key}={value}']
    command.append(options['image'])
    subprocess.run(['systemd-run', '--user', '--scope', '--quiet', '--collect',
                    '--unit=' + options['container'] + '-runtime', *command],
                   check=True, stdout=subprocess.DEVNULL)
    deadline = time.monotonic() + config['timeouts']['model_launch_seconds']
    while time.monotonic() < deadline:
        try:
            req = urllib.request.Request(options['url'] + '/cointos/control',
                json.dumps({'op': 'info'}).encode(), {'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=2) as response:
                if 'result' in json.load(response):
                    return
        except OSError:
            time.sleep(1)
    raise TimeoutError('Halogen native control did not become ready')
