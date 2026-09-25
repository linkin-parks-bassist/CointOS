---
status: green
revised_at: "2026-09-26T03:19:52+10:00"
---

If a role Markdown body in `roles/` refers to a repository helper script, use a portable home-relative spelling such as `~/Projects/CointOS/scripts/tell-david`, not a fixed `/home/david/...` path. The checked-in role Markdown bodies are intentionally blank during the role redesign, so no helper reference is currently required. `tests/test_role_path_portability.py` verifies the role files exist and contain no fixed `/home/david/` path; it does not resurrect instructions removed from those roles. See `what/is/the/intended/replacement/for/existing/agent/roles.md` for the redesign boundary. The same portability concern applies to Python-generated task instructions; see `why/do/agent_facing_strings/use_home_specifiers.md`.
