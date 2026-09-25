---
status: green
revised_at: "2026-09-26T02:59:21+10:00"
---

During survivor retry for incident `20260925T162248Z-0`, Lemonade journal showed two competing `/v1/load` requests for the same Qwen3.5 emergency model: resource guard requested pinned `ctx_size=65536`, `--parallel 2`, while another native caller requested unpinned `ctx_size=32768`, `--parallel 1` seconds later. The observed health profile was repeatedly the latter. Guard correctly rejected it as not satisfying the emergency allocation, but retried immediately, causing unload/reload churn.

The competing caller was the long-running `agent-notifier.service` presenting a pending notification. Its native inference used `ecosystem/managed_inference.py`, whose automatic unloaded-model realization ran before worker acquisition checked the draining gate. Thus a native request could reload an emergency model despite later admission refusal. The installed repair checks `resource_control.mode()` at the start of the native retry loop and waits without routing/realizing while mode is `pressure` or `emergency`. The notifier was restarted on that generation; the Telegram gateway was also stopped during diagnosis and has not yet been restarted. The guard's emergency loader now polls health for up to 30 seconds after a successful load response, addressing a separate readiness gap. Focused managed-inference, operator-inference and resource-control tests passed.

After the notifier restart, the guard observed the configured pinned Qwen3.5 `ctx_size=65536`, `--parallel 2` profile, activated successor Sole Survivor `task-9611a7c42b41120a`, and cleared its emergency error. The successor is running and has begun tool work; recovery is not yet complete. Keep ordinary dispatch closed until its conclusion and health checks pass. Restart the Telegram gateway only on the installed gated generation and verify it cannot reload a wrong emergency profile.
