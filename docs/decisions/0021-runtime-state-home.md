# 0021: Keep live runtime state outside the source checkout

Date: 2026-09-11

## Decision

Store the populated CointOS runtime trees at `/home/david/.CointOS/state` and
`/home/david/.CointOS/logs`. Keep `state` and `logs` in the source checkout as
compatibility symlinks so existing code, durable relative artifact paths, and
operator commands continue to work without rewriting historical records.

Systemd path watches name the physical state path directly. Sandboxed user units
allow writes to both the source checkout and `%h/.CointOS`. New runtime data must
not be accumulated in a Git checkout.

`inbox/` and `projects/` remain repository directories for now because they contain
only tracked placeholders, not accumulated runtime payload. Revisit their physical
location before either begins retaining live data.

## Migration

Writers and watchers were stopped before moving the trees, then restarted after
the links and installed unit changes were in place. Existing JSONL was moved
byte-for-byte and not rewritten. The transient inference proxy was recreated after
the cutover.

## Consequences

- Branch switches and checkout cleanup no longer put the live state or logs at risk.
- Repo-relative interfaces remain compatible during a later explicit path refactor.
- Removing either compatibility symlink does not remove its target, but operators
  must resolve the link before backup, migration, or deletion work.
