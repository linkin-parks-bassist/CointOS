"""Independent startup repair. Native service/session evidence lives outside the ledger.

The launcher imports no shared daemon state and uses the installed Codex harness's
remote provider. A model's proposed handback is checked against live authority.
"""
import fcntl
from contextlib import contextmanager
import hashlib
import json
import os
import shutil
import stat
from pathlib import Path
import subprocess
import sys
import urllib.request
import uuid

SCHEMA = {"type": "object", "additionalProperties": False,
          "properties": {"outcome": {"type": "string", "enum": ["complete", "blocked"]},
                         "summary": {"type": "string"},
                         "evidence": {"type": "array", "items": {"type": "string"}}},
          "required": ["outcome", "summary", "evidence"]}


def service(unit):
    result = subprocess.run(["systemctl", "--user", "show", unit, "-p", "ActiveState", "-p", "MainPID", "-p", "InvocationID", "-p", "LoadState"],
                            capture_output=True, text=True, check=True)
    return dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)


def inspect(root, unit):
    """Retain known ownership without copying gateway secrets into the assignment."""
    from cointos import config, startup
    from cointos.keys import _validate
    before = {"unit": unit, "authority": None, "tasks": {}, "queue": {}, "projects": {}, "keys": {}, "units": {}, "errors": []}
    try:
        previous = config.validate_ledger(config.read_owned_json(root / "state/cointos.json", {}))
        before["tasks"] = {name: {field: task.get(field) for field in
                                  ("session", "receipt", "acceptance", "held_by", "admission_hold", "cancelled")}
                           for name, task in previous.get("tasks", {}).items()}
        before["queue"] = {name: {"version": record.get("version"), "held_by": record.get("held_by")}
                           for name, record in previous.get("queue", {}).items()}
    except (OSError, ValueError) as error:
        before["errors"].append(f"prior ledger ownership unavailable: {error}")
    try:
        registry = config.read_owned_json(root / "config/projects.json", {"projects": []})
        if not isinstance(registry, dict) or "projects" not in registry:
            raise ValueError("invalid project registry")
        before["projects"] = {project["name"]: {**project, "path": str(Path(project["path"]).expanduser())}
                              for project in config.project_entries(registry["projects"])}
    except (OSError, ValueError) as error:
        before["errors"].append(f"prior enrollment unavailable: {error}")
    try:
        data = _validate(config.read_owned_json(root / "state/keys.json", {}))
        before["keys"] = {name: hashlib.sha256(key.encode()).hexdigest()
                          for name, key in {**data.get("agents", {}), **({"coin": data["coin"]} if "coin" in data else {})}.items()}
    except (OSError, ValueError) as error:
        before["errors"].append(f"prior gateway ownership unavailable: {error}")
    if not before['errors']:
        before['authority'] = startup.fingerprint(startup.authority(previous, list(before['projects'].values()), data))
    result = subprocess.run(["systemctl", "--user", "list-units", "cointos-agent-*", "--state=active,activating",
                             "--plain", "--no-legend", "--no-pager"], capture_output=True, text=True, check=True)
    for line in result.stdout.splitlines():
        name = line.split()[0]
        run = name.removeprefix("cointos-agent-").removesuffix(".service")
        if name.startswith("cointos-agent-") and name.endswith(".service") and run in before["keys"]:
            before["units"][name] = service(name)
    return before


