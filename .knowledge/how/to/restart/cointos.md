---
status: green
revised_at: "2026-10-05T22:12:59+11:00"
---

Use the least disruptive level that can apply the change:

1. **Live settings:** `scheduler.slice_seconds` and `scheduler.chunk_tokens` reload without process replacement.
2. **Compatible daemon replacement:** `cointos restart` drains spawn admission and active request/landing boundaries, then replaces only cointosd while preserving Coin, agent units, sessions and models.
3. **Compatible live installation:** `scripts/install --live` copies compatible code/config and replaces only cointosd at once around surviving processes, cutting replies in progress (`how/to/install/cointos.md`).
4. **Full restart:** paused installation, halt/up or reboot is reserved for gateway/model-process identity, model shape or other incompatible changes.

## Daemon restart

`cointos restart` closes new-run spawning but continues admitting thoughts, landing validations and receipts from existing conversations until the daemon reaches a quiet boundary. `cancel-restart` reopens spawning without changing pause state. Actual daemon shutdown sets `STOPPING`; only then may a newly arriving thought receive a retryable rejection. Timeout or Ctrl-C cancels without stopping processes.

Stopping cointosd directly is safe for conversations: shutdown lets the GPU step in flight end, saves each lane's state, and cuts the replies; OpenCode keeps a cut reply's partial output as a finished step and continues, and the next daemon resumes from the saved state (`how/to/install/cointos.md`). Requests arriving while it is down get refused and retried with OpenCode's backoff ([retry policy](https://raw.githubusercontent.com/anomalyco/opencode/v1.18.33/packages/opencode/src/session/retry.ts)); after the 2-second replacement in a live installation, a cut agent was back within about 30 seconds with its whole context restored.

The replacement daemon adopts a run only when its persisted key/task identity and transient systemd unit are both live. A keyed run whose unit died returns to waiting uncharged. Adoption follows the existing unit and injects no message. Unknown units are stopped. Coin, agents and models keep running across replacement; Coin retains its imported code and startup settings, and changes to those require the separate quiet Coin refresh owned by `how/to/install/cointos.md`.

## Emergency containment

For a Telegram alert flood or an abandoned thought that prevents drain, stop Coin first (`systemctl --user stop cointos-coin.service`), pause and requeue agents with `cointos stop`, then stop `cointosd.service` if the detached request remains. This clears in-memory gateway requests without unloading the shared models. It is an emergency shutdown, not a substitute for the ordinary drain handshake. Repair and verify the gateway while paused before starting Coin or releasing autonomous work.

## Full shutdown and reboot

Full machine shutdown orders cointosd before transient agent units. cointosd independently attempts lane-context saving, RAM-snapshot spill to the disk tier and final ledger saving, so one failed obligation does not suppress the others. Persistent services carry explicit runtime, user-local and system PATH.

At startup, caches whose conversations are unreachable are removed after run adoption. Interrupted transfer copies are discarded because their copying threads did not survive; completed disk/RAM states remain reusable. This can cause cold rereading, never loss of the durable conversation or branch.

A reboot destroys RAM snapshots and agent units. Startup may restore compatible disk snapshots and requeue dead runs, but warm reuse and uncharged dead-unit recovery after the current second-pass fixes still require the next explicitly authorized reboot. Never reboot merely to run that check.

## Resumed sessions

OpenCode 1.18.33 has no verified empty noninteractive session-resume invocation. A relaunched interruption under three hours therefore receives the real user turn `Continue.`; a longer gap receives one concise reorientation. OpenCode persists that turn in context. This handoff occurs only when a run is relaunched; daemon adoption and compatible live installation inject nothing.
