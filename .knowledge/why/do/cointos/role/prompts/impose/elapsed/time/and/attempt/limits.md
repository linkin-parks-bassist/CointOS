---
status: green
revised_at: "2026-09-17T09:56:37+10:00"
---

Active role prompts no longer impose arbitrary minute, attempt, or fallback-marker limits. Steward, lead, worker, and intake work until their assigned scope and acceptance conditions are complete or a concrete blocker requires a resumable handoff. Elapsed time and attempt count do not prove completion.

Chunker preserves an explicit scan limit when the task supplies one. Without one, it inspects only what is needed for one coherent candidate note and progressively narrows broad work; it does not invent a count or duration. Scope, authorization, cancellation, resource priority, acceptance criteria, and concrete blockers remain valid boundaries.

Coordinator inspection found none of the retired numeric phrases in the five prompts. No regression tests were added for this prompt-only repair.