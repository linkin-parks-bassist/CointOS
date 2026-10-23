---
status: green
revised_at: "2026-10-17T23:25:26+11:00"
---

Hidden packets stay off main while red, but are not technically secret from implementation agents. Task worktrees share the project's Git object database. Accepted commits remain reachable through branches or refs/cointos/archive; git log --all and git show can expose them. A native implementer previously found and applied its packet this way.

OpenCode explicitly allows Git metadata reads. The construction kernel boundary restricts writes, not shell reads; a private directory under the same Unix identity is not a read boundary. Moving or deleting refs alone cannot hide shared objects. Strong isolation must also account for test-author/reviewer worktrees, conversation/event files and read APIs carrying test material.

The user decision remains pending: keep the instruction-based boundary, or enforce technical isolation. A separate CointOS-owned test repository fetched only for trusted validation/review is a proposed component, not a deployed confidentiality guarantee. Do not treat hidden acceptance or stage/write guards as proof that implementers cannot inspect tests.
