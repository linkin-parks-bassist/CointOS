"""The Cointel identities: three Coin processes over one daemon.

One CointOS keeps the ledger, scheduler, GPU and model lane. Each identity adds only what it
must own alone: a bot credential, a display name, a conversation owner, an archive directory
and a station directory. No daemon, ledger or scheduler is multiplied.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / 'config/coins'


def names(base: Path = PROFILES) -> list[str]:
    return sorted(path.stem for path in base.glob('*.json'))


def profile(name: str | None, base: Path = PROFILES) -> dict:
    """The identity's own settings; absence means the historical single Coin."""
    if not name:
        return {}
    path = base / f'{name}.json'
    if not path.is_file():
        raise ValueError(f'unknown Cointel identity {name!r}; known: {", ".join(names(base))}')
    document = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(document, dict) or document.get('identity') in (None, ''):
        raise ValueError(f'Cointel identity {name} must name its identity slug')
    for key in ('identity', 'name', 'station', 'telegram_env'):
        if not isinstance(document.get(key), str) or not document[key].strip():
            raise ValueError(f'Cointel identity {name} must set {key}')
    for key in ('retain_archive', 'retain_diagnostics'):
        if key in document and type(document[key]) is not bool:
            raise ValueError(f'Cointel identity {name} must set {key} to a boolean')
    return document


def state(identity: str | None) -> str:
    """The Coin archive directory name: identity-scoped, never shared."""
    return 'coin' if not identity else f'coin-{identity}'


def unit(name: str) -> str:
    return f'cointel-{name}-coin.service'


def station(path: str) -> Path:
    return Path(path).expanduser()


def retains_diagnostics(identity: str | None) -> bool:
    for name in names():
        settings = profile(name)
        if settings['identity'] == identity:
            return settings.get('retain_diagnostics', True)
    return True
