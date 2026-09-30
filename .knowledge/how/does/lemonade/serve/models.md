---
status: green
revised_at: "2026-09-30T10:25:48+10:00"
---

Lemonade is the machine-level model service (`lemond.service`, user `lemonade`) shared by CointOS and other local clients. Its control API is `http://127.0.0.1:13305`; logs are in `journalctl -u lemond`. CointOS is a client, not its owner, and must tolerate another client reloading a model onto a different backend URL.

## Control contract

- `GET /api/v1/health` reports each model's loaded state, backend URL, effective launch command, recipe options, PID and pin state. CointOS refreshes this map during model checks.
- `POST /v1/load` accepts the model name, context size, complete llama.cpp argument string, merge/save flags and pin state. CointOS uses `merge_args: false` and `save_options: false`, so its operational config determines the active shape without rewriting Lemonade's saved recipe.
- `POST /v1/unload` unloads one named model; an absent model may answer 404.
- Model files under `/var/lib/lemonade` are not readable by David's account, so models are started through Lemonade rather than directly.

Lemonade and its llama-server children run in `inference.slice`. Snapshot files live in the configured `/dev/shm` directory and must be writable by the `lemonade` user. The backend checks both workstation headroom and the inference-slice allowance before admitting model or snapshot allocations.

## llama-server contract

The backend uses these model-server operations:

- `/apply-template`, `/tokenize` and `/detokenize` translate between structured conversation and tokens.
- Streaming `/completion` extends a specified slot with `cache_prompt`, explicit token input, bounded `n_predict` and prompt-progress reports.
- `/slots/N?action=save|restore|erase` moves a slot state to or from the configured snapshot directory.

A completion request is a bounded GPU step. Closing its HTTP connection is not a reliable instantaneous interrupt because llama-server may notice only when it next writes; CointOS therefore bounds reads and generation and switches between completed steps. The first prompt-progress report reveals how much state the server actually retained. If it retained materially less than CointOS recorded, the backend raises `Lost`, clears that lane's assumed state and resumes through ordinary bounded reads.

The configured Qwen models are hybrid recurrent/attention models. A saved state is reusable only when its tokens are a prefix of the next prompt. To generate without rereading the whole prompt, a prepared state stops one token short; after bounded generation the state holds the submitted context plus generated tokens except the last returned token. A connection cut mid-generation can leave an unseen token in server state, so an abandoned in-flight thought resumes from its committed checkpoint rather than assuming the cut state is exact.

## Active model policy

`config/cointos.json` is authoritative for model names, context, lanes, arguments and admission estimates. The current work model is Qwen3.8-27B with one 131,072-token lane and MTP speculative decoding; the front model is Qwen3.5-4B with two 32,768-token lanes, one reserved for Coin. Lane count and total context are load-time model shape: changing either requires a model reload and is incompatible with live daemon-only installation.

CointOS retains Qwen3.8-27B as the minimum work model unless David chooses a different quality point. Published alternative quantizations and runtimes are leads, not evidence of equal agent quality or a drop-in speedup. Any comparison must hold weights/quality target, sampling, occupied context and task success constant, then verify the exact installed runtime. No alternative currently has that evidence.

## Reasoning and output

Qwen3.8 accepts low, medium and xhigh `reasoning_effort` through its chat template. CointOS pins task effort, maps it into template options, and mechanically caps each uninterrupted reasoning block at 256, 384 or 1,024 tokens respectively. At the cap it appends the model's closing-think token on the same context and continues into answer or tool output. `max_thought_tokens` still bounds the complete reply. This is a per-reply bound, not a lifetime penalty, and does not establish semantic correctness.

The template emits reasoning inside `<think>...</think>` and tool calls in its Qwen function-call markup; `backend_llama.read` is the sole decoder for that literal representation.

## Remaining evidence

Exact throughput varies with occupied context, simultaneous reads, model-server build and speculation acceptance. Current configuration has usable live performance, but no controlled local comparison proves the net benefit of MTP, a smaller maximum context, another quantization or another runtime. Those are performance experiments, not active operating claims; `what/is/the/plan.md` owns any future work that becomes approved.
