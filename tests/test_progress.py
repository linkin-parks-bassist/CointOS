import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from cointos import progress


class Switches(unittest.TestCase):
    def test_classifies_resident_snapshot_and_cold(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            now = time.time()
            rows = [
                {"event": "switch", "at": now - 5, "mode": "resident", "restored": 900},
                {"event": "switch", "at": now - 10, "restored": 400},
                {"event": "switch", "at": now - 15, "restored": 0},
                {"event": "switch", "at": now - 1000, "restored": 0},
            ]
            path.write_text("\n".join(json.dumps(row) for row in rows))
            found = progress.switch_summary(path, minutes=5, now=now)
        self.assertEqual(found, {"total": 3, "resident": 1, "snapshot": 1, "cold": 1})


class Report(unittest.TestCase):
    def state(self):
        return {
            "memory": {"headroom_gb": 12.5, "available_gb": 30.0, "psi": 0.0, "swap_gb": 8.0},
            "agents": {"worker-a": {"id": "worker-a", "role": "worker", "state": "reading", "thoughts": 2}},
            "thoughts": {"t1": {"agent": "worker-a", "prompt": 1000, "read": 500,
                                "generated": 0, "reading": True, "rate": None}},
        }

    def test_text_shows_progress_and_switch_mix(self):
        with tempfile.TemporaryDirectory() as directory:
            events = Path(directory) / "events.jsonl"
            events.write_text(json.dumps({"event": "switch", "at": time.time(),
                                          "mode": "resident", "restored": 10}))
            with patch.object(progress, "backend_stats", return_value=None):
                text = progress.report(self.state(), {"work_model": "m"}, minutes=5, events_path=events)
        self.assertIn("CointOS progress", text)
        self.assertIn("resident 1", text)
        self.assertIn("worker-a", text)
        self.assertIn("500/1000 (50%)", text)

    def test_json_is_the_underlying_data(self):
        with tempfile.TemporaryDirectory() as directory:
            events = Path(directory) / "events.jsonl"
            events.write_text("")
            with patch.object(progress, "backend_stats", return_value=None):
                data = progress.report(self.state(), {"work_model": "m"}, minutes=5,
                                       as_json=True, events_path=events)
        self.assertEqual(data["agents"][0]["read_fraction"], 0.5)
        self.assertEqual(data["switches"]["total"], 0)

    def test_backend_stats_reads_speculation_counters(self):
        health = json.dumps({"all_models_loaded": [
            {"model_name": "m", "backend_url": "http://127.0.0.1:9/v1"}]})
        metrics = "llamacpp:spec_decode_num_draft_tokens_total 300\n" \
                  "llamacpp:spec_decode_num_accepted_tokens_total 240\n" \
                  "llamacpp:prompt_tokens_seconds 265\n" \
                  "llamacpp:tokens_predicted_total 50\n"
        with patch.object(progress, "_get", side_effect=[health, metrics]):
            found = progress.backend_stats({"lemonade": "http://127.0.0.1:1"}, "m")
        self.assertEqual(found["draft_tokens"], 300)
        self.assertEqual(found["accepted_tokens"], 240)
        self.assertAlmostEqual(found["acceptance"], 0.8)
        self.assertEqual(found["prefill_tps"], 265.0)


if __name__ == "__main__":
    unittest.main()
