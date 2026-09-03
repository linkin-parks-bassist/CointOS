import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from ecosystem.scheduler import choose
import ecosystem.scheduler as scheduler


class SchedulerTest(unittest.TestCase):
    def test_prefers_resident_large_model_without_starving_old_work(self):
        now = datetime.now(timezone.utc)
        resident = (Path("resident"), {"id":"a", "model":"large", "created_at":(now-timedelta(minutes=1)).isoformat()})
        other = (Path("other"), {"id":"b", "model":"small", "created_at":(now-timedelta(minutes=2)).isoformat()})
        inventory = {"models":[{"id":"large","size_gb":16,"loaded":True},{"id":"small","size_gb":4,"loaded":False}]}
        path, _, reason = choose([other, resident], inventory, now)
        self.assertEqual(path, Path("resident"))
        self.assertIn("batching", reason)

