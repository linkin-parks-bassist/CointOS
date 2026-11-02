"""User-facing results outlive task identities and rolling conversation history."""
import hashlib
import math
import time
from pathlib import Path

from cointos import config, privatejson


def identity(user, chat, location, milestone):
    return hashlib.sha256(f'{user}\0{chat}\0{location}\0{milestone}'.encode()).hexdigest()


def _validate(data):
    if not isinstance(data, dict) or set(data) != {'version', 'reports'} or type(data['version']) is not int or data['version'] != 1 or not isinstance(data['reports'], dict):
        raise ValueError('invalid result reports')
    for key, item in data['reports'].items():
        if (not isinstance(item, dict) or set(item) != {'user', 'chat', 'location', 'milestone', 'message', 'evidence', 'at'}
                or type(item['user']) is not int or item['user'] <= 0
                or type(item['chat']) is not int or not item['chat']
                or any(not isinstance(item[k], str) or not item[k].strip()
                       for k in ('location', 'milestone', 'message'))
                or not isinstance(item['evidence'], list) or not item['evidence']
                or any(not isinstance(e, dict) for e in item['evidence'])
                or type(item['at']) not in (int, float)
                or not math.isfinite(item['at']) or item['at'] < 0
                or key != identity(item['user'], item['chat'], item['location'], item['milestone'])):
            raise ValueError('invalid result report')
    return data


def _registry(directory):
    return privatejson.registry(directory, lambda fd: privatejson.read(
        fd, 'reports.json', _validate, config._fields, {'version': 1, 'reports': {}}))


def context(directory, user, chat):
    with _registry(directory) as (_, data):
        return [dict(item) for item in data['reports'].values()
                if item['user'] == user and item['chat'] == chat]


def deliver(directory, user, chat, location, milestone, message, evidence, sender):
    try:
        location = str(Path(location).expanduser().resolve(strict=True))
    except (OSError, RuntimeError) as error:
        raise ValueError('result location must exist; inspect its current location before reporting') from error
    milestone = '-'.join(milestone.lower().split())
    if not milestone or not message.strip() or not evidence:
        raise ValueError('a result needs a milestone, message and current verification evidence')
    key = identity(user, chat, location, milestone)
    with _registry(directory) as (fd, data):
        if key in data['reports']:
            return {'ok': True, 'sent': False, 'reason': 'already reported',
                    'report': {k: data['reports'][key][k] for k in ('location', 'milestone', 'message', 'at')}}
        item = {'user': user, 'chat': chat, 'location': location, 'milestone': milestone,
                'message': message, 'evidence': evidence, 'at': time.time()}
        # Validate before sending. A failed send must remain retryable. As with
        # normal Telegram egress, a crash after acceptance can still repeat delivery.
        _validate({'version': 1, 'reports': {key: item}})
        sender(message)
        data['reports'][key] = item
        privatejson.write(fd, 'reports.json', data, _validate)
    return {'ok': True, 'sent': True}
