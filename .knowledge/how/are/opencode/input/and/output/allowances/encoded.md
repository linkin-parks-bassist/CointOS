---
status: "unverified"
created_at: "2026-09-14T22:40:40+10:00"
scope: "local"
source: "Independently inspected current source and design decisions in this turn; isolated real OpenCode read-back and named tests; 2026-09-14"
updated_at: "2026-09-14T22:42:45+10:00"
---

apply_opencode_capacity receives a validated capacity record. It overwrites the selected model limit with context = opencode_context_tokens, output = opencode_output_tokens, and input = context - output. Output must be positive and strictly below context. Input is the allowance with the selected maximum output reserved, not a second independent context pool. Explicit input also replaces stale inherited input claims, which would survive ordinary recursive config merging if omitted.

Backend effective output is the minimum of the qualified exact-client ceiling, any observed backend output ceiling, and the checked-in output reserve. For managed requests, constrain_launch_capacity additionally limits the OpenCode fields to the admitted lease. Source observations remain intact. See why/can/a/valid/inference/lease/still/conflict/with/opencode/output/limits.md for this distinction.

The encoder strips model limits from the other base-catalogue entries; it does not certify those other models. This wrapper is qualified for the selected local model, not arbitrary later model switches. Code owner: ecosystem/inference_proxy.py apply_opencode_capacity, opencode_environment. Tests: tests/test_inference_enforcement.py and tests/test_opencode_launch.py. Read-back checks all three resolved limit fields before inference.

A bounded real-client capture test uses a synthetic local HTTP/SSE provider, not Lemonade or GPU computation. Installed OpenCode sends max_tokens = 128 when the constrained model output allowance is 128. This checks request construction in addition to catalogue read-back; it does not benchmark or exercise a full-context compaction.
