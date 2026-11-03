---
status: green
revised_at: "2026-11-04T08:13:04+11:00"
---

Each open dashboard fetches the whole /api/ledger once a second. The ledger is about 13.4 MB of JSON, roughly 11 MB of it settled task history (about 1,420 tasks). Every fetch deep-copies the ledger under LOCK (about 30 ms), JSON-encodes it (about 90 ms) and gzips it at level 1 in the request thread, all GIL-bound Python. With three dashboard streams this costs close to a full core of GIL time per second, so ordinary API calls on other threads slow down. A 60-second probe with three dashboards open measured inbox calls at median 0.62 s, p95 1.7 s, versus about 142 ms in the earlier cleanup qualification. Rare spikes can still pass client.py's 10-second api_seconds timeout.

memory.measure (about 2 ms) and the per-tick process/window scans are minor in a py-spy sample and are not the cause. Per-poll GGUF re-parsing in /api/models used to dominate (60% of daemon samples). models.metadata now parses each file once per identity; how/to/change/the/cointos/default/model.md owns that.

Proposed fix, awaiting the user's decision: send settled tasks to the dashboard once or when they change, instead of shipping the full ledger every second. This changes the /api/ledger contract and web/dashboard.html. Until then, closing unused dashboard tabs reduces the load roughly in proportion. Inbox waits already retry unreachable polls until their deadline (how/do/cointos/agents/use/cointos/tools/and/messages.md).

Blocker: User decision on changing the /api/ledger dashboard contract

Next check: 2026-11-11
