# Remaining planned ecosystem architecture

This is the intended attack order. Every prerequisite precedes the items that depend
on it. Where currently available items are independent, the smaller estimated bounded
implementation comes first. Re-evaluate the order only when implementation evidence
changes a dependency or the relative size of the remaining work.

Every item includes focused verification. The dedicated testing item below establishes
shared test infrastructure rather than deferring tests for later features.

1. Add Innovator and Speculator roles with distinct proposal-only and observation-only
   authority.
2. Make model-generated names broader, stranger, and task-sensitive, with repetition
   and blandness checks over recent identities.
3. Replace the remaining class-based tests with function-style tests.
4. Establish a versioned plain-data domain core for jobs, identities, messages,
   approvals, model leases, triggers, and events, with one explicit transition
   authority.
5. Put persistence behind repositories with atomic compare-and-set operations,
   indexes, format migrations, and authoritative lifecycle/query projections.
6. Establish narrow ports separating domain policy from the filesystem, Telegram,
   Lemonade, OpenCode, systemd, clocks, schedulers, and host telemetry.
7. Route typed commands into explicit state transitions and emit typed events and
   views so state changes and presentation do not depend on model prose or
   transport-specific records.
8. Add completion contracts that validate declared artifacts and acceptance checks
   in addition to independent semantic verification.
9. Add a typed approval broker with expiring or stronger confirmation for
   consequential actions.
10. Add a shared live roster that distinguishes processes, resumable logical agents,
    queued work, completed work, and historical records.
11. Add state watchers, scheduled reminders, and explicit event routing beyond the
    existing inbox and watchdog triggers.
12. Establish reusable crash, replay, state-machine, service-level, and architecture-
    dependency test infrastructure for subsequent work.
13. Mechanically enforce per-run wall-time, attempt, item, output, and concurrency
    budgets, with bounded partial handoffs and visible overruns.
14. Implement fair time-sharing among multiple resumable logical sessions without
    weakening the existing resource and emergency controls.
15. Add a durable transport-independent inter-agent message bus with exact live-run
    addressing, publish-time recipient resolution, idempotent per-recipient delivery,
    observed acknowledgements, and causal audit links.
16. Add role-wide announcements, global broadcasts, and a control-plane address with
    explicit retention and fan-out bounds.
17. Present real roster, message, queue, and transition facts through
    Cointelprofessional, including each agent's age and role on first mention.
18. Deliver messages to live-run inboxes at the earliest safe execution boundary,
    queuing them honestly where an adapter cannot interrupt an in-flight request.
19. Add authorized urgent status, wrap-up, and cancellation messages with cooperative
    interruption, durable checkpointing, and truthful lifecycle recovery.
20. Add bounded automatic retries and repair loops with deduplication, approval
    checks, operator controls, and independent re-verification.
21. Add one idempotent drain, reboot, and startup-health workflow that stops intake
    in a defined order, checkpoints work, reconciles interrupted state, flushes
    writes, and reports whether shutdown is safe, still draining, or blocked.
22. Strengthen executor isolation and destructive-action enforcement beyond the
    current best-effort shell policy.
23. Add voice-note and small-attachment intake through the constrained remote
    interface.
24. Add per-project isolated workspaces or containers with explicit mounts,
    resources, credentials, and device capabilities.
25. Add durable multi-worker execution behind measured resource admission and
    explicit model or device leases.
26. Add a constrained Vivado/JTAG hardware broker and Hardware Operator role with
    target leases, typed read and mutation operations, approvals, evidence capture,
    recovery procedures, and disconnect handling.
27. Complete reproducible bootstrap, backup, restore, and migration manifests
    covering packages, services, models, configuration, device rules, secrets
    recreation, and validation.
