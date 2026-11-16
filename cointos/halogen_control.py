"""CointOS bounded token control, loaded by the pinned Halogen API frontend.

All conversation data is volatile. Attention KV stays in the engine pool; its
retained cache copies recurrent state. No checkpoint or request recording is used.
"""
import asyncio
import secrets
import sys
import time


def render(api, tok, body):
    """Render a conversation whose message text stays text.

    Chat markers written inside messages or tool output (a file quoting
    `<|im_end|>`, an engine error naming `<|image_pad|>`) must not become control
    tokens: the engine refuses an uncovered image pad, and a forged turn marker
    rewrites the conversation. The pinned frontend's own chat path shields them;
    this applies the same shielding, tokenization and pad textification.
    """
    kw = dict(body.get('chat_template_kwargs') or {})
    if body.get('tools'):
        kw['tools'] = body['tools']
    continuation = body.get('continue_final_message', False)
    prompt = tok.apply_chat_template(api.shield_messages(body['messages']), tokenize=False,
        add_generation_prompt=body.get('add_generation_prompt', not continuation),
        continue_final_message=continuation, **api.shield_kwargs(kw))
    tokens, _ = api.tokenize_offsets(tok, prompt)
    tokens = api.textify_pad_mentions(list(tokens))[0]
    if api._UNMARK_RE is not None:
        prompt = api._UNMARK_RE.sub(lambda m: api._UNMARK[m.group(0)], prompt)
    return {'prompt': prompt, 'tokens': tokens}


def install(app, tok, engine):
    # The pinned frontend runs as __main__ and calls install() after
    # client_markers_setup(); its helpers own marker shielding for this tokenizer.
    api = sys.modules['__main__']
    if not all(hasattr(api, name) for name in
               ('shield_messages', 'shield_kwargs', 'tokenize_offsets', 'textify_pad_mentions')):
        raise RuntimeError('Pinned Halogen frontend lacks client-marker shielding')
    from fastapi import Request  # present only inside the pinned frontend image
    owners = {}
    active = {}
    gate = asyncio.Lock()
    epoch = secrets.token_hex(16)

    @app.post('/cointos/control')
    async def control(request: Request):
        body = await request.json()
        op = body['op']
        async with gate:
            try:
                if op == 'info':
                    await engine._ensure()
                    return {'result': {'protocol': 1, 'epoch': epoch,
                        'version': engine.info.get('version'), 'context': engine.info['ctx'],
                        'resident_state_bytes': max(1, engine.info.get('cache_mb', 58)) * 1024**2,
                        'owners': list(owners), 'experimental_cache_switch': True}}
                if op == 'render':
                    return {'result': render(api, tok, body)}
                if op == 'select':
                    owner = body['owner']
                    active[body['lane']] = owner
                    state = owners.setdefault(owner, {'tokens': [], 'handle': None})
                    return {'result': {'tokens': state['tokens']}}
                if op == 'release_residents':
                    for owner in body['owners']:
                        state = owners.pop(owner, None)
                        if state and state.get('handle'):
                            await engine.release(state['handle'])
                    return {'result': {}}
                if op not in ('prefill', 'think'):
                    raise ValueError('unsupported control operation')
                state = owners[active[body['lane']]]
                ids = body['tokens']
                held = body.get('held', 0)
                if held and (len(state['tokens']) < held or state['tokens'][:held] != ids[:held]):
                    return {'error': 'lost: retained token history changed'}
                sampling = body.get('sampling') or {}
                temp = sampling.get('temperature', 0)
                sample = (temp, sampling.get('top_k', 20), sampling.get('top_p', .95),
                          sampling.get('min_p', 0), sampling.get('seed', secrets.randbits(31))) if temp > 0 else None
                penalty = ''
                pp, fp = sampling.get('presence_penalty', 0), sampling.get('frequency_penalty', 0)
                if pp or fp:
                    penalty += f' PENALTY {pp} {fp}'
                rp = sampling.get('repeat_penalty', sampling.get('repetition_penalty', 1))
                if rp != 1:
                    penalty += f' REPEAT {rp}'
                progress = asyncio.Queue()
                ctl = {}
                lost = False
                cache_seen = None
                old_handle = state.get('handle')
                next_handle = secrets.randbits(62) + 1 if op == 'think' else None
                released = False
                async def watch():
                    nonlocal lost, cache_seen, released
                    while True:
                        event = await progress.get()
                        cache_seen = event['cache']
                        # A retained-cache miss may replay a bounded tail. Do not
                        # discard a 44k prefix merely because its latest 64 tokens
                        # were not pinned by the engine's kept-state budget.
                        if len(ids) - event['cache'] > body['max_input_tokens']:
                            lost = True
                            ctl['stop'] = True
                            if 'req' in ctl and engine.w is not None:
                                engine.w.write(f"X {ctl['req']}\n".encode())
                                await engine.w.drain()
                        elif old_handle and not released:
                            # The request now owns the active KV region. Retire its
                            # previous pin before committing the replacement tail.
                            await engine.release(old_handle)
                            released = True
                await engine.slots.acquire()
                watcher = asyncio.create_task(watch())
                new, done = [], None
                started = time.monotonic()
                try:
                    async for tid, result, lp in engine.generate(ids,
                            body.get('max_new', 0), sorted({tok.eos_token_id, tok.convert_tokens_to_ids('<|im_end|>')}),
                            drafter=1, sample=sample, penalty=penalty,
                            keep=next_handle, keep_end=(op == 'think'),
                            progress=progress, ctl=ctl):
                        if tid is not None:
                            new.append(tid)
                        if result is not None:
                            done = result
                finally:
                    watcher.cancel()
                    await asyncio.gather(watcher, return_exceptions=True)
                    engine.slots.release()
                    if old_handle and not released:
                        await engine.release(old_handle)
                    state['handle'] = next_handle if done and done.get('kept', 0) else None
                if lost:
                    state['tokens'] = []
                    return {'error': f'lost: engine retained {cache_seen} of {held} prefix tokens'}
                if done is None or done.get('reason') not in ('length', 'eos', 'stop'):
                    state['tokens'] = []
                    raise RuntimeError(f'incomplete native step: {done}')
                if op == 'prefill':
                    new = []  # GEN 0 computes logits and returns their argmax, without a decode tick.
                state['tokens'] = ids + new
                return {'result': {'tokens': new, 'held': len(state['tokens']),
                    'done': done['reason'] != 'length',
                    'generation_seconds': done['decode_ms'] / 1000,
                    'prefill_seconds': done['prefill_ms'] / 1000,
                    'prefill_tokens': max(0, len(ids) - (cache_seen or 0)),
                    'cache_tokens': cache_seen or 0,
                    'kept_tokens': done.get('kept', 0),
                    'call_seconds': time.monotonic() - started}}
            except Exception as error:
                return {'error': f'{type(error).__name__}: {error}'}
