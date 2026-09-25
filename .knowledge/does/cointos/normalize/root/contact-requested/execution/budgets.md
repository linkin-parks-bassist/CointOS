---
status: green
revised_at: "2026-09-25T22:01:08+10:00"
verifiable: "true"
---

Yes. Validating a root `contact_requested` task contract normalizes its execution-lifetime budget fields (`run_seconds`, `task_seconds`, `maximum_attempts`, `maximum_output_bytes`, and `maximum_evidence_items`) to `None`, while preserving `maximum_children`. A non-root or differently authorized contract retains the supplied finite values.

Proof:

```bash
python3 - <<'PY'
from pathlib import Path
from ecosystem.task_contracts import validate_task_contract
root = Path.cwd().resolve()
contract = {
    "objective": "proof",
    "scope": {"workspace": str(root), "read_paths": [str(root)], "write_paths": [str(root)]},
    "authority_profile": "contact_requested",
    "requirements": {"required_capabilities": [], "minimum_context_tokens": 0},
    "acceptance": [],
    "budget": {"run_seconds": 1, "task_seconds": 2, "maximum_attempts": 3,
               "maximum_output_bytes": 4, "maximum_evidence_items": 5,
               "maximum_children": 0},
    "source_key": "proof:contact-budget", "parent_job_id": None,
    "stop_condition": "Stop after proof.",
}
normalized = validate_task_contract(contract)["budget"]
assert all(normalized[field] is None for field in (
    "run_seconds", "task_seconds", "maximum_attempts",
    "maximum_output_bytes", "maximum_evidence_items"))
assert normalized["maximum_children"] == 0
contract["authority_profile"] = "bounded_maintenance"
assert validate_task_contract(contract)["budget"]["maximum_output_bytes"] == 4
contract["authority_profile"] = "contact_requested"
contract["parent_job_id"] = "task-parent"
assert validate_task_contract(contract)["budget"]["maximum_output_bytes"] == 4
PY
```
