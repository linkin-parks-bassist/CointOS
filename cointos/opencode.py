"""OpenCode: the fingertip where an agent run becomes processes and files, and back.

Each run is a transient systemd user unit `cointos-agent-<id>` running `python3 -m
cointos.opencode DIR` (`serve_run`): an OpenCode server and a `run` client in the task's
worktree, thinking only through the gateway. The unit writes `server.json`, `events.jsonl` and
`exit.json` into its directory; the daemon follows those files (`watch`) and so can outlive,
and be outlived by, the run. Nothing here decides what a run achieved: `watch` reports
execution facts only.
"""
from __future__ import annotations

import json
import contextlib
import hashlib
import os
import re
import signal
import secrets
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from cointos import git, kt, schema, stations
from cointos.config import ROOT, STATE, api_url, load as load_config, write_json

TIMEOUTS = load_config()["timeouts"]
OPENCODE = str(Path.home() / ".local/bin/opencode")
OPENCODE2 = str(Path.home() / '.local/lib/cointos/opencode2/node_modules/.bin/opencode')
LEGACY_OPENCODE = str(Path.home() / '.local/lib/cointos/opencode1/opencode')
OPENCODE2_VERSION = '2.2.6'
COMPACTION_CLI_SHA = "572e9e9f838c0a150558c8b412a50c3130acea0edd07288ab8da73b3b0a2380e"
PROVIDER = "cointos"
# Commands no agent may run; `control` ability lifts only the CointOS lifecycle ones.
DENIED_COMMANDS = ["sudo *", "su *", "systemctl *", "apt *", "apt-get *", "dpkg *", "snap *",
                   "pip install *", "pip3 install *", "npm install -g *", "git push*"]
LIFECYCLE_COMMANDS = ["cointos halt*", "cointos up*", "cointos stop*", "cointos restart*"]
LOOKING = ["systemctl status*", "systemctl --user status*", "systemctl cat*", "systemctl --user cat*",
           "systemctl is-active*", "systemctl --user is-active*", "systemctl list-units*",
           "systemctl --user list-units*", "systemctl show*", "systemctl --user show*", "dpkg -l*", "dpkg -s*",
           "cointos *--help*"]


def require_opencode2():
    # The V1 exporter is deliberately absent: David required the old binaries removed, so only
    # V2 assets are preflight-required. A recognised legacy store still refuses conversion.
    manifest = Path(OPENCODE2).parent.parent / '@opencode/cli/package.json'
    if (not Path(OPENCODE2).is_file()
            or not manifest.is_file() or json.loads(manifest.read_text()).get('version') != OPENCODE2_VERSION):
        raise ValueError('OpenCode 2 assets are missing or unpinned; run scripts/install-opencode2 before installation')


def run_dir(agent_id: str) -> Path:
    return STATE / "agents" / agent_id


def unit(agent_id: str) -> str:
    return f"cointos-agent-{agent_id}"


def confined_writes(task: dict) -> bool:
    """Branch-publishing roles preserve other checkouts, including maintenance.

    System Operators retain explicitly assigned infrastructure scope.
    """
    role = task.get('role')
    return observer(task) or stations.stationed(task) or (
        any(kind['role'] == role and kind['lands'] is not None for kind in schema.KINDS.values())
        and not (role == 'operator' and task.get('place') == 'system'))


def observer(task):
    """Branchless coordinators inspect through brokers; system Operators keep assigned scope."""
    return task.get('branch') is None and task.get('role') in ('supervisor', 'steward', 'test-auditor', 'first-responder')


def path_rules(rules: dict[str, str]) -> dict[str, str]:
    """OpenCode uses root-relative permission paths for directories without Git metadata."""
    return {name: action for pattern, action in rules.items()
            for name in ([pattern, pattern.lstrip('/')] if pattern.startswith('/') else [pattern])}


