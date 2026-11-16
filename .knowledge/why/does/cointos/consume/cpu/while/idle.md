---
status: green
revised_at: "2026-11-15T01:31:31+11:00"
---

Idle CPU use can come from live dashboard/viewer telemetry independently of inference or scheduled jobs. A single installed `cointos.cli view 0` process had retained thirteen concurrent live-update connections; the daemon used approximately 45–50% of one CPU core during interval samples. This establishes unnecessary idle telemetry work, not the cause of the earlier audible fan surges.

`coin_mirror.show` now owns its follower thread for exactly the mirror window's lifetime. Teardown signals the follower, which closes its state generator and therefore its HTTP response; teardown joins it using the existing API timeout. Normal streaming delivery, window display and Coin execution remain unchanged. The previous implementation never stopped that reader, so reopening viewer windows accumulated subscriptions. The regression test repeatedly closes windows and requires each subscription to close; it failed before the change.

The corrected client module is installed atomically under repair/install ownership. Closing the old idle viewer with SIGINT released its retained subscriptions without restarting the daemon, Coin or the model server. One Firefox dashboard subscription remained. Subsequent ten-second full-process intervals measured roughly 18–20% of one core, versus 45–50% before cleanup. Persistent-thread samples total only about 8%; those miss short-lived HTTP snapshot handlers and must not be reported as whole-process CPU use. Remaining dashboard/tick work is not evidence of a Coin job. No Coin conversation/log files were inspected, and cooling settings were untouched.

Each `gateway.Handler.live` subscription still independently calls `memory.measure` and serializes a frame at `dashboard.live_hz` (10 Hz). Physical-memory topology scanning and full-snapshot polling remain possible optimization targets; changes need their own evidence and must preserve fresh memory/pressure readings and visible updates. Removing the leaked consumers avoids multiplying this work.

Activation and CPU samples are retained outside knowledge under `~/.local/share/cointos/deployments/idle-viewer-20261115/`. Twenty-eight focused source checks and the same installed-module replay pass. These qualify the viewer cleanup, not all CointOS behavior or fan acoustics.

Proof:

```bash
python3 -m unittest tests.test_coin_mirror.ViewerLifetime -q
```
