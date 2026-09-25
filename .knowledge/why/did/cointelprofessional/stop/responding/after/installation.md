---
status: green
revised_at: "2026-09-17T16:21:54+10:00"
---

Telegram turn `telegram-999135394` received message `h`; its fast response failed and its deep path entered more than 1,200 attempts, each raising `ValueError: invalid inference capacity policy` roughly twice per second. The installed configuration had moved physical reserve keys from `inference_capacity` to `physical_capacity`, while the long-running `agent-control-worker.service` process still held the previous Python module generation. The installed current loader validated the same configuration successfully, proving a mixed running-code/config generation rather than invalid current files.

Stopping only the control worker ended the CPU-burning loop while Telegram intake remained active. Restarting the full user CointOS service set from freshly installed assets stopped the policy errors and resumed the retained turn in a stable deep attempt.

The operational fix is one central generation boundary, installed as `scripts/cointos-system {start|stop|restart|status}`. Restart stops triggers, oneshots, and long-running units together, reloads systemd, then starts the complete long-running system plus triggers; if start fails it stops the whole set rather than leaving a partial mixed system. A remaining defect is that control-turn retry currently requeues immediately on every exception and needs backoff/incident state so configuration failures cannot hot-spin.
