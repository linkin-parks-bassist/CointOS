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

    def test_rare_silly_pool(self):
        class DefinitelySilly:
            def random(self): return 0.01
            def choice(self, values): return values[0]
        with tempfile.TemporaryDirectory() as temporary, patch.object(cli,"ROOT",Path(temporary)):
            (cli.ROOT / "state/jobs").mkdir(parents=True)
            self.assertEqual(assign("worker",DefinitelySilly()),"Journathan")
