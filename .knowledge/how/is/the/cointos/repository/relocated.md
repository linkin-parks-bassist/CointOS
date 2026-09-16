---
status: "unverified"
created_at: "2026-09-14T22:54:59+10:00"
scope: "local"
source: "David relocation instruction; scoped path-reference audit 2026-09-14"
updated_at: "2026-09-14T22:56:18+10:00"
---

The requested source checkout destination is `/home/david/Projects/CointOS`, replacing the former `~/agent-ecosystem` checkout. Mutable CointOS runtime state/logs remain under `/home/david/.CointOS`; standalone global knowledge trees remain under `/home/david/.knowledge`. Relocation must preserve Git metadata and uncommitted/untracked work.

The pre-move audit found source-path references in role/task prompts, portability tests, development unit templates, workspace/model/configuration paths, local knowledge and the Codex project trust entry. Update literal absolute, home-relative and systemd `%h` source-path spellings, preserving existing service identities and the credential directory `.config/agent-ecosystem`. Do not rename service identifiers or credentials merely because the source directory changes.

Some stopped-service templates still address repo-relative runtime state/logs. Relocation alone does not repair that existing runtime-root debt or qualify service activation. Installed symlinks must be checked for references to the old source path; no compatibility symlink should be necessary after dependencies are updated. Historical runtime evidence and Git history are not rewritten. After moving, validate repository identity/status, scoped path references, root discovery/proofs and focused path tests. This leaf records the procedure; completion evidence is added after the move.

The checkout was moved by directory rename on 2026-09-14, preserving Git metadata and uncommitted/untracked work. Source-path literals and the Codex trust entry were updated; the installed unit symlink audit found no direct source-target symlinks. Fresh `kt roots` discovers the new local tree. Role/task path tests pass 3/3 each. Runtime records, credential directories and service activation were not changed. The intended installed execution home is now `~/.CointOS`; updated development source paths are transitional until that installer is implemented.

Post-move observable launch tests pass 10/10, including isolated real OpenCode configuration and synthetic request capture. The scoped executable/configuration/prompt path audit found no old source-path spellings; both permitted KT proof checks and whitespace validation passed. No live inference or service activation was performed.
