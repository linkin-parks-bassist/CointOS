# CointOS survival invariants

Recorded by the root Codex agent on 2026-09-04 from David's explicit ordering.
These are binding requirements for architecture, scheduling, admission, recovery,
testing, deployment, and incident handling. They are not ordinary priorities that
may be traded against throughput or convenience.

## Ordered priorities

1. **Cointelprofessional remains responsive.** House fire, power outage, or direct
   hardware destruction are the only accepted causes of unresponsiveness. No job,
   model, restart, reset, repair, deployment, or emergency action may sacrifice the
   Coin control plane or GUI responsiveness.

2. **Memory does not run out.** If OOM is possible, scale down, delay work, reduce
   concurrency or context, unload replaceable models, spill durable state to disk,
   or take any other bounded preventative action. An actual OOM immediately enters
   emergency mode: activate Sole Survivor, preserve Coin and GUI responsiveness,
   diagnose and repair, then repopulate the system safely.

3. **Context overflow is eliminated as a visible error class.** An agent never
   fails merely because its current context is full. Before the limit is reached,
   durable state and a sufficient handover are prepared and work continues swiftly
   in a fresh context. This continuation must be seamless and invisible at the
   task/control-plane level. There are no exceptions.

## Dependency graph

Priority 1 depends on Priority 2. Those are the only dependencies among these
three priorities. In particular, Priority 3 is independently mandatory; it is not
permitted to become conditional on either of the first two.

## Operational interpretation

- Resource admission must reserve memory and responsiveness for Coin and the GUI
  before admitting any replaceable workload.
- Prevention is preferred to OOM recovery; Sole Survivor is the consequence of a
  real OOM or full emergency, not a routine pressure-management mechanism.
- Context limits are scheduling inputs. Approaching one triggers proactive
  checkpoint and handover, never a terminal `context_overflow` job result.
- Tests and monitors must verify the externally observed invariants, including
  continuity across process death, memory pressure, lifecycle commands, and context
  turnover. A heartbeat or exit code alone is insufficient evidence.
- Status and incident messages continue through Coin throughout repair whenever the
  underlying house, power, and hardware still permit communication.

