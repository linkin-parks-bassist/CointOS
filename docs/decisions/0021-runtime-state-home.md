# 0021: Keep live runtime state outside the source checkout

Date: 2026-09-11

## Decision

Store the populated CointOS runtime trees at `/home/david/.CointOS/state` and
`/home/david/.CointOS/logs`. Do not keep compatibility symlinks or other runtime
path shims in the source checkout. Code and operator interfaces must distinguish
the immutable source root from the mutable runtime root explicitly.

Systemd path watches name the physical state path directly. New runtime data must
not be accumulated in a Git checkout.

`inbox/` and `projects/` remain repository directories for now because they contain
only tracked placeholders, not accumulated runtime payload. Revisit their physical
location before either begins retaining live data.

## Migration

Writers and watchers were stopped before moving the trees. Existing JSONL was
moved byte-for-byte and not rewritten. A temporary compatibility-link cutover was
rejected and removed at David's direction. Services remain stopped until their
runtime paths are explicitly refactored to use `~/.CointOS`.

## Consequences

- Branch switches and checkout cleanup no longer put the live state or logs at risk.
- Repo-relative runtime interfaces are intentionally broken rather than retained as
  permanent compatibility cruft.
- The next implementation step is an explicit source-root/runtime-root split,
  including durable artifact-path semantics and tests, before services restart.
