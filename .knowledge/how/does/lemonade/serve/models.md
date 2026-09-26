---
status: green
revised_at: "2026-09-27T00:27:35+10:00"
---

Checked service properties on 2026-09-27 match the description below; token-resume timings and performance are retained earlier observations, not tests repeated during the tree refresh.

Lemonade is the local model server, a system service (`lemond.service`, running as user `lemonade`, logs in `journalctl -u lemond`) independent of CointOS. Its API is at `http://127.0.0.1:13305`.

- `GET /api/v1/health` lists `all_models_loaded`. Each entry includes `model_name`, `loaded`, `backend_url`, `launch_command` (the effective llama-server argv), `recipe_options` (`ctx_size`, `llamacpp_args`), `pid` and `pinned`.
- `POST /v1/load` takes `{"model_name", "ctx_size", "llamacpp_args", "merge_args", "pinned", "save_options"}`. Extra llama-server flags pass through `llamacpp_args`.
- `POST /v1/unload` takes `{"model_name"}`, and answers 404 when that model is not loaded.

**Lemonade is shared.** Any client can unload or reload a model, and a reload may use another port, so clients must refresh backend URLs from health. CointOS refreshes its backend URL map during model checks; it does not resolve a URL afresh for every token call.

**Files and sandbox.** Model files under `/var/lib/lemonade` are readable only by `lemonade`, so every llama-server must be started through Lemonade. The service has a private `/tmp` and `ProtectSystem=full`, but can write to `/dev/shm`; a snapshot directory there must be writable by `lemonade` (for example mode 0777).

**llama-server**, one per loaded model at its `backend_url`, offers what a pre-emptive scheduler needs (all checked on the Qwen3.5-4B and on Qwen3.8-27B with MTP speculation):
- `POST /apply-template` with `messages` and `tools` returns the rendered prompt; `POST /tokenize` with `parse_special: true` turns it into tokens; `POST /detokenize` turns tokens back into text.
- `POST /completion` with a token list as `prompt`, `id_slot`, `cache_prompt`, `n_predict`, `stream` and `return_tokens` extends a context on one slot and streams the new token ids.
- Closing the connection does not reliably stop the slot: llama-server notices only when it next writes to the client, so a long read runs on for up to minutes (seen 2.7 s once, over 60 s another time), and a slot action (save, restore) sent meanwhile is never served. So nothing should be cut: bound each request instead (`n_predict: 0` for reading, a small `n_predict` for generating).
- With `--slot-save-path DIR`, `POST /slots/N?action=save|restore` with `{"filename"}` saves or restores a slot's whole state. On the 27B, 12,288 tokens took 1.5 s to save (0.96 GB) and 0.16 s to restore. `action=erase` clears a slot.
- **The Qwen models are hybrid (recurrent plus attention) and cannot roll back.** A slot state can be continued only by a token list that extends it by at least one token. If the state holds as many tokens as the next prompt, or more, the whole prompt is read again: to generate, the model must evaluate the prompt's last token, which a state already holding it cannot do. So a read must stop one token short of the context it prepares (seen 2026-09-26: a lane holding all 19,183 tokens of its prompt re-read them all before its first generated token).
- **Where a context can be stopped and resumed exactly:**
  - After a completion that stopped at `n_predict`, the state holds every token sent except the last. Continuing with prompt plus all tokens received reads 1 token.
  - A connection cut during generation can leave a token in the state that was never sent, so it cannot be continued exactly.
  - A cut while the prompt is still being read leaves a state holding a whole number of batches, which the full prompt then extends: seen 12,288 of 39,049 tokens reused.
- Speeds on the 27B: reading about 170 tokens/s alone (about 95 when both slots read at once); writing 20–25 tokens/s alone with MTP.

**Output format.** The Qwen templates put reasoning between `<think>` and `</think>`, and tool calls as `<tool_call><function=NAME><parameter=P>value</parameter>...</function></tool_call>`, with parameter values as raw text.
