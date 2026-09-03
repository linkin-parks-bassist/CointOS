import random, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from ecosystem import cli
from ecosystem.identity import assign

class IdentityTest(unittest.TestCase):
    def test_assigns_role_name(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(cli,"ROOT",Path(temporary)):
            (cli.ROOT / "state/jobs").mkdir(parents=True)
            self.assertIn(assign("worker",random.Random(1)),{"Rob","Nina","Dex"})
