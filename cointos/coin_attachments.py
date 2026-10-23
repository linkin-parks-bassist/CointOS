"""Telegram media descriptors and replay-safe attachment storage, independent of inference."""
import hashlib
import mimetypes
import os
from pathlib import Path
import re

from cointos import coin_files, config, privatejson


MEDIA = ('document', 'animation', 'video', 'audio', 'voice', 'video_note', 'sticker')


def attachments(message):
    selected = []
    photos = message.get('photo')
    if photos:
        if not isinstance(photos, list) or not all(isinstance(photo, dict) for photo in photos):
            raise ValueError('invalid Telegram photo sizes')
        selected.append(('photo', max(photos, key=lambda photo: photo.get('width', 0) * photo.get('height', 0))))
    for kind in MEDIA:
        if message.get(kind):
            selected.append((kind, message[kind]))
    result, seen = [], set()
    for kind, media in selected:
        if not isinstance(media, dict) or not isinstance(media.get('file_id'), str) or not media['file_id']:
            raise ValueError('invalid Telegram attachment')
        if media['file_id'] in seen:  # Telegram also exposes animations as documents
            continue
        seen.add(media['file_id'])
        entry = {'kind': kind, **{key: media[key] for key in
                 ('file_id', 'file_unique_id', 'file_name', 'mime_type', 'file_size') if key in media}}
        validate(entry)
        result.append(entry)
    return result


def validate(entry):
    if (not isinstance(entry, dict) or not {'kind', 'file_id'} <= entry.keys()
            or entry.keys() - {'kind', 'file_id', 'file_unique_id', 'file_name', 'mime_type', 'file_size'}
            or entry['kind'] not in ('photo', *MEDIA)
            or any(not isinstance(value, str) or not value for key, value in entry.items() if key != 'file_size')
            or ('file_size' in entry and (type(entry['file_size']) is not int or entry['file_size'] < 0))):
        raise ValueError('invalid retained attachment')
    return entry


def filename(entry, maximum):
    # Supplied names are labels, never filesystem paths. Keep useful Unicode and extensions.
    name = entry.get('file_name', '').replace('\\', '/').rsplit('/', 1)[-1]
    name = ''.join(char for char in name if char.isprintable()).strip().strip('.')
    if not name:
        suffix = '.jpg' if entry['kind'] == 'photo' else mimetypes.guess_extension(entry.get('mime_type', '')) or ''
        name = entry['kind'] + suffix
    # Filesystem component length is a byte boundary, not an intake size restriction.
    while len(name.encode('utf-8')) > maximum:
        name = name[:-1]
    return name


def _receipt(value):
    if (not isinstance(value, dict) or set(value) != {'file_id', 'path', 'size', 'sha256'}
            or not all(isinstance(value[key], str) and value[key] for key in ('file_id', 'path', 'sha256'))
            or type(value['size']) is not int or value['size'] < 0
            or re.fullmatch('[0-9a-f]{64}', value['sha256']) is None):
        raise ValueError('invalid attachment save receipt')
    return value


def save(root, item, entry, index, fetch, download):
    """A receipt survives later moves/removals; replay must never resurrect an organised file."""
    directory = coin_files.path(str(root / str(item['user']) / str(item['id']) / str(index)))
    def read(fd):
        return privatejson.read(fd, 'saved.json', _receipt, config._fields, None)
    with privatejson.registry(directory, read) as (fd, saved):
        payloads = directory / 'files'
        requested = privatejson.read(fd, 'request.json', validate, config._fields, None)
        if requested is not None and requested != entry:
            raise ValueError('attachment request identity changed')
        if requested is None:
            privatejson.write(fd, 'request.json', entry, validate)
        if saved is not None:
            if saved['file_id'] != entry['file_id']:
                raise ValueError('attachment save identity changed')
            privatejson.sync(fd, 'saved.json')
            return {**entry, **saved, 'present': Path(saved['path']).is_file()}
        payloads.mkdir(mode=0o700, exist_ok=True)
        if payloads.is_symlink() or not payloads.is_dir():
            raise ValueError('attachment payload directory must be a real directory')
        os.fsync(fd)
        destination = payloads / filename(entry, os.pathconf(payloads, 'PC_NAME_MAX'))
        if destination.exists():
            # Bytes committed before a crash, but the receipt did not. Never overwrite them.
            if destination.is_symlink() or not destination.is_file():
                raise ValueError('attachment destination is not a regular file')
        else:
            remote = fetch(entry['file_id'])
            if remote.get('error'):
                return {**entry, 'present': False, 'error': remote['error']}
            remote_path = remote.get('file_path')
            if not isinstance(remote_path, str) or not remote_path:
                raise ValueError('Telegram returned no downloadable file path')
            expected = remote.get('file_size', entry.get('file_size'))
            def write(stream):
                download(remote_path, stream)
                if expected is not None and stream.tell() != expected:
                    raise OSError('attachment download was incomplete')
            coin_files.publish(destination, write)
        with destination.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            os.fsync(stream.fileno())
        saved = {'file_id': entry['file_id'], 'path': str(destination),
                 'size': destination.stat().st_size, 'sha256': digest}
        privatejson.write(fd, 'saved.json', saved, _receipt)
        return {**entry, **saved, 'present': True}


def retry(root, user, update, index, fetch, download):
    if type(update) is not int or update < 0 or type(index) is not int or index < 0:
        raise ValueError('attachment update/index must be nonnegative integers')
    directory = coin_files.path(str(root / str(user) / str(update) / str(index)))
    if not directory.is_dir():
        raise FileNotFoundError('no retained attachment for this user/update/index')
    def read(fd):
        return privatejson.read(fd, 'request.json', validate, config._fields, None)
    with privatejson.registry(directory, read) as (_, entry):
        if entry is None:
            raise FileNotFoundError('no retained attachment request')
    return save(root, {'user': user, 'id': update}, entry, index, fetch, download)
