---
status: green
revised_at: "2026-10-19T23:21:57+11:00"
---

The dashboard uses relative /api/ledger, /api/live and control URLs against its page's server. A DDRiver reverse proxy displays DDRiver's runtime; the viewing device needs no local instance. Host access and layout retain separate owners.

Full snapshots clone nested state under the daemon lock, then encode, compress and send outside it. Slow sockets cannot retain that lock; concurrent mutation cannot change a captured reply. Installed capture reuses state._snapshot's JSON-container clone instead of generic deepcopy, preserving ordinary JSON response bytes and nested isolation.

On the same captured 8.18 MB ledger, alternating CPU trials measured median 46.43 ms for deepcopy versus 24.39 ms for the JSON helper. An isolated HTTP server with identical ledger/projection values returned byte-identical bodies: median 139.33 versus 120.11 ms across nine alternating trials per method. Forty-nine focused checks and 1,034 source tests pass, with three native-only skips. workflow-observation-20261019/{dashboard-copy-comparison.json,dashboard-copy-http-control.json,dashboard-copy-verified.json} bind qualification.

dashboard-copy-activation/recovery.json and dashboard-copy-live-summary.json retain compatible gateway activation and live verification. The controlled HTTP comparison supports reduced capture cost; unmatched production windows establish no generation speedup.

JSON/HTML replies negotiate gzip for bodies at least 1,024 bytes with explicit positive acceptance. gzip;q=0, malformed quality and identity clients remain uncompressed. Content-Length describes transmitted bytes; Vary names Accept-Encoding. Streaming chat/live events remain separate; their socket writes occur outside the lock.

Snapshot polling retries one second after completion with a 30-second fetch/body deadline. The header distinguishes request/network/HTTP/JSON/timeouts from display exceptions; details go to the console. HTTP 200 for HTML alone proves neither rendering nor stream delivery.

Earlier lock repairs remain installed: ordered persistence moves file I/O outside LOCK and rechecks landing authority; captured os.replace previously blocked responses for 13.19 seconds. Its JSON clone measured 82.00 to 28.43 ms. Periodic tree observation runs in a dedicated worker rather than daemon.tick under LOCK. Its 157-response observation had median 146.74 ms and maximum 261.02 ms, versus a preceding 3,128 ms maximum. Persistence and managed-tree owners retain those checks.

Two traced blocking paths required separate repairs. A 16.08-second API stall showed journal file I/O under LOCK, outside switch-event timing, while a spill ran in sendfile. Installed diagnostic staging/ordered flushing removes that path; its owner retains FIFO-blocked TCP/producer tests. A subsequent 238.58-second window still had three timeouts and an 8.64-second response, median 135.53 ms. Four stacks identified snapshots.keep/drop → backend forget/os.remove holding LOCK; I/O PSI some/full avg10 peaked at 86.34/84.94. These stacks identify causes, not all historical stalls. Installed independent RAM/disk cleanup removes ordinary unlink from LOCK and SSD disposal from the model worker. Qualification passes 117 focused source/installed and 1,061 full source checks. The 4.42-second activation preserves native/client identities and authority. Its ordinary 237.94-second follow-up has 120 successful API responses, median 142.49/max 244.97 ms, and observed physical retirement without cleanup errors. I/O PSI peaks at only 0.18; severe-pressure resilience remains open. Storage owns details. Evidence: workflow-observation-20261019/{journal-lock-stall.json,snapshot-unlink-lock-stall.json,snapshot-cleanup-live-summary.json}.

Tailscale HTTPS returned HTML, compressed snapshots and live events; an isolated Node DOM rendered a fetched snapshot. Neither proves a remote device's stream. The earlier blank view remains unreproduced.

Proof:

```bash
python3 -m unittest tests.test_dashboard_transport -q
```
