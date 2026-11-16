"""Install a separate, pinned server bundle without overwriting Lemonade's package."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

candidate, expected = Path(sys.argv[1]), sys.argv[2]
seal = sys.argv[3:] == ['--seal']
original = Path('/var/cache/lemonade/bin/llamacpp/vulkan')
destination = Path('/opt/cointos-llama-state-size/1a24df163-v1/bin')
if os.geteuid() != 0:
    raise SystemExit('Run through the authorised sudo askpass workflow.')
if hashlib.sha256(candidate.read_bytes()).hexdigest() != expected:
    raise SystemExit('Candidate changed after verification.')
if destination.exists() and not seal:
    raise SystemExit('Refusing to overwrite an existing qualified bundle.')
if seal and json.loads((destination.parent / 'build.json').read_text()).get('upstream') != '1a24df163':
    raise SystemExit('Refusing to modify a different server bundle.')
destination.mkdir(parents=True, mode=0o755, exist_ok=seal)
# Install regular libraries before their local aliases. Current mapped inodes stay intact.
for entry in original.iterdir():
    if entry.name not in ('llama-server', 'libllama-server-impl.so') and not entry.is_symlink():
        temporary = destination / (entry.name + '.new')
        shutil.copy2(entry, temporary)
        os.replace(temporary, destination / entry.name)
for entry in original.iterdir():
    if entry.is_symlink() and entry.name != 'libllama-server-impl.so':
        temporary = destination / (entry.name + '.new')
        temporary.symlink_to(entry.resolve().name)
        os.replace(temporary, destination / entry.name)
for source, name in [(original / 'llama-server', 'llama-server'), (candidate, 'libllama-server-impl.so')]:
    temporary = destination / (name + '.new')
    shutil.copy2(source, temporary)
    os.replace(temporary, destination / name)
(destination.parent / 'build.json').write_text(json.dumps({
    'upstream': '1a24df163', 'patch': 'native-size.patch', 'implementation_sha256': expected,
    'original_core': str(original), 'native_ui': 'b11846',
    'core_pinned': True,
}, indent=2) + '\n')
print(destination / 'llama-server')
