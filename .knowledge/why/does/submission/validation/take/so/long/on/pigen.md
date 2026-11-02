---
status: green
revised_at: "2026-11-03T00:27:56+11:00"
---

Validation used to be dominated by recompiling and no longer is. `cointos_finish` runs the packet's commands (`contracts.packet_tests`) and `cointos_land` runs every command the candidate registers, one at a time under `state/test-output.lock`, because pigen's tests write fixed `/tmp` paths. Each runs in a `systemd-run` unit for its memory cap, group kill and deadline. A command that fails is also rerun on main to decide whether it was already red (`contracts`).

Before pigen `ac7651f`, each of 30 C test targets compiled its whole program into a temporary directory, ran one case and deleted the binary. Over 68 measured commands that was 364 seconds of wall time and 360 of CPU, so systemd and lock waits cost almost nothing when uncontended. Those targets now build once under `build/tests` and rebuild only when their sources, shared headers or the Makefile change.

Recent test-packet `cointos_land` calls took 240 to 751 seconds, usually 500 to 700. The first implementation landing after the cleanup ran 120 commands in 64 seconds. It is one sample of a different landing kind.

That landing's integrator took 2,341 seconds, of which tests were about 104 and generation 1,647. About 19,900 of its 30,258 generated tokens went to reading and rewriting knowledge leaves, and 7,500 to rounds running bash commands.

A packet that edits an existing test file is checked against its whole manifest. Commands it only inherited from its base and main has since removed are dropped, because the composed tree has nothing to run for them and the already-red exemption covers only commands registered on main. Before CointOS `9d1fdbc`, those commands stayed binding, so removing commands from main failed every older packet that edits a shared test file.

pigen `c2827a5` and `9c53568`, by the user's decision, removed the old end-to-end tests: seven contract commands the gate had exempted as already red on master, and their Makefile targets, programs, testbenches and scripts. They used transfer-first `.pigen` syntax that production `./pigen` rejects, or failed RTL naming. The user will introduce new end-to-end tests; until then no contract compiles a real design end to end through those programs. `examples/` remains, including programs and testbenches no target uses now.

`tests/harness_artifact_ownership.sh` still passes, though its header's "fresh, invocation-owned binary" wording no longer describes the targets.

A test run outside the daemon must hold `state/test-output.lock` for every command, and doing so slows any concurrent submission or landing.
