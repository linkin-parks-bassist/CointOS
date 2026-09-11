---
verified_at: '2026-09-12T01:52:04+10:00'
verified_by: opencode /home/david
scope: project local
source: pre-99318d9 Git history; ecosystem/opencode_capacity.py; ecosystem/opencode_client.py; config/opencode-capabilities.json; ecosystem/models.py observe_opencode_backend_capacity
verification: Distilled the accepted contract and immediate implementation seam; the pure record, the version-qualified capability, and the incarnation-bound observation adapter seams are implemented and test-verified, no activation claimed.
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
(1.18.30 -> 32000); an unknown version has no default and closes launch. The
fresh backend-capacity observation adapter is implemented in `ecosystem/models.py`
(`observe_opencode_backend_capacity`), a pure incarnation-bound projection of one
verified resident observation (reusing `_observed_model_record` and
`context_layout.observed_context_layout`) into the constructor's record: the
per-request context, aggregate pool, and mode come verbatim from the layout, the
backend reports no output ceiling, the prompt estimate is zero until the launcher
supplies it, and contradictions return explicit absence (None). The next seam is
the one ephemeral OpenCode configuration encoder. Do not begin by editing user
OpenCode configuration, replacing the executable symlink, restarting services, or
changing live model allocation.
Wrapper integration and activation are later independently verified stages.
