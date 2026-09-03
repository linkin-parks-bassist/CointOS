# HIGH PRIORITY: Make powerdown simple and safe

The ecosystem needs one obvious, idempotent command for preparing the machine to
restart, enter firmware setup, or power off. David should not need to understand
systemd units, job-state files, model processes, or stale outbox transitions.

The command should:

- atomically prevent new dispatch and inbound work;
- stop timers, path activation, Telegram intake, and active executors in a defined
  order;
- send each live agent a durable `wrap_up` message, wait a bounded interval for
  acknowledgment and checkpointing, then escalate to interruption;
- reconcile interrupted `running` and `sending` records truthfully, without claiming
  success or leaving work permanently orphaned;
- flush durable state and repository writes;
- distinguish queued/recoverable work from work that needs verification or repair;
- optionally unload models and stop Lemonade when useful, while remaining compatible
  with an ordinary OS-managed shutdown;
- print one concise, evidence-backed verdict: safe to reboot, still draining, or
  blocked with the exact remaining owner;
- preserve enabled-at-boot configuration and support the inverse startup health
  check after reboot.

Add tests for repeated invocation, interruption during each lifecycle phase, stale
state recovery, already-stopped services, unavailable Lemonade, and reboot while a
worker or outbox delivery is active. Keep the implementation functional and
data-oriented; OOP is forbidden.

This is an operational safety boundary, not a convenience shell pile. Define a
single lifecycle representation used by the CLI, watchdog, status reporting, and
systemd integration. The live messaging boundary is specified in
`agent_notes/0003-control-plane-presence-and-live-messaging.md`.

— Codex, 2026-09-03
