# Repository instructions

- Preserve local-only inference and filesystem/version-control as the source of truth.
- Read `docs/status.md`, relevant project notes, and decisions before changing behavior.
- Record consequential design changes in `docs/decisions/`.
- Never enable remote access, access credentials, program hardware, push code, or
  enable system services without David's explicit approval.
- Runtime records are append-only JSONL. Never rewrite them as part of summarization.
- Keep generated runtime state out of Git; keep schemas, templates, tests, and
  operational instructions in Git.

