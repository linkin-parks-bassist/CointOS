---
status: green
revised_at: "2026-10-01T23:46:26+10:00"
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
- `/completion` prepares explicit token prefixes with streamed prompt-progress reports, then generates a bounded complete token vector with `cache_prompt` and `n_predict`.
- `/slots/N?action=save|restore|erase` moves a slot state to or from the configured snapshot directory.

A completion request is a bounded GPU step. `backend_llama.prefill` streams prompt progress, rejects an error or missing terminal event, and verifies the final cached token count. The first progress report reveals how much state the server retained; materially lost state raises `Lost` before an unbounded reread. `think` verifies cache retention by extending the prepared prefix with its pending real token, then requests a non-streaming, token-only bounded completion and checks terminal status, complete token count and cached-state length. Both calls use the configured server timeout. The generation duration is measured after prefix preparation and returned separately, so this extra cache verification does not spend an agent's generation budget.

The installed llama-server build is `b10723-010be9683`. Its text stream suppresses tokens inside incomplete UTF-8 characters, and even native completions pass isolated output through a chat parser that rejects leading continuation bytes. Token steps therefore supply a no-op epsilon `chat_parser` and restrict response fields to token/state metadata. This is a raw-token boundary: Qwen message/tool interpretation remains in `backend_llama.read` over the whole thought. Trailing detokenizer replacement characters are withheld during outward streaming until the character is complete. A real work-model test split 🦦 into `[9008, 99, 99]` and preserved all three IDs across one-token steps. A zero-token, nonterminal generation result is rejected; the lane clears unknown state and ends that thought rather than replaying it.

The configured Qwen models are hybrid recurrent/attention models. A saved state is reusable only when its tokens are a prefix of the next prompt. Prompt preparation stops one token short. Cache verification then submits the full real prompt, extending the retained prefix by that pending token. An equal-length check after restoring recurrent state would require an unavailable earlier checkpoint and discard the cache; the strict extension creates the checkpoint needed for the following buffered generation to reevaluate its last token without a full reread. After generation, the backend derives the exact known retained prefix from `tokens_cached` and the complete prompt/output token vector; the lane never fabricates this prefix from output count. MTP may retain draft tokens beyond a finished reply: an unreturned tail is marked cold while the valid complete reply is delivered. A connection cut mid-generation can leave an unseen token in server state, so an abandoned in-flight thought resumes from its committed checkpoint rather than assuming the cut state is exact.

## Active model policy

`config/cointos.json` is authoritative for model names, context, lanes, arguments and admission estimates. The current work model is Qwen3.8-27B with one 131,072-token lane and MTP speculative decoding; the front model is Qwen3.5-4B with two 32,768-token lanes, one reserved for Coin. Lane count and total context are load-time model shape: changing either requires a model reload and is incompatible with live daemon-only installation.

CointOS retains Qwen3.8-27B as the minimum work model unless David chooses a different quality point. Published alternative quantizations and runtimes are leads, not evidence of equal agent quality or a drop-in speedup. Any comparison must hold weights/quality target, sampling, occupied context and task success constant, then verify the exact installed runtime. No alternative currently has that evidence.

## Reasoning and output

Qwen3.8 accepts low, medium and xhigh `reasoning_effort` through its chat template. CointOS pins task effort, maps it into template options, and mechanically caps each uninterrupted reasoning block at 256, 384 or 1,024 tokens respectively. At the cap it appends the model's closing-think token on the same context and continues into answer or tool output. `max_thought_tokens` still bounds the complete reply. This is a per-reply bound, not a lifetime penalty, and does not establish semantic correctness.

The template emits reasoning inside `<think>...</think>` and tool calls in its Qwen function-call markup; `backend_llama.read` is the sole decoder for that literal representation.

## Remaining evidence

Exact throughput varies with occupied context, simultaneous reads, model-server build and speculation acceptance. Current configuration has usable live performance, but no controlled local comparison proves the net benefit of MTP, a smaller maximum context, another quantization or another runtime. Those are performance experiments, not active operating claims; `what/is/the/plan.md` owns any future work that becomes approved.
