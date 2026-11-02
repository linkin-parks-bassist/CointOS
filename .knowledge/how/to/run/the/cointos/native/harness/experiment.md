---
status: green
revised_at: "2026-10-25T22:33:13+11:00"
---

The disposable prototype is experiments/native_runner/runner.py, with focused fault-injection checks in experiments/native_runner/test_runner.py. It is experimental apparatus, not a deployed harness or replacement for OpenCode/Coin.

Run offline checks from the repository root:

```bash
python3 -m pytest -q experiments/native_runner/test_runner.py
```

Start a fresh live session with an absent/private directory:

```bash
python3 experiments/native_runner/runner.py /tmp/cointos-native-example --request-class user --prompt 'Create answer.txt containing 42 followed by a newline, read it back and report its actual contents.'
```

Resume with the same directory and no --prompt. Default endpoint is http://127.0.0.1:4200/v1, model default. Background priority is the default and can wait behind active agents; --request-class user uses ordinary user priority. Use only one live experiment at a time: the gateway maps unissued keys to its shared user conversation/cache identity. Never borrow Coin or agent keys. The experiment issues no credentials and changes no daemon enrollment or services.

SQLite commits state and sequenced events together with synchronous=FULL; an exclusive process lock holds the session. A separate first model request has no tools and must produce acknowledgement text before work is admitted. The CLI emits that durable acknowledgement at its boundary. This guarantees ordering, not fast inference or semantic quality. The initial live acknowledgement unnecessarily mentioned another go-ahead; its instruction now explicitly says the request is authorised. A second live probe confirmed a direct starting acknowledgement without another permission request.

Work exposes only read_file/write_file for flat non-symlink files under the session workspace, capped at 16 KiB. There is no shell or MCP. Files publish atomically with fsync. This is a narrow tool surface, not hostile-process/kernel confinement. A recorded assistant tool batch resumes without re-inference; persisted results are not repeated. A crash after tool-start but before durable result leaves an ambiguous outcome and refuses automatic replay. No manual reconciliation interface exists yet. Completed sessions make no further model requests. Eight durable work-request attempts and eight calls per batch bound work; each live reply defaults to 768 tokens and a 180-second HTTP timeout. Acknowledgement requests are separate and may be retried after failed requests. Delivery is stdout/journal only; it has no recipient acknowledgement or exactly-once remote delivery.

Fifteen checks cover ordering, real process death after acknowledgement/model record/tool start/effect/result, competing ownership, path/symlink refusal, retained work limits and exclusion of model reasoning from event storage. These establish fixture mechanisms, not production acceptance. The first live probe produced and read back exactly 29 bytes in greeting.txt; host verification checked bytes and terminal state. Acknowledgement took 15.4 seconds and full turn 68.1 seconds at user priority. Its initial background request did not reach acknowledgement before cancellation while production agents were active. Evidence: /tmp/cointos-native-runner-20261025-a/session.sqlite3 and workspace/greeting.txt. The second live probe wrote/read exactly three bytes (42 plus newline) with acknowledgement at 11.0 seconds and completion at 36.5 seconds. Evidence: /tmp/cointos-native-runner-20261025-b/session.sqlite3 and workspace/answer.txt; host verification checked bytes and terminal state. These are short smoke probes, not a throughput comparison.

Unimplemented: production task binding, checked completion receipts, kernel confinement, MCP, streaming/cancellation protocol, context compaction, remote client and safe resolution of ambiguous effects.