def check(root, unit, before):
    """A restored API and preserved known ownership, never a model claim alone."""
    from cointos import config, startup
    from cointos.keys import _validate
    failures = list(before.get("errors", []))
    try:
        settings = config.load(root / "config/cointos.json", root / "config/projects.json")
        projects = startup.projects(settings['projects'])
        config.validate_ledger(config.read_owned_json(root / "state/cointos.json", {}))
        data = _validate(config.read_owned_json(root / "state/keys.json", {}))
        if "coin" not in data:
            failures.append("fixed Coin key is missing")
        current = service(unit)
        if current.get("ActiveState") != "active" or not int(current.get("MainPID", "0")):
            failures.append("daemon service is not active")
        with urllib.request.urlopen(config.api_url(settings) + "/api/ledger",
                                    timeout=settings["timeouts"]["api_seconds"]) as response:
            ledger = config.validate_ledger(json.load(response))
        if (not isinstance(ledger.get("checks"), list) or not ledger["checks"]
                or any(not isinstance(item, dict) or item.get("ok") is not True for item in ledger["checks"])):
            failures.append("live daemon checks have not passed")
        if projects != startup.projects(ledger.get('projects', [])):
            failures.append('current enrollment differs between disk and live daemon authority')
        if ledger.get('gateway_coin') != startup.key_digests(data).get('coin'):
            failures.append('fixed Coin key does not match loaded daemon ownership')
        certificate = ledger.get('startup')
        if (not isinstance(certificate, dict) or certificate.get('pid') != int(current.get('MainPID', '0'))
                or not before.get('authority') or certificate.get('authority') != before['authority']):
            failures.append('daemon startup did not verify retained authority for this native process')
        witnessed = certificate.get('units', {}) if isinstance(certificate, dict) else {}
        for name, original in before['units'].items():
            born = witnessed.get(name) if isinstance(witnessed, dict) else None
            if (not isinstance(original, dict) or not isinstance(born, dict) or born.get('load_state') not in ('loaded', 'masked')
                    or not isinstance(born.get('pid'), str) or not born['pid'].isdigit()
                    or born.get('state') not in ('active', 'activating', 'deactivating', 'inactive', 'failed')
                    or (born['state'] in ('inactive', 'failed') and born['pid'] != '0')):
                failures.append('startup native ownership unavailable: ' + name)
            elif born['state'] not in ('inactive', 'failed'):
                if (born.get('pid') != original.get('MainPID') or born.get('pid') in (None, '', '0')
                        or (original.get('InvocationID') and born.get('invocation') != original['InvocationID'])):
                    failures.append('startup surviving unit identity changed: ' + name)
        # Coin remains fixed. Agent identities and historical task records may legitimately
        # end, be revised, or be cleared after their startup restoration was verified.
        if before['keys'].get('coin') and startup.key_digests(data).get('coin') != before['keys']['coin']:
            failures.append('retained gateway identity changed: coin')
        environment = {**os.environ, "COINTOS_CONFIG": str(root / "config/cointos.json"),
                       "COINTOS_PROJECTS": str(root / "config/projects.json"), "COINTOS_STATE": str(root / "state"),
                       "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
        subprocess.run([sys.executable, "-m", "cointos.cli", "check"], cwd=root, env=environment,
                       capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as error:
        detail = f"repair check unavailable: {error}"
        for name, output in (("stderr", error.stderr), ("stdout", error.stdout)):
            if output and output.strip():
                detail += f"\n{name}:\n{output.strip()[-2000:]}"
        failures.append(detail)
    except (OSError, ValueError, KeyError, TypeError) as error:
        failures.append(f"repair check unavailable: {error}")
    return failures


def assignment(root, unit, before):
    return (f"You are an independent repair Operator. Diagnose and repair startup of {unit} in {root}. "
            "CointOS's daemon/gateway is unavailable; use native files, Git, journal and systemctl --user. "
            "Read its owning knowledge tree and preserve every existing source edit, project, task, session, "
            "receipt, acceptance, key identity and explicit user hold. Source is named by .runtime-install. "
            "Scope is CointOS source/runtime and its user services; do not implement or edit managed product work. "
            "This repair owns the runtime installation lock: scripts/install will refuse while you run. "
            "Repair installed/source code directly within scope, preserve edits, and do not bypass ownership. "
            "Respect professional-data disclosure rules; do not use sudo, credentials, "
            "Git push or external messaging. Preserve configured question/blockage delivery; routine diagnostics remain local. "
            "The daemon is the sole ledger writer: do not edit/delete/reset the ledger or keys to force startup. "
            "Never invent lost ownership or replace damaged authority with empty data. If unique recovery "
            "cannot be established, preserve evidence and return blocked with the exact missing evidence. "
            "Repair the cause, start the named daemon and check its actual API/native ownership before "
            "proposing complete. Do not halt models or surviving agent units. No recursive helper chain. "
            "Keep affected knowledge current. Your structured response is a proposed handback, not a "
            "CointOS completion receipt; the launcher independently checks it.\n\nPrior ownership:\n" + json.dumps(before))


def execute(directory, prompt):
    """Retain the actual Codex thread across interrupted launcher/model turns."""
    from cointos import config
    events = directory / "events.jsonl"
    thread = None
    text = config.read_owned_text(events, "")
    if text:
        for line in text.splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if (isinstance(event, dict) and event.get("type") == "thread.started"
                    and isinstance(event.get("thread_id"), str) and event["thread_id"].strip()):
                thread = event["thread_id"]
    output = directory / (uuid.uuid4().hex + ".json")
    binary = shutil.which("codex")
    if not binary:
        raise FileNotFoundError("independent repair requires the installed Codex CLI")
    command = [binary, "--cd", str(directory.parents[2]), "-c", 'model_provider="openai"', "exec"]
    if thread:
        command += ["resume", thread]
    schema = directory / "schema.json"
    config.write_json(schema, SCHEMA, mode=0o600)
    # The installed runtime is intentionally not a Git checkout. This option
    # declares that deployment shape; it does not change tool or approval policy.
    command += ["--skip-git-repo-check", "--output-schema", str(schema)]
    command += ["--json", "--output-last-message", str(output), "-"]
    descriptor = os.open(events, os.O_APPEND | os.O_CREAT | os.O_WRONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise ValueError("repair events are not a regular file")
    with os.fdopen(descriptor, "a", encoding="utf-8") as log:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=log, stderr=None, text=True)
        process.communicate(prompt)
    if process.returncode:
        raise subprocess.CalledProcessError(process.returncode, command)
    result = config.read_owned_json(output)
    if (not isinstance(result, dict) or result.get("outcome") not in ("complete", "blocked")
            or not isinstance(result.get("summary"), str) or not result["summary"].strip()
            or not isinstance(result.get("evidence"), list) or not result["evidence"]
            or any(not isinstance(item, str) or not item.strip() for item in result["evidence"])):
        raise ValueError("Codex did not return a complete semantic handback; retained thread needs continuation")
    return result


@contextmanager
def ownership(root, *, wait=False):
    """Share repair/installation ownership; native repair waits through installation."""
    repairs = root / "state/repairs"
    repairs.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(repairs / "owner.lock", os.O_CREAT | os.O_RDWR | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise ValueError("repair owner is not a regular file")
    with os.fdopen(descriptor, "r+") as owner:
        try:
            fcntl.flock(owner, fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
        except BlockingIOError:
            yield False
            return
        yield True


def supersede_installation(root):
    """An explicit installation ends an older repair assignment, without certifying it.

    Caller owns the installation/repair lease and has stopped the repair service.
    Keep the original snapshot and transcript; the next OnFailure owns a new epoch.
    """
    from cointos import config
    current = config.read_owned_json(root / 'state/repairs/current.json')
    if current is None:
        return
    identity = current.get('directory') if isinstance(current, dict) else None
    if (not isinstance(identity, str) or len(identity) != 32
            or any(c not in '0123456789abcdef' for c in identity)):
        raise ValueError('invalid retained repair identity')
    directory = root / 'state/repairs' / identity
    if config.read_owned_json(directory / 'checked.json') is not None:
        return
    config.write_json(directory / 'checked.json', {
        'outcome': 'blocked', 'superseded_by': 'installation',
        'summary': 'An explicit runtime installation superseded this repair assignment.',
        'evidence': ['The original authority snapshot and native events remain retained.',
                     'This is not certification of the old repair; the next startup failure owns a new baseline.']}, mode=0o600)


def main(root, unit):
    from cointos import config
    repairs = root / "state/repairs"
    with ownership(root, wait=True) as acquired:
        if not acquired:
            return
        absent = object()
        current = config.read_owned_json(repairs / "current.json", absent)
        directory = None
        if current is not absent:
            if (not isinstance(current, dict) or not isinstance(current.get("directory"), str)
                    or len(current["directory"]) != 32 or any(c not in "0123456789abcdef" for c in current["directory"])):
                raise ValueError("invalid retained repair identity")
            directory = repairs / current["directory"]
            terminal = config.read_owned_json(directory / "checked.json", absent)
            if terminal is not absent:
                if not isinstance(terminal, dict) or terminal.get("outcome") not in ("complete", "blocked"):
                    raise ValueError("invalid retained repair handback")
                directory = None
        if directory is None:
            directory = repairs / uuid.uuid4().hex
            directory.mkdir(mode=0o700)
            before = inspect(root, unit)
            config.write_json(directory / "before.json", before, mode=0o600)
            config.write_json(repairs / "current.json", {"directory": directory.name}, mode=0o600)
        else:
            before = config.read_owned_json(directory / "before.json")
            if not isinstance(before, dict) or before.get("unit") != unit:
                raise ValueError("retained repair belongs to missing or different assignment")
        failures = check(root, unit, before)
        if not failures:
            config.write_json(directory / "checked.json", {"outcome": "complete", "evidence": ["startup and retained ownership verified"]}, mode=0o600)
            return
        prompt = assignment(root, unit, before) + "\nCurrent refusal:\n" + json.dumps(failures)
        proposed = execute(directory, prompt)
        config.write_json(directory / "proposed.json", proposed, mode=0o600)
        failures = check(root, unit, before)
        if not failures:
            config.write_json(directory / "checked.json", {**proposed, "outcome": "complete", "checks": []}, mode=0o600)
        elif proposed["outcome"] == "blocked":
            config.write_json(directory / "checked.json", {**proposed, "checks": failures}, mode=0o600)
        else:
            raise ValueError("proposed completion refused: " + "; ".join(failures))


if __name__ == "__main__":
    main(Path(sys.argv[1]), sys.argv[2])
