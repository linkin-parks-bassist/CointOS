---
status: green
revised_at: "2026-10-02T04:48:44+10:00"
---

Use the least disruptive level that can apply the change:

1. **Live settings:** `scheduler.slice_seconds` and `scheduler.chunk_tokens` reload without process replacement.
2. **Compatible daemon replacement:** `cointos restart` drains spawn admission and active request/landing boundaries, then replaces only cointosd while preserving Coin, agent units, sessions and models.
3. **Compatible live installation:** `scripts/install --live` quiesces new thoughts, copies compatible code/config and replaces only cointosd around surviving processes.
4. **Full restart:** paused installation, halt/up or reboot is reserved for gateway/model-process identity, model shape or other incompatible changes.

## Daemon restart

`cointos restart` closes new-run spawning but continues admitting thoughts, landing validations and receipts from existing conversations until the daemon reaches a quiet boundary. `cancel-restart` reopens spawning without changing pause state. Actual daemon shutdown sets `STOPPING`; only then may a newly arriving thought receive a retryable rejection. Timeout or Ctrl-C cancels without stopping processes.

Do not substitute `systemctl restart cointosd`: it bypasses the readiness handshake and can truncate streams.

The replacement daemon adopts a run only when its persisted key/task identity and transient systemd unit are both live. A keyed run whose unit died returns to waiting uncharged. Adoption follows the existing unit and injects no message. Unknown units are stopped.

## Live installation

`scripts/install --live` uses stronger deployment quiescence: admitted thoughts finish and new model requests wait at the gateway admission gate, outside the active-request count. Cancellation admits them; disconnect removes them; shutdown returns a retryable refusal. This avoids repeated 503 responses spending the finite retries and increasing delays in [OpenCode 1.18.33's retry policy](https://raw.githubusercontent.com/anomalyco/opencode/v1.18.33/packages/opencode/src/session/retry.ts). Before contact it compares the candidate with the installed gateway/backend/model process-identity projection. Daemon-policy changes such as reasoning, recovery, scheduling and spawning are compatible; endpoint, backend and loaded-model topology changes are refused.

At the quiet boundary it stops only cointosd, copies/upgrades the installed runtime, reloads units and starts cointosd to adopt survivors. Coin, agents and models keep running. Coin retains its imported code and startup settings; changes to those require the separate quiet Coin refresh owned by `how/to/install/cointos.md`. The default wait is 60 seconds, bounded by the daemon command timeout; `--wait-seconds` changes it. Timeout cancels quiescence before copying or stopping anything. If a later step fails after cointosd stops, process-exit cleanup restarts it.

Live evidence establishes exact agent/session adoption without relaunch or new continuation turns. The timeout/cancellation path also leaves processes untouched. `what/is/the/live/acceptance/evidence/for/cointos.md` owns that boundary.

## Emergency containment

For a Telegram alert flood or an abandoned thought that prevents drain, stop Coin first (`systemctl --user stop cointos-coin.service`), pause and requeue agents with `cointos stop`, then stop `cointosd.service` if the detached request remains. This clears in-memory gateway requests without unloading the shared models. It is an emergency shutdown, not a substitute for the ordinary drain handshake. Repair and verify the gateway while paused before starting Coin or releasing autonomous work.

## Full shutdown and reboot

Full machine shutdown orders cointosd before transient agent units. cointosd independently attempts lane-context saving, RAM-snapshot spill to the disk tier and final ledger saving, so one failed obligation does not suppress the others. Persistent services carry explicit runtime, user-local and system PATH.

At startup, caches whose conversations are unreachable are removed after run adoption. Interrupted transfer copies are discarded because their copying threads did not survive; completed disk/RAM states remain reusable. This can cause cold rereading, never loss of the durable conversation or branch.

A reboot destroys RAM snapshots and agent units. Startup may restore compatible disk snapshots and requeue dead runs, but warm reuse and uncharged dead-unit recovery after the current second-pass fixes still require the next explicitly authorized reboot. Never reboot merely to run that check.

## Resumed sessions

OpenCode 1.18.33 has no verified empty noninteractive session-resume invocation. A relaunched interruption under three hours therefore receives the real user turn `Continue.`; a longer gap receives one concise reorientation. OpenCode persists that turn in context. This handoff occurs only when a run is relaunched; daemon adoption and compatible live installation inject nothing.
