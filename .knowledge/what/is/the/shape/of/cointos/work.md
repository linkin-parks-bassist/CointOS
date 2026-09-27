---
status: green
revised_at: "2026-09-27T11:59:47+10:00"
---

David's direction of 2026-09-27 is **everything small, pipelined, hardware-like**. Local models have useful flexibility within one well-bounded concern; CointOS must not rely on that flexibility across a large assignment. Agents are execution units, work flows through their stages, and abstraction keeps the next level small too.

**Concern pipelines.** Break work by interface and responsibility, not a few large features. A parser may separate lexical recognition, value construction and serialization; the precise stages depend on its contract. Each item gives one outcome, exclusions, inputs/outputs, error and ownership rules, affected area, dependencies and an executable check. Managers sketch the pipeline but elaborate only the next one to three items per run, retaining an unexpanded frontier in the idea. Surveys advance that frontier. Workers block oversized items with the requested split instead of attempting a whole feature. All roles compute with code/tools rather than extended prose arithmetic.

**Reverse review.** Workers report the boundary they expose and assume, checks and unresolved mismatches; the owning interface leaf states the current contract. The integrator checks that boundary against the actual change and neighbors. Manager surveys compare a small set of neighboring contracts at a common abstraction level and record the higher-level contract or queue a bounded coherence check. This is the current prompt-based review pipeline; a separately scheduled recursive reviewer hierarchy is not implemented or accepted live.

**Small gardeners.** work.next_task chooses up to garden.leaves_per_pass leaves (configured 3): random for routine passes, brown then yellow for health repairs. A gardener verifies only that batch plus necessary neighboring evidence, lands corrections and ends. Completion requires a landed branch, a clean worktree and normal stop. Selected leaves still non-green on main are reported through an alert; the bounded pass ends instead of retrying until the whole tree is green. This does not validate unresolved leaves. An unchanged health set is retried only at the routine interval. Separate tree-auditor agents examine one structural concern across representative owners (duplicates, log-shaped answers, stale routes or contradictory abstraction levels). Both kinds share per-tree exclusion. Broad conceptual coverage is not permission for an exhaustive fact audit.

The role prompts and scheduler implement these bounds; live task-quality acceptance remains to be demonstrated. Earlier oversized sandbox worker, manager and gardener runs took tens of minutes to over an hour and accumulated large shared-lane contexts. Those observations motivate the scope limit, not an arbitrary time-based kill of useful model work.

The obsolete test assignments were cancelled at David's request. Autonomy remains paused with no replacement queue. Next is a deliberately small pipeline exercise when resumed; what/is/next.md owns that sequence.
