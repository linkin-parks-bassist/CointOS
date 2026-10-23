---
status: green
revised_at: "2026-10-18T22:33:50+11:00"
---

Use the least disruptive level that can apply the change:

1. `scheduler.slice_seconds` and `scheduler.chunk_tokens` reload live.
2. `cointos restart` drains admission/request/landing boundaries and replaces only cointosd, retaining Coin, units, sessions and models.
3. `scripts/install --live` deploys compatible changes around surviving processes, cutting replies when daemon replacement is required. The installation procedure owns compatibility and authority preflight.
4. Paused full installation, halt/up or reboot applies incompatible gateway/model identity or shape changes. The qualified Gufo backend-only migration has a separate stopped-daemon procedure in what/is/the/gufo/backend/candidate/for/cointos.md; it preserves frozen clients while invalidating incompatible native caches.

## Daemon restart

`restart` stops new-run spawning while existing conversations can send thoughts, landings and receipts until quiet. `cancel-restart` reopens spawning without changing pause state. Actual shutdown sets STOPPING; only then may new thoughts receive retryable refusal. Timeout/Ctrl-C cancels without stopping processes.

Stopping cointosd saves lane state and cuts replies. OpenCode retains partial output. Nonempty consecutive assistants require explicit continuation; empty final assistants require the coupled adapter/native generation-opening fix. Native probes and managed continuations establish narrower behavior than sustained recovery. Prefer quiet drain when practical; acceptance owns outcomes.

Startup requires regular, non-symlink authority JSON, rejecting corruption, duplicate fields, unreadability and invalid retained ledger containers before mutation/adoption/save. Only absence initializes defaults. Preserve refused files for inspection/repair rather than deleting them to force startup. A managed Operator requires the daemon/gateway. Fatal Python exceptions exit 2 and trigger independent remote Codex through `cointos-repair.service`. It retains incident/thread evidence and checks native/API health, authority, sessions, enrollment and explicit holds. Native retries have no inherited start cap. Installation shares repair ownership; native repair waits through replacement. Acceptance owns deployment status and validation limits.

Valid startup settles published verified intents before adoption/budgets. Adoption requires persisted exact task/current-receipt ownership and an active unit, injects nothing and stops unknown units. Dead keyed units requeue uncharged. Coin/agents/models survive compatible replacement. Gufo requires an independent systemd user scope; a new session still inherits daemon cgroup cleanup. Verify native PID survival. Coin retains imports/startup settings; refresh it separately only when quiet.

## Emergency containment

For a detached thought preventing drain, stop Coin first, then pause/requeue with `cointos stop`, then stop cointosd if necessary. This clears gateway requests without unloading models. Warm restored native state and settle host PSI/headroom before daemon adoption. Repair/verify while paused before starting Coin or releasing autonomy; it does not replace ordinary drain.

## Shutdown, reboot and resumed sessions

Machine shutdown orders cointosd before agent units. Context saving, RAM-to-disk spill and ledger saving are attempted independently. Services carry runtime/user-local/system PATH.

Startup removes unreachable conversation caches after adoption and discards interrupted transfers. Completed compatible states remain reusable; missing caches reread without deleting conversations/branches. Reboot destroys RAM snapshots/units. Disk reuse and uncharged recovery still require the next authorized reboot; never reboot merely to test them.

New units reuse unfinished short-gap turns, use Continue for completed replies and reorient longer gaps. Surviving servers keep captured configuration. Patched fixtures preserve metadata/tools/events; natural acceptance remains open. Pending compaction finishes through native summarize with auto:false; failure withholds continuation.
