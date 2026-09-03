# Core engineering principles

These are binding constraints for humans and agents working on this ecosystem.

## Continual custodianship

The machine should improve itself through observation, taste, and disciplined
maintenance. Periodic Stewards inspect broad health and durable knowledge. Auditors
seek systemic defects, misleading behavior, unsafe assumptions, and violated
invariants. Refactorers turn accepted findings into small verified structural
improvements. They should work gently: one bounded change, evidence, tests, notes,
and a clean handoff at a time.

Autonomy is not permission to churn. Do not rewrite healthy components for novelty,
generate speculative abstractions, or confuse activity with improvement. Prefer
measured simplification, deletion of accidental complexity (with approval where
material), explicit contracts, and recovery-friendly changes.

## No object-oriented programming

OOP is strictly forbidden. This includes classes, inheritance, class-based domain
models, service objects, mutable objects used as implicit state machines, and
framework choices that force application logic into classes.

Use instead:

- Plain versioned data records.
- Pure transformations where practical.
- Small functions and modules with explicit inputs and outputs.
- Explicit state-transition tables and validators.
- Ports expressed as callables or data-driven protocols.
- Composition and dependency injection through function arguments.
- Append-only events and derived projections.

Python standard-library exception types and external library internals are not our
code. Existing `unittest.TestCase` classes predate this rule and are migration debt;
move tests to function style without pausing higher-risk architectural repairs.

## Architectural quality

- Separate domain policy from Telegram, Lemonade, OpenCode, systemd, and filesystem adapters.
- Never use model prose as authority for facts or state transitions.
- Make invalid states difficult to represent and transitions explicit.
- Version persisted formats and provide migrations before changing them.
- Centralize policy; do not fix repeated symptoms with scattered conditionals.
- Test invariants, replay, crash boundaries, and failure recovery—not only happy paths.
- Preserve inspectability, local inference, auditability, and global pause behavior.
- Record debt honestly. Never describe a prototype as production architecture.

