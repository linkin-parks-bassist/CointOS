"""Unfinished, user-scoped instructions survive Coin's rolling chat history."""
import copy
import hashlib
import math
import time

from cointos import config, privatejson


def _identity(value, chat=False):
    if not isinstance(value, int) or isinstance(value, bool) or (value == 0 if chat else value <= 0):
        raise ValueError('invalid request identity')


def _validate(data):
    if not isinstance(data, dict) or set(data) != {'version', 'requests'} or type(data['version']) is not int or data['version'] != 1 or not isinstance(data['requests'], dict):
        raise ValueError('invalid active requests')
    for ident, item in data['requests'].items():
        if not isinstance(item, dict) or set(item) != {'id', 'user', 'chat', 'instruction', 'created_at'}:
            raise ValueError('invalid active request')
        _identity(item['user'])
        _identity(item['chat'], chat=True)
        text = item['instruction']
        if not isinstance(text, str) or not text.strip() or ident != _id(item['user'], text) or item['id'] != ident:
            raise ValueError('invalid retained instruction')
        at = item['created_at']
        if isinstance(at, bool) or not isinstance(at, (int, float)) or not math.isfinite(at) or at < 0:
            raise ValueError('invalid request timestamp')
    return data


def _id(user, instruction):
    return hashlib.sha256((str(user) + '\0' + instruction).encode()).hexdigest()


def _registry(directory):
    return privatejson.registry(directory, lambda fd: privatejson.read(
        fd, 'requests.json', _validate, config._fields, {'version': 1, 'requests': {}}))


def retain(directory, user, chat, instruction):
    _identity(user)
    _identity(chat, chat=True)
    if not isinstance(instruction, str) or not instruction.strip():
        raise ValueError('an explicit ongoing instruction is required')
    instruction = instruction.strip()
    ident = _id(user, instruction)
    with _registry(directory) as (fd, data):
        if ident not in data['requests']:
            data['requests'][ident] = {'id': ident, 'user': user, 'chat': chat,
                                      'instruction': instruction, 'created_at': time.time()}
        privatejson.write(fd, 'requests.json', data, _validate)
        return copy.deepcopy(data['requests'][ident])


def active(directory, user):
    _identity(user)
    with _registry(directory) as (_, data):
        return copy.deepcopy(sorted((item for item in data['requests'].values() if item['user'] == user),
                                    key=lambda item: (item['created_at'], item['id'])))


def finish(directory, user, ident):
    _identity(user)
    if not isinstance(ident, str):
        raise ValueError('request id is required')
    with _registry(directory) as (fd, data):
        item = data['requests'].get(ident)
        if item is None or item['user'] != user:
            privatejson.write(fd, 'requests.json', data, _validate)
            return False
        del data['requests'][ident]
        privatejson.write(fd, 'requests.json', data, _validate)
        return True
