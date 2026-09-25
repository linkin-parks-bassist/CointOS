---
status: green
revised_at: "2026-09-14T23:21:34+10:00"
---

The previous executor close fixture pinned front_sequences and total_sequences in resource-policy.json. _load_capacity_policy deliberately rejects these fields because config/inference.cfg owns slot counts, including release_sequence cleanup. Repair the fixture with front_slots and work_slots in inference.cfg and retain the remaining resource policy fields; do not weaken production validation.

The fixture now writes a complete [inference] INI section with front_slots=1, work_slots=3, context_tokens_per_slot=4096, backend_context_tokens=12288 and context_mode=fixed. All five required keys are present; a pair of unsectioned slot assignments is invalid.
