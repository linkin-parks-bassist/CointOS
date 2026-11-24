#!/usr/bin/env python3
"""Explicit assisted Telegram qualification, using only generated test content.

Run against installed code with PYTHONPATH="$HOME/.CointOS" python3 -P ...
--send sends labelled fixtures to the sole configured user. --check only inspects
those receipts and downloads the fixture. --model runs an isolated native Coin
turn using the installed model and real delivery tools, without steering a resident.
Evidence stays outside maintained source/knowledge; bot tokens are never printed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time

parser = argparse.ArgumentParser()
parser.add_argument('--profile', required=True, choices=['amateur', 'professional', 'personal'])
parser.add_argument('--evidence', type=Path, required=True)
parser.add_argument('--send', action='store_true')
parser.add_argument('--check', action='store_true')
parser.add_argument('--model', action='store_true')
parser.add_argument('--model-discovery', action='store_true')
args = parser.parse_args()
os.environ['COINTEL'] = args.profile
from cointos import coin  # noqa: E402; select identity before production import

if Path(coin.__file__).resolve().parents[1] != Path.home() / '.CointOS':
    raise SystemExit('This probe must use the installed package')
root = args.evidence.resolve() / args.profile
root.mkdir(parents=True, exist_ok=True, mode=0o700)
# Never read resident conversations or write resident dashboard/turn state.
coin.COIN_STATE = root / 'isolated-state'
coin.ensure_state()
coin.report = lambda *a, **kw: None
coin.journal = lambda entry: None
token, allowed = coin.credentials()
if len(allowed) != 1:
    raise SystemExit('Probe requires exactly one configured recipient')
user = chat = next(iter(allowed))
receipt_path = root / 'receipts.json'
receipts = json.loads(receipt_path.read_text()) if receipt_path.exists() else {}


def invoke(method, arguments):
    result = coin.invoke('telegram_' + method, arguments, token, user, chat, None)
    if not result.get('ok'):
        raise RuntimeError(f'{method}: {result.get("error", "refused")}')
    print(json.dumps({'at': time.time(), 'profile': args.profile, 'method': method, 'ok': True}), flush=True)
    return result.get('result', result)


if args.send or args.model:
    from PIL import Image, ImageDraw, ImageFont
    image = Image.new('RGB', (720, 400), '#101b2b')
    draw = ImageDraw.Draw(image)
    font = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
    draw.rounded_rectangle((28, 28, 692, 372), radius=22, outline='#49d6be', width=3)
    draw.text((60, 72), 'Telegram tools', font=ImageFont.truetype(font, 44), fill='#ffffff')
    draw.text((60, 150), 'Live upload verification', font=ImageFont.truetype(font, 25), fill='#49d6be')
    draw.text((60, 220), 'Cointel ' + args.profile.capitalize(), font=ImageFont.truetype(font, 29), fill='#ffffff')
    draw.text((60, 295), 'Generated test content · assisted check', font=ImageFont.truetype(font, 20), fill='#abb8ca')
    image.save(root / 'telegram-check.png')
    (root / 'telegram-check.txt').write_text('CointOS Telegram toolset\nGenerated test content.\nIdentity: ' + args.profile + '\n')

if args.send:
    photo = invoke('sendPhoto', {'photo': {'path': str(root / 'telegram-check.png')},
        'caption': 'Telegram toolset check — ' + args.profile + '. Generated test image; assisted verification.'})
    document = invoke('sendDocument', {'document': {'path': str(root / 'telegram-check.txt')},
        'caption': 'Generated test document — verifying upload and exact-byte download.'})
    receipts.update(photo=photo['message_id'], document=document['message_id'], file_id=document['document']['file_id'], sent_at=time.time())
    if args.profile == 'amateur':
        album = invoke('sendMediaGroup', {'media': [
            {'type': 'photo', 'media': {'path': str(root / 'telegram-check.png')}, 'caption': 'Album upload check — generated image 1'},
            {'type': 'photo', 'media': {'path': str(root / 'telegram-check.png')}, 'caption': 'Album upload check — generated image 2'}]})
        receipts['album'] = [item['message_id'] for item in album]
        poll = invoke('sendPoll', {'question': 'Telegram toolset check (no response needed)',
                                  'options': [{'text': 'Photo and document'}, {'text': 'Album and poll'}], 'is_anonymous': False})
        invoke('stopPoll', {'message_id': poll['message_id']})
        invoke('setMessageReaction', {'message_id': photo['message_id'], 'reaction': [{'type': 'emoji', 'emoji': '👍'}]})
        receipts['poll'] = poll['message_id']
    receipt_path.write_text(json.dumps(receipts, indent=2) + '\n')

if args.model:
    requested = {'id': int(time.time() * 1000), 'at': time.time(),
        'text': 'This is an authorized assisted Telegram tool check using generated test content. '
                'Send me the image at ' + str(root / 'telegram-check.png') + ' directly with telegram_sendPhoto. '
                'Use caption "Native Coin tool check — generated image". Then call done. No dispatch or other work is needed.'}
    coin.turn(token, user, chat, [requested], lambda: [], None)
    # Archive markers use native Bot API method spelling.
    delivered = [item for item in coin.recent(user) if item.get('role') == 'assistant' and 'sendPhoto' in item.get('content', '')]
    if not delivered:
        raise RuntimeError('Native model turn did not deliver an image')
    print(json.dumps({'at': time.time(), 'profile': args.profile, 'native_model_image': True}), flush=True)

if args.model_discovery:
    observed = []
    trace = []
    native_complete = coin.complete
    def observed_complete(*a, **kw):
        result = native_complete(*a, **kw)
        trace.append({'tools': [t['function']['name'] for t in kw.get('tools', [])],
                      'calls': [r['function'] for r in result.get('tool_calls', [])]})
        (root / 'discovery-trace.json').write_text(json.dumps(trace, indent=2) + '\n')
        return result
    coin.complete = observed_complete
    native_request = coin.coin_telegram.request
    def observed_request(token, method, parameters, timeout):
        result = native_request(token, method, parameters, timeout)
        observed.append({'method': method, 'ok': result.get('ok'),
                         'caption': result.get('result', {}).get('caption') if isinstance(result.get('result'), dict) else None})
        return result
    coin.coin_telegram.request = observed_request
    caption = 'Native discovery check — generated test image'
    requested = {'id': int(time.time() * 1000), 'at': time.time(),
        'text': 'Authorized assisted tool discovery check on generated test content only. '
                'Use telegram_tools to discover editMessageCaption, then use that tool to change caption of message '
                + str(receipts['photo']) + ' in this chat to "' + caption + '". '
                'Send one brief confirmation and call done. Do not dispatch other work.'}
    coin.turn(token, user, chat, [requested], lambda: [], None)
    (root / 'discovery-observations.json').write_text(json.dumps(observed, indent=2) + '\n')
    if not any(item['method'] == 'editMessageCaption' and item['ok'] and item['caption'] == caption for item in observed):
        raise RuntimeError('Native discovery turn did not perform the requested edit')
    print(json.dumps({'at': time.time(), 'profile': args.profile, 'native_discovery_edit': True}), flush=True)

if args.check:
    invoke('getMe', {})
    invoke('getChat', {})
    destination = root / ('download-' + str(time.time_ns()) + '.txt')
    invoke('download_file', {'file_id': receipts['file_id'], 'destination': str(destination)})
    expected = hashlib.sha256((root / 'telegram-check.txt').read_bytes()).hexdigest()
    actual = hashlib.sha256(destination.read_bytes()).hexdigest()
    if actual != expected:
        raise RuntimeError('Document bytes changed')
    print(json.dumps({'at': time.time(), 'profile': args.profile, 'download_sha256_matches': True,
                      'seconds_since_send': round(time.time() - receipts['sent_at'], 1)}), flush=True)
