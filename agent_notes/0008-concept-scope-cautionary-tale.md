# Cautionary tale: vocabulary does not imply infrastructure

A named role, output, or informal term does not by itself imply a new domain entity,
schema, store, lifecycle, protocol, queue, scheduler, dispatcher, or verification
system. Implement the requested behaviour at the narrowest existing architectural
boundary that can represent it honestly.

Before promoting a term into shared infrastructure, require explicit requirements or
clear evidence from authoritative architecture documents. If that would be a
consequential design choice, present the evidence and tradeoffs to David and stop for
his decision. Do not turn speculative machinery into a fait accompli through notes,
tests, schemas, or implementation.

When removing a mistaken conceptual expansion, restore the clean intended model.
Remove its code, schemas, tests, terminology, negative requirements, disclaimers, and
historical commentary from ordinary architecture and operating documents. Do not
make the rejected idea conspicuous by repeatedly explaining its absence. Preserve a
lesson only as a separate, self-contained cautionary tale when that lesson will help
prevent the same class of mistake.

## Fluid design and disposable implementation

The root Codex agent recorded David's explicit clarification on 2026-09-05: nothing
in a system under fluid design is sacred. Building is part of discovering the
canonical design, and the resulting hairball may be valuable precisely because it
reveals why its preliminary conception was wrong.

When that happens, do not massage the implementation toward the newly understood
design. Do not add adapters, compatibility strata, dual routes, or migration
machinery merely to preserve sunk work. Retain the distilled obligations, contracts,
evidence, and still-valid tests; delete the incompatible scaffolding and rebuild the
correct structure cleanly. The discarded implementation already repaid its cost by
revealing the way forward.
