"""Coin owns Telegram cursor and pending requested work in one durable transaction."""
import copy
import math
import time
from contextlib import contextmanager
from pathlib import Path

from cointos import config, privatejson, coin_attachments

FILE = 'intake.json'


def _integer(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _validate(data):
    if (not isinstance(data, dict) or set(data) != {'version', 'offset', 'inputs'} or not _integer(data['version']) or data['version'] != 1
            or (data['offset'] is not None and (not _integer(data['offset']) or data['offset'] < 0))
            or not isinstance(data['inputs'], dict)):
        raise ValueError('invalid Coin input authority')
    for ident, item in data['inputs'].items():
        required = {'id', 'user', 'chat', 'text', 'kind', 'receipt'}
        if (not isinstance(item, dict) or not required <= item.keys()
                or item.keys() - required - {'at', 'attachments', 'media_group_id', 'reply_to'}
                or not _integer(item['id']) or item['id'] < 0 or ident != str(item['id'])
                or not _integer(item['user']) or item['user'] <= 0 or not _integer(item['chat']) or item['chat'] == 0
                or not isinstance(item['text'], str) or not (item['text'].strip() or item.get('attachments'))
                or item['kind'] != ('status' if item['text'].strip().lower() in ('status', '/status') else 'message')
                or data['offset'] is None or item['id'] >= data['offset']):
            raise ValueError('invalid pending Coin input')
        if 'attachments' in item:
            if not isinstance(item['attachments'], list) or not item['attachments']:
                raise ValueError('invalid pending attachments')
            for entry in item['attachments']:
                coin_attachments.validate(entry)
        if 'media_group_id' in item and (not isinstance(item['media_group_id'], str) or not item['media_group_id']):
            raise ValueError('invalid Telegram album identity')
        if 'at' in item and (isinstance(item['at'], bool) or not isinstance(item['at'], (int, float))
                             or not math.isfinite(item['at']) or item['at'] < 0):
            raise ValueError('invalid Coin input timestamp')
        if 'reply_to' in item:
            reply = item['reply_to']
            if (not isinstance(reply, dict) or set(reply) != {'message_id', 'text', 'at', 'bot'}
                    or not _integer(reply['message_id']) or reply['message_id'] <= 0
                    or not isinstance(reply['text'], str) or type(reply['bot']) is not bool
                    or (reply['at'] is not None and (not _integer(reply['at']) or reply['at'] < 0))):
                raise ValueError('invalid Telegram reply reference')
        receipt = item['receipt']
        if receipt is not None and (not isinstance(receipt, dict) or set(receipt) != {'message_id'}
                                    or not _integer(receipt['message_id']) or receipt['message_id'] <= 0):
            raise ValueError('invalid Coin input delivery receipt')
    return data


@contextmanager
def _registry(directory, legacy=None):
    def read(fd):
        absent = object()
        data = privatejson.read(fd, FILE, _validate, config._fields, absent)
        if data is absent:
            absent_cursor = object()
            cursor = config.read_owned_json(Path(legacy), absent_cursor) if legacy is not None else absent_cursor
            if cursor is absent_cursor:
                cursor = None
            elif not _integer(cursor) or cursor < 0:
                raise ValueError('invalid legacy Telegram cursor')
            data = {'version': 1, 'offset': cursor, 'inputs': {}}
            privatejson.write(fd, FILE, data, _validate)
        return data
    with privatejson.registry(directory, read) as value:
        yield value


def offset(directory, legacy=None):
    with _registry(directory, legacy) as (_, data):
        return data['offset']


def accept(directory, update, allowed):
    if not isinstance(update, dict) or not _integer(update.get('update_id')) or update['update_id'] < 0:
        raise ValueError('invalid Telegram update identity')
    ident = update['update_id']
    message = update.get('message', {})
    if not isinstance(message, dict) or not isinstance(message.get('from', {}), dict) or not isinstance(message.get('chat', {}), dict):
        raise ValueError('invalid Telegram message identity')
    user, chat = message.get('from', {}).get('id'), message.get('chat', {}).get('id')
    media = coin_attachments.attachments(message) if user in allowed else []
    text = message.get('text', message.get('caption', '') if media else '')
    candidate = None
    if isinstance(text, str) and (text.strip() or media):
        if not _integer(user) or user <= 0 or not _integer(chat) or chat == 0:
            raise ValueError('text has no valid Telegram user/chat identity')
        at = message.get('date', time.time())
        if isinstance(at, bool) or not isinstance(at, (int, float)) or not math.isfinite(at) or at < 0:
            raise ValueError('invalid Telegram message timestamp')
        candidate = {'id': ident, 'user': user, 'chat': chat, 'text': text, 'at': at,
                     'kind': 'status' if text.strip().lower() in ('status', '/status') else 'message', 'receipt': None}
        if isinstance(message.get('reply_to_message'), dict):
            reply = message['reply_to_message']
            candidate['reply_to'] = {'message_id': reply.get('message_id'),
                'text': reply.get('text', reply.get('caption', '')), 'at': reply.get('date'),
                'bot': bool(reply.get('from', {}).get('is_bot', False))}
        if media:
            candidate['attachments'] = media
            if 'media_group_id' in message:
                candidate['media_group_id'] = message['media_group_id']
    with _registry(directory) as (fd, data):
        existing = data['inputs'].get(str(ident))
        if existing is not None and (candidate is None or any(existing.get(field) != candidate.get(field)
                                    for field in ('id', 'user', 'chat', 'text', 'kind', 'attachments', 'media_group_id', 'reply_to'))):
            raise ValueError('duplicate Telegram update changed its retained input')
        if data['offset'] is not None and ident < data['offset']:
            privatejson.sync(fd, FILE)
            return copy.deepcopy(existing)
        item = candidate if candidate is not None and user in allowed else None
        if item is not None:
            data['inputs'][str(ident)] = item
        data['offset'] = ident + 1
        privatejson.write(fd, FILE, data, _validate)
        return copy.deepcopy(item)


def pending(directory):
    with _registry(directory) as (fd, data):
        privatejson.sync(fd, FILE)
        return [copy.deepcopy(item) for _, item in sorted(data['inputs'].items(), key=lambda pair: int(pair[0]))]


def receipted(directory, ident, message_id):
    if not _integer(ident) or ident < 0 or not _integer(message_id) or message_id <= 0:
        raise ValueError('Telegram did not return a delivery message identity')
    with _registry(directory) as (fd, data):
        item = data['inputs'].get(str(ident))
        if item is not None:
            item['receipt'] = {'message_id': message_id}
            privatejson.write(fd, FILE, data, _validate)


def complete(directory, identifiers):
    identifiers = list(identifiers)
    if any(not _integer(ident) or ident < 0 for ident in identifiers):
        raise ValueError('invalid completed Telegram input identity')
    with _registry(directory) as (fd, data):
        for ident in identifiers:
            data['inputs'].pop(str(ident), None)
        privatejson.write(fd, FILE, data, _validate)
