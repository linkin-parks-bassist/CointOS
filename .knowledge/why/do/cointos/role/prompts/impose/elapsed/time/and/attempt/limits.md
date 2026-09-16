---
status: "unverified"
created_at: "2026-09-16T05:06:44+10:00"
scope: "local"
source: "roles steward lead worker intake and chunker inspected 2026-09-16"
updated_at: "2026-09-16T05:22:57+10:00"
---

Five active role prompts still impose arbitrary local-agent work limits independently of the task-contract code:

- `roles/steward.md`: two attempts and ten minutes, described as a hard boundary.
- `roles/lead.md`: two attempts and ten minutes, described as a hard boundary.
- `roles/worker.md`: three attempts and thirty minutes.
- `roles/intake.md`: three attempts and two minutes.
- `roles/chunker.md`: at most 20 candidate markers for at most five minutes when no explicit scan limit exists.

These instructions predate the current MVP/local-worker policy. Elapsed time and attempt count do not prove completion or a safe handoff, and the executor constructors now represent absent lifetime ceilings directly. Scope, authorization, explicit task acceptance, cancellation, resource priority, and concrete blockers remain valid boundaries.

Next implementation: replace only these role-level minute/attempt defaults with scope-based completion/blocker language. Preserve model guidance, missions, authority, handoff requirements, and the chunker's requirement to narrow broad work to one coherent note. No regression tests are needed for prompt text removal.

The five prompt-level barriers are removed. Steward, lead, worker, and intake now work until assigned scope and acceptance are complete or a concrete blocker requires a resumable handoff, explicitly stating that elapsed time and attempt count do not prove completion. Chunker preserves explicit task scan limits but, without one, inspects only what is needed for one coherent candidate note and narrows broad backlogs without an invented count or duration. The observable Qwen worker exited 0; coordinator `rg` found none of the removed phrases in the five files and direct section inspection matched the decided text. No tests were added.

Implementation is complete: all five active prompt sections use scope/acceptance or concrete-blocker completion. The observable worker exited 0, and coordinator inspection confirmed the exact replacement text and zero matches for the removed numeric phrases.
