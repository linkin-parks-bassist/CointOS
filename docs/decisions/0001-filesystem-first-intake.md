# ADR 0001: Filesystem-first deterministic intake

- Status: accepted for milestone 1
- Date: 2026-09-03

## Decision

Use atomic JSON job files, append-only JSONL events, and deterministic Markdown
proposal generation for the first slice. Treat project files as source of truth.
Ship systemd templates but do not install or enable them yet.

## Rationale

This proves durable intake, observability, idempotency, and a kill switch without
making model availability part of correctness or crossing the undecided autonomy
boundary. Lemonade-based enrichment can later produce a proposed patch while the
deterministic coordinator retains state ownership.

