"""Fast, backend-free decisions for multi-model profile scheduling."""

import unittest
from pathlib import Path
from unittest.mock import patch

from ecosystem.backend_profile_scheduler import assess_profiles


class ProfileCandidateScanTests(unittest.TestCase):
    def assess(self, capacity, *, demand_a=0, demand_b=2):
        inventory = {
            "control_model": "control",
            "models": [{"id": "a", "loaded": True},
                       {"id": "b", "loaded": True}],
            "resource_envelope": {"verified": True, "fresh": True,
                                  "maximum_kv_bytes": 100_000},
        }
        policy = {"dynamic_models": {
            "estimated_kv_bytes_per_token": 1,
            "profile_minimum_dwell_seconds": 300,
            "profile_failure_cooldown_seconds": 3600,
        }}
        profiles = {"a": {"model_id": "a", "parallel_sequences": 2,
                          "context_tokens_per_sequence": 100},
                    "b": {"model_id": "b", "parallel_sequences": 1,
                          "context_tokens_per_sequence": 100}}
        def residency(_health, model_id):
            return {"state": "live", "record": {"model_id": model_id,
                    "is_busy": False, "pinned": False}}
        with patch("ecosystem.backend_profile_scheduler.resource_control.model_residency_status",
                   side_effect=residency), \
             patch("ecosystem.backend_profile_scheduler.backend_profiles.observed_profile",
                   side_effect=lambda record: profiles[record["model_id"]]), \
             patch("ecosystem.backend_profile_scheduler.backend_profiles.require_qualified_allocation"), \
             patch("ecosystem.backend_profile_scheduler.backend_profile_policy.qualified_ceiling",
                   return_value=2), \
             patch("ecosystem.backend_profile_scheduler.inference_policy.load_inference_policy",
                   return_value={"work_slots": 2}), \
             patch("ecosystem.backend_profile_scheduler.backend_profile_policy.model_demand",
                   side_effect=lambda _jobs, model_id, _route: {
                       "a": demand_a, "b": demand_b}[model_id]):
            return assess_profiles(
                Path("/unused-profile-test-root"), [], inventory, {}, {},
                capacity, policy, now=1000.0, boot_id="boot-one",
                route_for_job=lambda _job: None)

    def test_shrink_dwell_does_not_hide_another_models_growth(self):
        result = self.assess({"backend_profile_last_change": {
            "model_id": "a", "boot_id": "boot-one",
            "completed_monotonic": 900.0}})
        self.assertEqual(result["state"], "change")
        self.assertEqual(result["model_id"], "b")
        self.assertEqual(result["target_parallel_sequences"], 2)

    def test_eligible_growth_precedes_alphabetically_earlier_shrink(self):
        result = self.assess({})
        self.assertEqual(result["state"], "change")
        self.assertEqual(result["model_id"], "b")
        self.assertEqual(result["target_parallel_sequences"], 2)

    def test_shrink_is_selected_when_no_growth_is_needed(self):
        result = self.assess({}, demand_b=1)
        self.assertEqual(result["state"], "change")
        self.assertEqual(result["model_id"], "a")
        self.assertEqual(result["target_parallel_sequences"], 1)

    def test_failed_target_cooldown_does_not_hide_another_model(self):
        result = self.assess({"backend_profile_last_failure": {
            "model_id": "a", "target_parallel_sequences": 1,
            "boot_id": "boot-one", "completed_monotonic": 900.0}})
        self.assertEqual(result["state"], "change")
        self.assertEqual(result["model_id"], "b")
        self.assertEqual(result["target_parallel_sequences"], 2)

    def test_first_deferred_reason_survives_when_no_model_can_change(self):
        result = self.assess({"backend_profile_last_change": {
            "model_id": "a", "boot_id": "boot-one",
            "completed_monotonic": 900.0}}, demand_b=1)
        self.assertEqual(result["state"], "wait")
        self.assertEqual(result["reason"], "shrink_dwell")
        self.assertEqual(result["model_id"], "a")


if __name__ == "__main__":
    unittest.main()
