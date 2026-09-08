# Decision 0018: leases are owned only by living agents

Status: accepted, 2026-09-08.

A worker or inference lease represents current occupancy, not a historical claim
that requires a cause-specific release ceremony. The decisive reuse question is:
does the exact bound agent process still exist and have a live proxy request?

Once that process identity is independently observed ended and its proxy has no
in-flight request, its ownership ends. The slot may be reassigned regardless of
whether the run completed, timed out, crashed, was killed by OpenCode/Lemonade, or
ended for a cause not yet known to CointOS. A stale `starting`, failed close, or
unclassified death belonging to one lease must never block unrelated leases.

Completion tokens, exit causes, heartbeats, orphan-backend observations and revival
artifacts remain useful, but they are lifecycle and recovery evidence. They do not
extend ownership after the owner is gone. A heartbeat will later help detect a
wedged process that still exists; process identity is sufficient for a dead one.

Backend cancellation and telemetry may continue after ownership ends. The backend
remains authoritative for its instantaneous physical occupancy and may queue a new
request until hardware is actually free; CointOS must not reserve that capacity for
a dead consumer.
