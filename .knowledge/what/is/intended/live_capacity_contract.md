---
verified_at: '2026-09-11T23:40:30+10:00'
verified_by: opencode /home/david
scope: project local
source: pre-99318d9 Git history; ecosystem/opencode_capacity.py; ecosystem/opencode_client.py; config/opencode-capabilities.json
verification: Distilled the accepted contract and immediate implementation seam; the pure record and the version-qualified capability seams are implemented and test-verified, no activation claimed.
review_when: Recheck after each accepted live-capacity implementation stage.
---

Every OpenCode launch should derive one effective capacity record from fresh backend
per-request allocation, qualified model limits, and the installed client's exact
version capabilities. Total pool size, training maximum, static catalogues, and
saved user configuration are not runtime capacity truth. Contradictory, stale, or
unknown inputs fail closed. OpenCode compaction and CointOS continuation must use
the same effective denominator; `finish: length` is incomplete even after HTTP 200
and process exit zero.

The pure record seam is implemented in `ecosystem/opencode_capacity.py`
(`effective_inference_capacity`, `launch_fingerprint`); effective output is the
smallest of the qualified client ceiling, any observed backend output ceiling, and
the policy reserve, and the effective context is the observed per-sequence cap
verbatim. The version-qualified capability seam is implemented in
`ecosystem/opencode_client.py` against `config/opencode-capabilities.json`
(1.18.30 -> 32000); an unknown version has no default and closes launch. The next
seam is the fresh backend-capacity observation adapter in the current observation
owners. Do not begin by editing user OpenCode configuration, replacing the
executable symlink, restarting services, or changing live model allocation.
Observation, anonymous per-launch config construction, wrapper integration, and
activation are later independently verified stages.
