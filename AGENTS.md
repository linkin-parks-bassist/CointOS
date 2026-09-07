# Repository instructions

The workspace instructions in `/home/david/AGENTS.md` apply here in full. This is
personal orchestration infrastructure that may coordinate professional tasks; that
does not authorize mixing personal, Avnet, AMD, partner, or customer information.

- Preserve local-only inference and filesystem/version-control as the source of truth.
- Launch future local Qwen/OpenCode workers with a live attachable OpenCode UI by
  default, using `scripts/opencode_observable.py` inside the existing admission
  gate. Publish the exact per-run attach command/session to David. Keep the server
  loopback-only, ephemeral and in the admitted process group; retain JSONL logs.
  Closing the viewer must not stop the worker. Do not restart a running worker to
  add viewing, expose a LAN/public listener, or replace gated inference with a
  permanent credential-bearing server. See `docs/operations/local-worker-view.md`.
  On David's graphical desktop, automatically open a new GNOME Terminal window
  attached to the exact new session; pass arguments directly, not via shell text.
  Headless runs still publish the attach command. A viewer failure must not cancel
  or restart the admitted worker.
- This observable spawn path is canonical for local model agents, not an optional
  debugging mode. Every new local agent must have its own visible oversight window
  and exact session context. Do not use an alternative silent background runner.
  If no graphical viewer can be opened, obtain David's explicit exception before
  starting the agent; a printed log path alone is not equivalent. A viewer closing
  or failing after launch is not permission to kill/restart its worker.
- Read `docs/status.md`, relevant project notes, and decisions before changing behavior.
- Record consequential design changes in `docs/decisions/`.
- Never enable remote access, access credentials, program hardware, push code, or
  enable system services without David's explicit approval.
- Runtime records are append-only JSONL. Never rewrite them as part of summarization.
- Keep generated runtime state out of Git; keep schemas, templates, tests, and
  operational instructions in Git.
- Object-oriented programming is forbidden everywhere in this ecosystem. Do not
  introduce classes, inheritance, objects carrying hidden mutable state, or
  class-oriented frameworks. Prefer small functions, plain data, explicit state
  transitions, modules with narrow interfaces, and composition. Existing class-based
  tests are known migration debt and should be converted incrementally.
- Treat maintainability, taste, simplicity, honest behavior, and architectural
  coherence as product requirements. Background Stewards, Auditors, and Refactorers
  should improve the system in bounded, tested increments without waiting for a
  visible failure or allowing autonomous scope to outrun approval boundaries.
- Treat scope as an enforced resource boundary. Every run needs one deliverable, a
  necessary-evidence boundary, explicit authority, a time/resource budget, and a
  stopping condition. Substantial or multi-concern work must be decomposed into
  independently verifiable tasks and delegated through durable handoffs; adjacent
  findings become follow-ups instead of silently expanding the current run.
- Prompted budgets are not sufficient enforcement. The scheduler and executor must
  eventually enforce role and task budgets mechanically and preserve a useful
  partial handoff when a run reaches its boundary.
