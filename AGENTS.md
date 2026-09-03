# Repository instructions

The workspace instructions in `/home/david/AGENTS.md` apply here in full. This is
personal orchestration infrastructure that may coordinate professional tasks; that
does not authorize mixing personal, Avnet, AMD, partner, or customer information.

- Preserve local-only inference and filesystem/version-control as the source of truth.
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
