---
status: green
revised_at: "2026-11-17T06:10:47+11:00"
---

A confined stationed Operator outside a Git worktree could receive XDG paths under its task-specific agent-data/<hash>/v2 store without a matching writable grant. The ordinary write_paths branch granted legacy global OpenCode directories but omitted the selected store. OpenCode then failed at startup with `PlatformError: PermissionDenied: FileSystem.makeDirectory (.../v2/data/opencode/log)` and EACCES creating v2/data. Lifecycle reported no completion receipt and no exit code before reaching the model. This is not an inference or assignment-quality failure.

opencode.launch now derives the selected versioned store once and passes that same Path to write_paths, read_paths and the environment/spec. Both confinement branches include only that selected store, rather than broadly granting the agent-data parent. Launch prepares the directory before sandboxing. Legacy/unconfined behavior and durable assignment/session ownership remain unchanged.

tests.test_opencode_scratch exercises the stationed non-repository branch and the real worktree guard's ability to create the selected store's data/opencode/log, without relying on the fixture's broad /tmp grant. The native V2 source-launch fixture also passed with a disposable stub provider. The three observed weekly-report failures were operator-0508b9, operator-613f4c and operator-4b993c; their server.log startup error is the retained evidence. Do not read report prompts or user session contents to diagnose this filesystem error.

The fix is installed, but restarting a completed/failed assignment is separate authority. Preserve the existing report tasks, session data and budgets; do not delete them or silently create a fresh-budget duplicate. Ordinary retry/dispatch must use the supported lifecycle route.
