---
status: green
revised_at: "2026-09-26T00:37:45+10:00"
verifiable: "true"
---

The source `agent-executor@.service` declares exactly one `COINTOS_RUNTIME_ROOT=%h/.CointOS` environment assignment. Its expanded runtime root matches the CointOS paths default and is outside the source checkout. This is a source-template contract, not proof that a live systemd manager loaded that template.

Proof:

```bash
python3 -m unittest tests.test_user_service_runtime_root -q
```
