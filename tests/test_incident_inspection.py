"""Bounded, read-only projection of an emergency snapshot."""

import json
import runpy
import tempfile
import unittest
from pathlib import Path

from ecosystem.resource_control import _survivor_task


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/cointos-incident"
summarize = runpy.run_path(str(SCRIPT))["summarize"]
report = runpy.run_path(str(SCRIPT))["report"]


def incident():
    return {
        "id": "incident-1", "detected_at": "now", "reason": "pressure",
        "context_boundary": "sessions preserved",
        "active_jobs": [], "active_control_turns": [], "interrupted_jobs": [],
        "resources": {"memory_available_gb": 50, "gtt_used_gb": 60,
                      "swap_used_gb": 0, "memory_full_avg10": 2, "oom_kills": 0},
        "executor_reconciliation": {"ok": True, "blockers": [],
                                    "proxy": {"retained": ["lease-1"]}},
        "unload": {"ok": True}, "emergency_model_load": {"ok": True},
        "large_private_snapshot_payload": "x" * 1_000_000,
    }


class IncidentInspectionTests(unittest.TestCase):
    def test_survivor_prompt_starts_with_bounded_views_and_early_record(self):
        path = Path("/runtime/state/resource-incidents/incident-1.json")
        prompt = _survivor_task(path, "incident-1", None)
        self.assertIn("/runtime/scripts/cointos-incident incident-1 --json", prompt)
        self.assertIn("/runtime/scripts/cointos-health --json", prompt)
        self.assertLess(prompt.index("Create `state/resource-incidents/incident-1-conclusion.md` early"),
                        prompt.index("resource-control recover"))

    def test_summary_is_bounded_and_never_claims_recovery(self):
        control = {"incident_id": "incident-1", "mode": "emergency",
                   "emergency_phase": "active",
                   "emergency_work_gate": {"mode": "draining"},
                   "sole_survivor_job": "task-1"}
        result = summarize(incident(), control, conclusion_exists=False)
        self.assertLess(len(json.dumps(result)), 2_000)
        self.assertEqual(result["recovery_safety"], "not assessed")
        self.assertEqual(result["affected_counts"]["retained_proxy_leases_at_snapshot"], 1)
        self.assertEqual(result["current"]["work_gate"], "draining")
        self.assertFalse(result["conclusion_exists"])

    def test_report_rejects_path_escape_and_snapshot_identity_mismatch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = root / "state"
            incidents = state / "resource-incidents"
            incidents.mkdir(parents=True)
            (state / "resource-control.json").write_text(json.dumps({
                "incident_id": "incident-1", "mode": "emergency"}))
            (incidents / "incident-1.json").write_text(json.dumps({
                **incident(), "id": "wrong"}))
            with self.assertRaisesRegex(ValueError, "invalid incident ID"):
                report(root, "../escape")
            with self.assertRaisesRegex(ValueError, "identity mismatch"):
                report(root, "incident-1")


if __name__ == "__main__":
    unittest.main()