def settings(config: dict, key: str, task: dict, protected: list[str], agent_id: str = "") -> dict:
    """The run's OpenCode config: the gateway as its only provider, its station's tools,
    and narrow denials."""
    work = config["work_model"]
    shape = config["models"][work]
    home = str(Path.home())
    servers = stations.servers()
    granted = task.get("tools") or []
    abilities = set(task.get("abilities") or ["standard"])
    denied = DENIED_COMMANDS + ([] if "control" in abilities else LIFECYCLE_COMMANDS)
    if task.get('branch') or observer(task):
        denied += ['git *', 'hg *', 'svn *', 'fossil *']
    operator_control = task.get("role") == "operator" and "control" in abilities
    edit_scope = ({"*": "deny"} if task.get("role") == "first-responder"  # it dispatches; it doesn't do the work
                  else {"*": "deny", f"{Path(task['worktree']).resolve()}/**": "allow"}
                  if confined_writes(task) and task.get('worktree')
                  else {"*": "allow"})
    if agent_id and confined_writes(task) and task.get('role') != 'first-responder':
        edit_scope[f'{run_dir(agent_id).resolve()}/scratch/**'] = 'allow'
    read_scope = {}
    if confined_writes(task) and task.get('worktree'):
        project = next((p for p in config['projects'] if p['name'] == task.get('place')), None)
        if project and Path(project['path']).resolve() != Path(task['worktree']).resolve():
            origin = Path(project['path']).resolve()
            read_scope = {str(origin): 'deny', f'{origin}/**': 'deny'}
            for name in ('.knowledge', '.agents'):
                read_scope.update({str(origin / name): 'allow', f'{origin}/{name}/**': 'allow'})
    result = {
        "$schema": "https://opencode.ai/config.json",
        "model": f"{PROVIDER}/default",
        "provider": {PROVIDER: {
            "npm": "@ai-sdk/openai-compatible", "name": "CointOS gateway",
            # A request can wait for a lane and then prefill for minutes before its first byte;
            # the daemon's silence check, not a client timeout, decides when an agent is stuck.
            "options": {"baseURL": api_url(config) + "/v1", "apiKey": key,
                        "timeout": False, "headerTimeout": False, "chunkTimeout": False},
            "models": {"default": {"name": "CointOS default", "tool_call": True,
                              "limit": {"context": shape["ctx_size"] // shape["lanes"],
                                        "output": config["scheduler"]["max_thought_tokens"]}}},
        }},
        # Every agent gets the kt MCP server and CointOS's own tools. Other configured servers
        # are enabled only by its station.
        "mcp": {**{name: {**server, "enabled": name == 'knowledgetrees' or stations.grants(granted, name),
                          **({'environment': {**server.get('environment', {}), 'KT_MCP_PROJECT_DIR': str(ROOT)}}
                             if name == 'knowledgetrees' and observer(task) else {})}
                   for name, server in servers.items() if name != 'cointos'},
                "cointos": {"type": "local", "enabled": True, "command": [sys.executable, "-P", "-m", "cointos.mcp"],
                            "timeout": (config['timeouts']['validation_seconds'] + config['timeouts']['api_seconds'] * 2) * 1000,
                            "environment": {"PYTHONPATH": str(ROOT), "COINTOS_TASK_ID": task.get("id", ""),
                                            "COINTOS_AGENT": agent_id}}},
        "permission": {
            "*": "allow", "webfetch": "allow", "websearch": "allow", "doom_loop": "deny",
            "bash": {"*": "allow", **{command: "deny" for command in denied},
                     **({"*probe*": "deny"} if protected else {}),
                     **{command: "allow" for command in LOOKING},
                     **({"systemctl --user *": "allow"} if operator_control else {})},
            "external_directory": path_rules({"*": "deny", f"{home}/**": "allow", **read_scope}),
            "read": path_rules({"*": "allow", **read_scope, "*.env": "deny"}),
            "edit": path_rules({**edit_scope, **{path: "deny" for path in protected},
                     **({"*probe*": "deny"} if protected else {})}),  # implementers implement; finish runs the tests
        },
        "tools": {"task": False, "todowrite": False, "skill": False},
        "autoupdate": False, "share": "disabled",
        "compaction": config["compaction"],
        "plugin": [(ROOT / "cointos/opencode_resume.mjs").as_uri()],
    }
    if config.get('opencode_v2'):
        provider = result.pop('provider')[PROVIDER]
        model = provider['models']['default']
        model.pop('tool_call')  # Native chat providers expose tool capability directly.
        model['limit']['context'] = (
            shape['ctx_size'] // int(shape.get('slots') or shape['lanes']))
        result['providers'] = {PROVIDER: {
            'package': '@opencode/ai/providers/openai-compatible',
            'settings': provider['options'], 'models': provider['models'],
        }}
        result['plugin'] = [str(ROOT / 'cointos/opencode_plugin')]
        result['permission']['shell'] = result['permission'].pop('bash')
        result['permission'].update(subagent='deny', skill='deny', question='deny')
        result['tools'].update(subagent=False)
    return result



def write_paths(task: dict, directory: Path, store: Path | None = None) -> list[str] | None:
    """Branch-publishing runs can write their checkout and Git/tool state."""
    if not confined_writes(task):
        return None
    checkout = Path(task['worktree']).resolve()
    kt.prepare(checkout)
    if observer(task) or git.workspace_context(checkout):
        rewrites = STATE / 'knowledge-rewrites'
        rewrites.mkdir(parents=True, exist_ok=True, mode=0o700)
        data = store or agent_data(task)
        data.mkdir(parents=True, exist_ok=True, mode=0o700)
        catalog = data / 'models.json'
        if not catalog.exists():
            write_json(catalog, {})  # The configured CointOS provider is the whole managed catalog.
        return [str(p) for p in (checkout, directory.resolve(), rewrites, data, Path('/dev/null'))]
    # A station directory need not be a repository; a branch's checkout must be.
    found = subprocess.run(['git', '-C', str(checkout), 'rev-parse', '--path-format=absolute', '--git-common-dir'],
                           text=True, capture_output=True, check=task.get('branch') is not None)
    common = found.stdout.strip() if found.returncode == 0 else None
    rewrite_state = STATE / 'knowledge-rewrites'
    rewrite_state.mkdir(parents=True, exist_ok=True, mode=0o700)
    paths = [checkout, directory.resolve(), rewrite_state.resolve(),
             store or agent_data(task), Path('/tmp'), Path('/var/tmp'), Path('/dev/null')]
    if common:
        paths.append(Path(common))
    if common and task['role'] != 'worker':
        knowledge = Path(common).parent / '.knowledge'
        if knowledge.is_dir():
            paths.append(knowledge)
    for name in ('.cache/opencode', '.config/opencode', '.local/share/opencode', '.local/state/opencode'):
        path = Path.home() / name
        path.mkdir(parents=True, exist_ok=True)
        paths.append(path)
    return [str(path) for path in paths]


def agent_data(task, v2=None):
    base = STATE / 'agent-data' / hashlib.sha256(task['id'].encode()).hexdigest()
    return base / 'v2' if (load_config().get('opencode_v2') if v2 is None else v2) else base


def read_paths(task, directory, store=None):
    """Expose source and tools, excluding other workspaces, runtime authority and Git metadata."""
    if not observer(task) and (not task.get('branch') or not git.workspace_context(task['worktree'])):
        return None
    home = Path.home()
    roots = [Path(task['worktree']), directory, store or agent_data(task), STATE / 'knowledge-rewrites',
             home / '.knowledge/.tools',
             *[Path(p) for p in ('/usr', '/bin', '/sbin', '/lib', '/lib64', '/etc', '/proc', '/sys', '/dev')],
             *[ROOT / p for p in ('cointos', 'bin', 'config', 'roles', 'runtime')],
             *[home / p for p in ('.opencode/bin', '.local/bin', '.local/lib', '.local/libexec', '.cache/opencode')]]
    files = [str(Path('/etc/resolv.conf').resolve())] if Path('/etc/resolv.conf').exists() else []
    if observer(task):
        files.extend(str(path.resolve()) for path in
                     (home / '.knowledge/.tools/kt', home / '.knowledge/.tools/kt-mcp',
                      Path(os.environ.get('KT_CONFIG', str(home / '.knowledge/.tools/roots.json')))) if path.is_file())
    directories = [str(ROOT)]
    knowledge_roots = kt.readable_roots(ROOT) if observer(task) else [home / '.knowledge', ROOT / '.knowledge']
    for knowledge in (*knowledge_roots, home / '.agents/skills'):
        if not knowledge.is_dir():
            continue
        directories.append(str(knowledge))
        for parent, children, names in os.walk(knowledge):
            children[:] = [n for n in children if n != '.git' and not (Path(parent) / n).is_symlink()]
            files.extend(str(Path(parent) / n) for n in names if n != '.git' and not (Path(parent) / n).is_symlink())
    roots = [str(p.resolve()) for p in roots if p.exists()]
    return {'trees': roots, 'files': files, 'directories': directories}


def launch(config: dict, agent_id: str, task: dict, key: str, text: str, protected: list[str]) -> str | None:
    """Start a run as its own systemd unit, outside the daemon, so that it outlives a daemon
    replacement. `text` is the message the run starts with."""
    structured = config.get("structured_compaction", False)
    if not isinstance(structured, bool):
        raise ValueError("structured_compaction must be a boolean")
    v2 = config.get('opencode_v2', False)
    executable = OPENCODE2 if v2 else OPENCODE
    if v2 and structured:
        raise ValueError('the V1 structured-compaction binary cannot run a V2 session')
    if structured:
        candidate = ROOT / "bin" / "opencode-compaction"
        if hashlib.sha256(candidate.read_bytes()).hexdigest() != COMPACTION_CLI_SHA:
            raise ValueError("CointOS compaction CLI differs from the checked prototype")
        executable = str(candidate)
    directory = run_dir(agent_id)
    directory.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(directory / "opencode.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(settings(config, key, task, protected, agent_id), stream, indent=1)
    # Admission reserves a fresh run directory. Never reuse or clear a scratch path
    # left by another owner, including a symlink inside a damaged run directory.
    (directory / "scratch").mkdir(mode=0o700)
    if v2:
        descriptor = os.open(directory / 'server-password', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w') as stream:
            stream.write(secrets.token_urlsafe(32))
    command = [executable, "run", "--dir", task["worktree"], "--format", "json", "--auto",
               "--title", f"{task['role']}: {task['title']}", "--model", f"{PROVIDER}/default"]
    if v2:
        command[2:4] = []  # V2 binds its directory from the explicit process environment.
    if task.get("session"):
        command += ["--session", task["session"]]
    spec = {"task": {"id": task["id"], "worktree": task["worktree"], 'role': task['role']}, "command": command, "text": text,
            "structured_compaction": structured, 'protocol': 2 if v2 else 1,
            "session": task.get("session"), "model": {"providerID": PROVIDER, "modelID": "default"}}
    with (directory / "run.json").open("x") as stream:
        store = agent_data(task, v2)
        spec['write_paths'] = write_paths(task, directory, store)
        spec['read_paths'] = read_paths(task, directory, store)
        if spec['read_paths'] is not None or v2:
            spec['agent_data'] = str(store)
            Path(spec['agent_data']).mkdir(parents=True, exist_ok=True, mode=0o700)
            write_json(Path(spec['agent_data']) / 'models.json', {})
            from cointos import sessions
            if v2:
                sessions.prepare_v2(task, directory, store, executable, LEGACY_OPENCODE,
                                    TIMEOUTS['agent_start_seconds'])
            else:
                sessions.prepare(task, directory, store, executable, TIMEOUTS['agent_start_seconds'])
        stream.write(json.dumps(spec))
    for stale in ("server.json", "exit.json"):
        (directory / stale).unlink(missing_ok=True)
    subprocess.run(["systemd-run", "--user", "--quiet", "--collect", f"--unit={unit(agent_id)}",
                    f"--working-directory={ROOT}", f"--setenv=COINTOS_AGENT={agent_id}",
                    "--property=Before=cointosd.service",
                    "--property=KillMode=control-group", "--property=TimeoutStopSec=15",
                    # A runaway tool is killed inside its own agent, never by the machine's OOM
                    # handling, which would pick the model server. Only the tool dies (the largest
                    # process); the agent sees it killed and carries on.
                    f"--property=MemoryMax={config['memory']['agent_limit_gb']}G", "--property=MemorySwapMax=0",
                    "--property=OOMPolicy=continue",
                    sys.executable, "-m", "cointos.opencode", str(directory)], check=True)
    return spec.get('agent_data')


def environment(directory: Path, spec: dict) -> dict:
    """The run's processes know their run (COINTOS_AGENT, from the unit) and task, so the CLI
    can submit receipts and proposals as them."""
    return {**os.environ, "OPENCODE_CONFIG": str(directory / "opencode.json"),
            **({'PWD': spec['task']['worktree']} if spec['task'].get('worktree') else {}),
            'COINTOS_OPENCODE_V2': '1' if spec.get('protocol') == 2 else '0',
            **({'OPENCODE_PASSWORD': (directory / 'server-password').read_text()}
               if spec.get('protocol') == 2 else {}),
            "COINTOS_SCRATCH": str(directory / "scratch"),
            "TMPDIR": str(directory / "scratch"),
            "KT_REWRITE_STATE_DIR": str(STATE / "knowledge-rewrites"),
            "COINTOS_WRITE_PATHS": json.dumps(spec.get('write_paths')),
            "COINTOS_READ_PATHS": json.dumps(spec.get('read_paths')),
            **({name: str(Path(spec['agent_data']) / suffix) for name, suffix in
                (('XDG_DATA_HOME', 'data'), ('XDG_STATE_HOME', 'state'), ('XDG_CONFIG_HOME', 'config'),
                 ('XDG_CACHE_HOME', 'cache'))} if spec.get('agent_data') else {}),
            **({'OPENCODE_MODELS_PATH': str(Path(spec['agent_data']) / 'models.json'),
                'OPENCODE_DISABLE_MODELS_FETCH': '1'} if spec.get('agent_data') else {}),
            "COINTOS_OPENCODE_BINARY": spec.get("command", [OPENCODE])[0],
            "COINTOS_STRUCTURED_COMPACTION": "1" if spec.get("structured_compaction") else "0",
            "COINTOS_RESUME_PACKET": str(directory / "resume.json"),
            "COINTOS_COMPACTION_CONTEXT_COMMAND": json.dumps([
                sys.executable, "-P", "-m", "cointos.opencode", "--compaction-context",
                spec["task"]["id"], directory.name]),
            # Skills come from the one shared catalog. Claude Code's directory holds hard-linked
            # duplicates OpenCode would list from either place run to run, plus synced skills
            # that change on their own; either would break the system prefix tasks share.
            "OPENCODE_DISABLE_CLAUDE_CODE_SKILLS": "1",
            # Managed CLI sessions inspect files explicitly; watching whole worktrees is
            # unnecessary and can exhaust the user's shared inotify quota.
            "OPENCODE_EXPERIMENTAL_DISABLE_FILEWATCHER": "1",
            "COINTOS_TASK_ID": spec["task"]["id"],
            'COINTOS_ROLE': spec['task'].get('role', ''),
            'COINTOS_PROVIDER': PROVIDER,
            "PATH": f"{ROOT / 'bin'}:{Path.home() / '.local/bin'}:{os.environ.get('PATH', '')}"}


def start_server(directory: Path, worktree: str, env: dict) -> tuple[subprocess.Popen, str]:
    log_path = directory / "server.log"
    command = [env.get("COINTOS_OPENCODE_BINARY", OPENCODE), "serve", "--hostname", "127.0.0.1", "--port", "0", "--mdns=false"]
    if env.get('COINTOS_OPENCODE_V2') == '1':
        command.pop()
    paths = json.loads(env.get('COINTOS_WRITE_PATHS', 'null'))
    if paths is not None:
        command = [sys.executable, str(ROOT / 'cointos/worktree_guard.py'), json.dumps(paths), *command]
    with os.fdopen(os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600), 'ab') as log:
        server = subprocess.Popen(command,
                                  cwd=worktree, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                  process_group=0)
    deadline = time.monotonic() + TIMEOUTS["agent_start_seconds"]
    while time.monotonic() < deadline:
        if server.poll() is not None:
            raise RuntimeError(f"opencode serve exited with {server.returncode}")
        found = re.search(r"(?:opencode )?server listening on (http://127\.0\.0\.1:\d+)",
                          log_path.read_text(errors="replace"))
        if found:
            return server, found[1]
        time.sleep(0.2)
    stop_group(server.pid)
    raise RuntimeError(f"opencode serve did not report a listening URL within {TIMEOUTS['agent_start_seconds']}s")


def serve_run(directory: Path) -> None:
    """The run's unit: its OpenCode server and client, their events into `events.jsonl`, and the
    client's exit code into `exit.json`. Nothing here depends on the daemon being up."""
    spec = json.loads((directory / "run.json").read_text())
    (directory / "resume.json").unlink(missing_ok=True)
    env = environment(directory, spec)
    server, url = start_server(directory, spec["task"]["worktree"], env)
    code = 1
    try:
        v2 = spec.get('protocol') == 2
        write_json(directory / "server.json", {"pid": server.pid, "url": url, **({'protocol': 2} if v2 else {})})
        resume_v2 = False
        if spec['session'] and v2:
            from cointos import opencode2
            opencode2.AUTH.set(env['OPENCODE_PASSWORD'])
            opencode2.request(url, opencode2.path(spec['session'], 'model'), {
                'model': {'providerID': spec['model']['providerID'], 'id': spec['model']['modelID']}})
            opencode2.finish_compaction(url, spec['session'])
            history = opencode2.messages(url, spec['session'])
            resume_v2 = spec['text'] == 'Continue.' and opencode2.unfinished(history)
        elif spec["session"]:
            finish_compaction(url, spec["session"], spec["task"]["worktree"], spec["model"])
            prepare_resume(directory, url, spec)
        command = spec["command"][:2] + ["--server" if v2 else "--attach", url] + spec["command"][2:]
        with open(directory / "events.jsonl", "ab") as events, open(directory / "client.log", "ab") as errors:
            if resume_v2:
                code = opencode2.resume(url, spec['session'], events)
                return
            client = subprocess.Popen(command, cwd=spec["task"]["worktree"], env=env, stdin=subprocess.PIPE,
                                      stdout=events, stderr=errors)
            client.stdin.write(spec["text"].encode())
            client.stdin.close()
            code = client.wait()
    finally:
        try:
            write_json(directory / "exit.json", {"code": code})
        finally:
            stop_group(server.pid)
            if spec.get('protocol') == 2:
                server.wait()


def session_request(url: str, session: str, worktree: str, action: str, body=None):
    endpoint = f"{url}/session/{urllib.parse.quote(session, safe='')}/{action}?" + urllib.parse.urlencode({"directory": worktree})
    request = urllib.request.Request(endpoint, data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
    # Model work can wait for a lane and read for minutes. The daemon owns stalls and stops
    # the whole run; a transport timeout must not create a detached compaction.
    with urllib.request.urlopen(request, timeout=None) as response:
        return json.load(response)


def prepare_resume(directory: Path, url: str, spec: dict) -> bool:
    """Reuse the last user turn only when its native loop still has work to do.

    The CLI requires text. The per-run hook replaces that transport-only Continue
    with the original user metadata and no new parts, preserving its ID/time/text.
    Completed replies, summaries, reviews and reorientation receive real new turns.
    """
    if spec["text"] != "Continue.":
        return False
    messages = session_request(url, spec["session"], spec["task"]["worktree"], "message")
    user_at = next((i for i in range(len(messages) - 1, -1, -1)
                    if messages[i]["info"]["role"] == "user"), None)
    if user_at is None or any(p["type"] == "compaction" for p in messages[user_at]["parts"]):
        return False
    assistants = [m for m in messages[user_at + 1:] if m["info"]["role"] == "assistant"]
    if assistants and assistants[-1]["info"].get("finish") not in (None, "tool-calls", "unknown"):
        return False
    packet = directory / "resume.json"
    info = dict(messages[user_at]["info"])
    if spec.get("model"):
        info["model"] = spec["model"]  # a user-selected model switch also applies to unfinished turns
    with open(packet, "x", opener=lambda path, flags: os.open(path, flags, 0o600)) as stream:
        json.dump({"info": info}, stream)
    return True


def compaction_pending(url: str, session: str, worktree: str) -> bool:
    messages = session_request(url, session, worktree, "message")
    user = next((m for m in reversed(messages) if m["info"]["role"] == "user"), None)
    if not user or not any(p["type"] == "compaction" for p in user["parts"]):
        return False
    return not any(m["info"]["role"] == "assistant" and m["info"].get("summary")
                   and m["info"].get("finish") and not m["info"].get("error")
                   and m["info"].get("parentID") == user["info"]["id"] for m in messages)


def finish_compaction(url: str, session: str, worktree: str, model: dict) -> bool:
    """Complete an interrupted summary before a real recovery user turn moves its parent.

    OpenCode's native summarize endpoint creates a compaction marker, establishes its summary
    and stops (auto=False). Never edit its database or discard conversation history.
    """
    if not compaction_pending(url, session, worktree):
        return False
    session_request(url, session, worktree, "summarize", {**model, "auto": False})
    if compaction_pending(url, session, worktree):
        raise RuntimeError("OpenCode compaction did not establish a completed summary; recovery turn withheld")
    return True


@contextlib.contextmanager
def quiesce(agent_id: str):
    """Freeze the producing unit only while the daemon captures its files, then always thaw it."""
    marker = run_dir(agent_id) / 'capture-freeze.json'
    write_json(marker, {'run': agent_id})
    try:
        subprocess.run(['systemctl', '--user', 'freeze', unit(agent_id)], check=True,
                       capture_output=True, text=True, timeout=TIMEOUTS['api_seconds'])
        yield
    finally:
        thaw_capture(agent_id)


def thaw_capture(agent_id: str):
    """Recover only a freeze owned by our capture, including after daemon death."""
    marker = run_dir(agent_id) / 'capture-freeze.json'
    if not marker.exists():
        return
    if marker.is_symlink() or json.loads(marker.read_text()) != {'run': agent_id}:
        raise ValueError('invalid artifact capture ownership')
    subprocess.run(['systemctl', '--user', 'thaw', unit(agent_id)], check=True,
                   capture_output=True, text=True, timeout=TIMEOUTS['api_seconds'])
    marker.unlink()


def active(agent_id: str) -> bool:
    """Only a successful observation of a terminal unit permits reconciliation.

    A failed status query is not evidence that the run ended. Keep following it
    until systemd can answer, rather than releasing its ownership and killing it.
    """
    try:
        result = subprocess.run(["systemctl", "--user", "is-active", unit(agent_id)],
                                capture_output=True, text=True)
    except OSError:
        return True
    return not (result.returncode in (0, 3, 4)
                and result.stdout.strip() in ("inactive", "failed", "unknown"))


def stop(agent_id: str) -> None:
    subprocess.run(["systemctl", "--user", "stop", unit(agent_id)], capture_output=True)


def watch(agent_id: str, on_event) -> dict:
    """Follow a run from its files until its unit has ended. Blocking; safe to call again for a
    run already under way (after a daemon restart): it reads the events from the start.

    `on_event(kind, value)` reports "server" ((pid, server URL)), "session" (id) and "activity"
    (a one-line description of what the agent just did, or None). Returns execution facts only:
    {"finish": the last step's finish marker, "code": the client's exit code}.
    """
    directory = run_dir(agent_id)
    facts, offset, server_seen = {"finish": None, "code": None}, 0, False
    while True:
        running = active(agent_id)
        if not server_seen and (directory / "server.json").exists():
            server = json.loads((directory / "server.json").read_text())
            on_event("server", (server["pid"], server["url"]))
            server_seen = True
        try:
            with open(directory / "events.jsonl", "rb") as stream:
                stream.seek(offset)
                chunk = stream.read()
        except FileNotFoundError:
            chunk = b""
        # Once the unit is terminal, a final JSON event need not have its newline.
        # While it is live, keep unfinished lines for the next observation.
        complete = chunk[:chunk.rfind(b"\n") + 1] if running else chunk
        offset += len(complete)
        for line in complete.splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if not isinstance(event, dict):
                continue
            if isinstance(event.get("sessionID"), str) and event["sessionID"]:
                on_event("session", event["sessionID"])
            part = event.get("part") or {}
            if not isinstance(part, dict):
                part = {}
            on_event("activity", describe(part))
            if event.get("type") == "step_finish":
                facts["finish"] = part.get("reason")
            elif event.get("type") == "error" and event.get("error"):
                facts["error"] = event["error"]
        if not running and not complete:
            if (directory / "exit.json").exists():
                facts["code"] = json.loads((directory / "exit.json").read_text())["code"]
            return facts
        time.sleep(0.5)


def describe(part: dict) -> str | None:
    """One line saying what an OpenCode event part shows the agent doing, if anything."""
    if part.get("type") == "text" and isinstance(part.get("text"), str) and part["text"]:
        return " ".join(part["text"].split())[:200]
    if part.get("type") == "tool":
        state = part.get("state")
        given = state.get("input") if isinstance(state, dict) else None
        if not isinstance(given, dict):
            given = {}
        detail = next((value for value in given.values() if isinstance(value, str) and value), json.dumps(given))
        return f"{part.get('tool')}: {' '.join(str(detail).split())[:180]}"
    return None


def evidence(agent_id: str, limit: int) -> list[str]:
    """The run's most recent outward text and completed tool calls, newest first; never its
    hidden reasoning."""
    try:
        lines = (run_dir(agent_id) / "events.jsonl").read_text(errors="replace").splitlines()
    except OSError:
        return []
    found = []
    for line in reversed(lines):
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict) or not isinstance(event.get("part"), dict):
            continue
        part = event["part"]
        state = part.get("state")
        if part.get("type") == "text" and isinstance(part.get("text"), str) and part["text"]:
            found.append("OUTWARD: " + clip(part["text"]))
        elif part.get("type") == "tool" and isinstance(state, dict) and state.get("status") == "completed":
            found.append("TOOL: " + clip(part.get("tool")) + " " + clip(state.get("input"), 900) +
                         "\nRESULT: " + clip(state.get("output"), 1400))
        if len(found) >= limit:
            break
    return found


def clip(text, limit=1200) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def attach(agent: dict) -> list[str]:
    """The command that shows a live run in its matching native viewer."""
    server = run_dir(agent['id']) / 'server.json' if agent.get('id') else None
    if server and server.exists() and json.loads(server.read_text()).get('protocol') == 2:
        return [OPENCODE2, '--server', agent['url'], '--session', agent['session']]
    return [OPENCODE, "attach", agent["url"], "--session", agent["session"]]


def attach_environment(agent):
    password = run_dir(agent['id']) / 'server-password'
    return {**os.environ, **({'OPENCODE_PASSWORD': password.read_text()} if password.exists() else {})}


# ---------------------------------------------------------------- processes

def stop_group(pgid: int, grace: float = TIMEOUTS["agent_stop_grace_seconds"]) -> None:
    """Stop a process group: TERM, then KILL whatever is left."""
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.1)
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def live_processes():
    """Each live (not zombie) process: (pid, its /proc directory)."""
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            if (proc / "stat").read_text().rsplit(")", 1)[1].split()[0] == "Z":
                continue
        except OSError:
            continue
        yield int(proc.name), proc


def processes_by(variable: str) -> dict[str, list[int]]:
    """Live processes carrying an environment variable, by its value."""
    found: dict[str, list[int]] = {}
    prefix = variable.encode() + b"="
    for pid, proc in live_processes():
        try:
            environ = (proc / "environ").read_bytes()
        except OSError:
            continue
        for entry in environ.split(b"\0"):
            if entry.startswith(prefix):
                found.setdefault(entry[len(prefix):].decode(), []).append(pid)
                break
    return found


AGENT_UNIT = re.compile(r"/cointos-agent-([^/]+)\.service(?:/|$)", re.M)


def find_processes() -> dict[str, list[int]]:
    """Live agent processes, by agent id: the processes inside each agent's unit. An inherited
    COINTOS_AGENT variable (a test run, a shell started from a run) does not make an agent."""
    found: dict[str, list[int]] = {}
    for pid, proc in live_processes():
        try:
            unit_of = AGENT_UNIT.search((proc / "cgroup").read_text())
        except OSError:
            continue
        if unit_of:
            found.setdefault(unit_of[1], []).append(pid)
    return found


def compaction_context(task_id: str, agent_id: str) -> str:
    """Read current authority and local checkout facts, never hidden packet contents.

    The completion hook calls this in a bounded subprocess. Failure must not stop
    native compaction or turn an obsolete run into a current assignment.
    """
    from datetime import datetime, timezone
    from cointos import client, frontier, schema

    try:
        ledger = client.ledger(timeout=2)
        task = ledger['tasks'][task_id]
        agent = ledger['agents'].get(agent_id)
        if task.get('agent') != agent_id or not agent or agent.get('task') != task_id:
            raise ValueError('run is no longer the current task owner')
        view = frontier.inspect(task_id, ledger)
        queue = view.get('queue') or {}
        spent = schema.spent(agent)
        result = {
            'observed_at': datetime.now(timezone.utc).isoformat(),
            'task': {key: task.get(key) for key in ('id', 'status', 'role', 'record_version')},
            'queue': {key: queue.get(key) for key in ('project', 'item', 'version', 'stage', 'depends', 'held_by')},
            'accepted_test_bindings': [{k: v for k, v in binding.items() if k != 'commit'}
                                       for binding in view['binding_tests']],
            'budget': {'limit': task['budget'], 'spent_including_grants': spent,
                       'remaining': {key: None if task['budget'][key] is None else max(0, task['budget'][key] - spent[key])
                                     for key in schema.BUDGET_KEYS}},
        }
        worktree = Path(task['worktree']).resolve()
        checkout = {'path': str(worktree)}
        project = next((p for p in ledger['projects'] if p['name'] == task.get('place')), {})
        manifest = (project.get('test_policy') or {}).get('manifest')
        checkout['manifest'] = {'path': manifest, 'entries': None, 'state': 'unavailable'}
        if manifest:
            path = (worktree / manifest).resolve()
            if path.is_relative_to(worktree):
                try:
                    if path.stat().st_size > 1_000_000:
                        raise ValueError('manifest too large')
                    entries = json.loads(path.read_text())
                    if not isinstance(entries, list):
                        raise ValueError('manifest is not a list')
                    checkout['manifest'].update(entries=len(entries), state='present')
                except FileNotFoundError:
                    checkout['manifest']['state'] = 'absent'
                except (OSError, ValueError):
                    pass
        result['local_checkout'] = checkout
        answer = json.dumps(result, ensure_ascii=True, sort_keys=True)
        if len(answer) > 6000:
            raise ValueError('current context exceeds the bounded snapshot; inspect cointos_task')
        return answer
    except Exception as error:
        return json.dumps({'state': 'unavailable', 'reason': type(error).__name__,
                           'next_check': 'Re-read cointos_task and inspect local checkout; do not infer facts from summary prose.'})


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == '--compaction-context':
        print(compaction_context(sys.argv[2], sys.argv[3]))
    else:
        serve_run(Path(sys.argv[1]))
