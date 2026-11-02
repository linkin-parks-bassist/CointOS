---
status: green
revised_at: "2026-11-02T19:24:57+11:00"
---

Validation used to be dominated by recompiling. `cointos_finish` and `cointos_land` run every command in pigen's `tests/contracts.json`, one at a time under `state/test-output.lock`, because pigen's tests write fixed `/tmp` paths. Each runs in a `systemd-run` unit for its memory cap, group kill and deadline. A command that fails is also rerun on main to decide whether it was already red (`contracts`).

Before pigen `ac7651f`, each of 30 C test targets compiled its whole program into a temporary directory, ran one case and deleted the binary. Over 68 measured commands that was 364 seconds of wall time and 360 of CPU, about 10 minutes per run, so systemd and lock waits cost almost nothing when uncontended. Those targets now build once under `build/tests` and rebuild only when their sources, shared headers or the Makefile change. After the change, 109 commands with programs already built ran in 99 seconds outside the daemon. It has not yet been measured on a live submission.

pigen `c2827a5` and `9c53568`, by the user's decision, removed the old end-to-end tests: seven contract commands the gate had exempted as already red on master, and their Makefile targets, programs, testbenches and scripts. They used transfer-first `.pigen` syntax that production `./pigen` rejects, or failed RTL naming. The user will introduce new end-to-end tests; until then no contract compiles a real design end to end through those programs. `make test`, `make verify` and all 109 contracts pass on master. `examples/` remains, including programs and testbenches no target uses now.

`tests/harness_artifact_ownership.sh` still passes, though its header's "fresh, invocation-owned binary" wording no longer describes the targets.

A test run outside the daemon must hold `state/test-output.lock` for every command, and doing so slows any concurrent submission or landing.
