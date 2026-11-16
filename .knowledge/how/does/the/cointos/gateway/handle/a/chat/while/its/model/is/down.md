---
status: green
revised_at: "2026-11-17T10:53:52+11:00"
---

A chat for a known model that is not up does not fail immediately. `Handler.stream_thought` in cointos/gateway.py holds the request on LOCK until the daemon's health loop (cointos/daemon.py) reports the model up again, then continues normally. The wait is bounded by `scheduler.model_wait_seconds` (300 in config/cointos.json). Each Halogen container recreation leaves the model down for about 165 s, so a restart fits inside the wait.

The wait ends early when:

- the daemon is stopping, which returns 503 "daemon restarting; retry shortly";
- a default-model change starts, which returns 503 "default model changing; retry shortly". Waiting chats count in ACTIVE["chats"], and the change drains them, so leaving early keeps the change from stalling;
- the client hangs up, which returns no reply.

If the model is still down at the deadline, the gateway returns 503 "<model> did not come up within N s", followed by the daemon's recorded problems. `scripts/install` copies the new scheduler key and keeps the installed `slice_seconds`/`chunk_tokens`.

Proof:

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_restart.py -k ModelOutage
```
