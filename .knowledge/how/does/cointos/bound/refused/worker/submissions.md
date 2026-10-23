---
status: green
revised_at: "2026-10-16T01:50:08+11:00"
---

A clean committed construction worker gets three product-validation refusals with unchanged acceptance inputs. On the third, api.finishing records a blocked receipt and returns it to the terminal caller. The work frontier assigns one recovery controller; branch and failure evidence survive. CLI finish reports the actual disposition, even when complete was requested.

Persistent submission_failure stores attempts, validator error and inputs: candidate tree, accepted main, test refs, bundled commands, copied policy, stage and assignment version. This uses artifact/authority identity, never report-text parsing. Empty commits do not refill attempts; changed content/main/tests/policy/stage/version starts a new episode. Success clears failure. State reload preserves the episode.

Recording/escalation rechecks current run, version, stage, test refs, bundled commands, policy, clean worktree, submitted HEAD and accepted main. Revoked validation cannot block newer work. Accounting unwinds in finally. The original complete request can replay its automatic blocked receipt for the same run/account after a lost reply; foreign requests cannot.

This covers packet/stage failures after clean artifact admission. Dirty/no-artifact preflight and integrator landing refusals remain outside it. Source and installed runtime distinguish ExecutionError: timeouts, killed execution units and commands that did not complete are infrastructure evidence. submission_failure.category separates execution from product refusals; changing category starts a fresh count. Three unchanged execution failures produce a blocked infrastructure receipt for the recovery controller, never fabricated assertion evidence. A transient execution failure followed by a valid check can complete. Installed native fixtures pass.

The motivating native worker trace held 102 finish errors about protected Makefile changes while process checks stayed green. Some refusals predated this bound. A later 53-command review exposed the separate problem of exhausting a shared suite deadline; the reviewed packet succeeded on retry. Neither identical-thought checks nor interpreting infrastructure failure as product rejection solves those distinct causes.

Evidence: api.py, cli.py and real-Git tests.test_landing.Packets cover unchanged refusal, persistence, empty commits, changed inputs, lost replies, revoked ownership, successful repair and typed execution failures. The simulator models commit-content identity separately. Validation evidence owns current test counts; mechanism tests do not establish semantic recovery quality.
