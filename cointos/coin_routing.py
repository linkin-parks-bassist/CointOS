"""Standing attachment destinations: filesystem work, not model turns or quotas."""
import errno
import hashlib
import math
import os
from pathlib import Path
import shutil
import time
import re

from cointos import coin_files, config, privatejson


def _origin(value):
    if (not isinstance(value, dict) or set(value) != {'update_id', 'at', 'captioned'}
            or type(value['update_id']) is not int or value['update_id'] < 0
            or type(value['at']) not in (int, float) or not math.isfinite(value['at'])
            or type(value['captioned']) is not bool):
        raise ValueError('invalid attachment origin')
    return value


def _delivered(value):
    if (not isinstance(value, dict) or set(value) != {'path', 'operation', 'size', 'sha256'}
            or not isinstance(value['path'], str) or not Path(value['path']).is_absolute()
            or value['operation'] not in ('copy', 'move') or type(value['size']) is not int or value['size'] < 0
            or not isinstance(value['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', value['sha256'])):
        raise ValueError('invalid attachment delivery receipt')
    return value


def _validate(data):
    if not isinstance(data, dict) or set(data) != {'version', 'routes'} or type(data['version']) is not int or data['version'] != 1 or not isinstance(data['routes'], dict):
        raise ValueError('invalid attachment routes')
    for user, route in data['routes'].items():
        if (not user.isdigit() or int(user) <= 0 or not isinstance(route, dict)
                or set(route) != {'destination', 'operation', 'start_at', 'initial_inputs'}
                or not isinstance(route['destination'], str) or not Path(route['destination']).is_absolute()
                or route['operation'] not in ('copy', 'move')
                or type(route['start_at']) not in (int, float) or not math.isfinite(route['start_at'])
                or not isinstance(route['initial_inputs'], list)
                or any(type(v) is not int or v < 0 for v in route['initial_inputs'])):
            raise ValueError('invalid attachment route')
    return data


def _registry(root):
    return privatejson.registry(root, lambda fd: privatejson.read(
        fd, 'routes.json', _validate, config._fields, {'version': 1, 'routes': {}}))


def get(root, user):
    with _registry(root) as (_, data):
        route = data['routes'].get(str(user))
        return dict(route) if route else None


def configure(root, user, destination, operation='copy', *, start_at=None, initial_inputs=()):
    if type(user) is not int or user <= 0 or operation not in ('copy', 'move'):
        raise ValueError('invalid route identity or operation')
    destination = coin_files.path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    with _registry(root) as (fd, data):
        route = data['routes'].get(str(user))
        if not route or (route['destination'], route['operation']) != (str(destination), operation):
            route = {'destination': str(destination), 'operation': operation,
                     'start_at': time.time() if start_at is None else start_at, 'initial_inputs': []}
        route['initial_inputs'] = sorted(set(route['initial_inputs']) | set(initial_inputs))
        data['routes'][str(user)] = route
        privatejson.write(fd, 'routes.json', data, _validate)
        return dict(route)


def stop(root, user):
    with _registry(root) as (fd, data):
        removed = data['routes'].pop(str(user), None) is not None
        privatejson.write(fd, 'routes.json', data, _validate)
        return removed


def origin(root, item, index):
    directory = root / str(item['user']) / str(item['id']) / str(index)
    with privatejson.registry(directory, lambda fd: None) as (fd, _):
        privatejson.write(fd, 'origin.json', {'update_id': item['id'], 'at': item.get('at', time.time()),
                         'captioned': bool(item['text'].strip())}, _origin)


def receipt(root, user, update, index):
    directory = root / str(user) / str(update) / str(index)
    if not directory.exists():
        return None
    with privatejson.registry(directory, lambda fd: privatejson.read(
            fd, 'routed.json', _delivered, config._fields, None)) as (_, value):
        return {**value, 'present': coin_files.path(value['path']).is_file()} if value else None


def _hash(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def deliver(root, user, update, index, saved, route):
    """A normal copy/move, once. Hash only a collision before reusing its destination."""
    directory = root / str(user) / str(update) / str(index)
    with privatejson.registry(directory, lambda fd: privatejson.read(
            fd, 'routed.json', _delivered, config._fields, None)) as (fd, previous):
        if previous:
            return {**previous, 'present': coin_files.path(previous['path']).is_file()}
        source = coin_files.path(saved['path'])
        if not source.resolve().is_relative_to((root / str(user)).resolve()):
            raise ValueError('attachment source is outside this user\'s inbox')
        if source.is_symlink() or not source.is_file():
            raise FileNotFoundError('attachment inbox file is absent; it may already have been organised')
        folder = coin_files.path(route['destination'])
        folder.mkdir(parents=True, exist_ok=True)
        name = f'photo_{update}' + (f'_{index}' if index else '') + source.suffix
        target = coin_files.path(str(folder / name))
        if target.exists() or target.is_symlink():
            if target.is_symlink() or not target.is_file() or _hash(target) != saved['sha256']:
                raise FileExistsError('destination collision; existing file preserved')
            if route['operation'] == 'move' and _hash(source) != saved['sha256']:
                raise ValueError('inbox file changed; both files preserved')
        else:
            if route['operation'] == 'move':
                try:
                    os.link(source, target)
                except OSError as error:
                    if error.errno != errno.EXDEV:
                        raise
                    with source.open('rb') as stream:
                        coin_files.publish(target, lambda output: shutil.copyfileobj(stream, output))
            else:
                with source.open('rb') as stream:
                    coin_files.publish(target, lambda output: shutil.copyfileobj(stream, output))
        parent = os.open(folder, os.O_DIRECTORY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
        result = {'path': str(target), 'operation': route['operation'], 'size': saved['size'],
                  'sha256': saved['sha256']}
        # Publish delivery before removing the inbox original. An interrupted move
        # may leave an extra original, but cannot lose its durable destination receipt.
        privatejson.write(fd, 'routed.json', result, _delivered)
        if route['operation'] == 'move':
            source.unlink()
            parent = os.open(source.parent, os.O_DIRECTORY)
            try:
                os.fsync(parent)
            finally:
                os.close(parent)
        return {**result, 'present': True}


def failure(root, user, update, message):
    directory = root / str(user) / str(update)
    def validate(value):
        if not isinstance(value, dict) or set(value) != {'message', 'at'} or not isinstance(value['message'], str) or type(value['at']) not in (int, float) or not math.isfinite(value['at']):
            raise ValueError('invalid attachment failure')
        return value
    with privatejson.registry(directory, lambda fd: None) as (fd, _):
        if message is None:
            try:
                os.unlink('failed.json', dir_fd=fd)
            except FileNotFoundError:
                pass
            os.fsync(fd)
        else:
            privatejson.write(fd, 'failed.json', {'message': message, 'at': time.time()}, validate)


def catch_up(root, routing, allowed):
    """Route already-saved photos received since the user's instruction, without rereading bytes."""
    for user_dir in root.iterdir() if root.exists() else ():
        if not user_dir.name.isdigit() or user_dir.is_symlink() or int(user_dir.name) not in allowed:
            continue
        user = int(user_dir.name)
        for file in user_dir.glob('*/*/origin.json'):
            if (file.parent / 'routed.json').exists():
                continue  # completed delivery needs no reread, recount or revalidation
            route = get(routing, user)
            if route is None:
                break
            if not file.parent.name.isdigit() or not file.parent.parent.name.isdigit():
                continue
            update = int(file.parent.parent.name)
            try:
                with privatejson.registry(file.parent, lambda fd: (
                        privatejson.read(fd, 'origin.json', _origin, config._fields, None),
                        config.read_owned_json(file.parent / 'saved.json'),
                        config.read_owned_json(file.parent / 'request.json'))) as (_, values):
                    item, saved, request = values
                if item['at'] < route['start_at'] or (item['captioned'] and item['update_id'] not in route['initial_inputs']):
                    continue
                if saved and request and request['kind'] == 'photo':
                    deliver(root, user, update, int(file.parent.name), saved, route)
                    failure(root, user, update, None)
            except (OSError, ValueError) as error:
                failure(root, user, update, str(error))
