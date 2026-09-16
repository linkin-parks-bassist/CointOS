---
scope: project local
status: "unverified"
source: "Direct source/runtime change and focused existing checks 2026-09-15"
review_when: Recheck when client limit observation or backend capacity derivation changes.
updated_at: "2026-09-15T11:54:56+10:00"
---

OpenCode package versions are observable identity, not an inference-admission allowlist. A version absent from `config/opencode-capabilities.json` must not block or strand benign local work. `qualified_opencode_capability` records the literal nonempty version and supplies no additional client ceiling for an unknown version; fresh backend capacity, any observed backend output ceiling, and configured output reserve still bound each request.

The catalogue may retain measured version-specific client ceilings when useful. Add an exact entry only after a bounded request-capture probe or authoritative client fact establishes a real ceiling. Requalification is background refinement, not a prerequisite for dispatch. An absent/unrecognised version entry is normal after package updates; malformed catalogue structure and an unavailable executable remain actual configuration/runtime errors.

The former exact-version fail-closed behavior stranded an ordinary GPU worker after the installed client moved from 1.18.30 to 1.18.31. The temporary copied 1.18.31 entry was removed rather than perpetuating that barrier. Existing `test_opencode_client.py` and `test_opencode_capacity.py` checks pass after changing the policy; no new test case was added.
