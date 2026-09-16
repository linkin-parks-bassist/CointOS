---
status: "unverified"
created_at: "2026-09-14T23:56:54+10:00"
scope: "local"
source: "ecosystem/telegram.py fast_response; control_agent.py deep_response; installed unit environment; actual active/exited model unit and resident27B observation"
---

telegram.fast_response uses AGENT_TELEGRAM_FIRST_RESPONSE_MODEL, default Qwen3.5-4B-GGUF; control_agent.deep_response uses AGENT_TELEGRAM_MODEL with the same default. Both pass selection through active_chat_model for current resource mode and default to automatic managed inference. Installed Telegram/control/notifier units explicitly select the small model. agent-models.service is a remain-after-exit oneshot; if it is active/exited but actual resident model was changed later, starting its dependent services will not rerun the model loader. Verify actual residency rather than oneshot status; missing small-model residency can leave control requests waiting. Reload the intended control model under authorized activation and measured capacity, preserving the work-model reference.
