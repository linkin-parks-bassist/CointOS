---
status: "green"
revised_at: "2026-09-26T10:51:25+10:00"
---

Lemonade is the local model server, a system service independent of CointOS. Its API is at `http://127.0.0.1:13305`.

- `GET /api/v1/health` lists `all_models_loaded`. Each entry includes `model_name`, `loaded`, `status`, `pinned`, `is_busy`, `backend_url`, `launch_command` (the effective llama-server argv), `recipe_options` (`ctx_size`, `llamacpp_args`), `pid`, `max_context_window`, `slot_pool` and `checkpoint`.
- `POST /v1/load` takes `{"model_name", "ctx_size", "llamacpp_args", "merge_args": true, "pinned", "save_options"}`.
- `POST /v1/unload` takes `{"model_name"}`.
- `GET /v1/models` lists the registry.

Each loaded model runs as its own llama-server process at its `backend_url`, a loopback port such as `http://127.0.0.1:8002`. That server exposes `/v1/chat/completions`, `/props` and `/slots`. llama-server accepts per-request `id_slot` (which lane to use) and `cache_prompt` (reuse that lane's KV prefix).

Loading or unloading takes seconds to minutes and occupies that model while it happens.
