import random
import unittest
from datetime import datetime, timezone
from ecosystem.steward_tasks import select


class StewardTaskTest(unittest.TestCase):
    def test_selects_a_real_card_and_records_reason(self):
        config = {"task_deck":[{"id":"system-map","file":"system-map.md","weight":1,"maximum_interval_seconds":60}]}
        task_id, content, reason = select(config, {}, rng=random.Random(1), now=datetime.now(timezone.utc))
        self.assertEqual(task_id, "system-map")
        self.assertIn("Maintain a broad", content)
        self.assertIn("overdue", reason)
