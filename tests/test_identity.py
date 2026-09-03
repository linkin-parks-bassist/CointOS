import tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from ecosystem import cli
from ecosystem.identity import validate

class IdentityTest(unittest.TestCase):
    def test_assigns_role_name(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(cli,"ROOT",Path(temporary)):
            (cli.ROOT / "state/jobs").mkdir(parents=True)
            self.assertEqual(validate("Rob"),"Rob")

    def test_generated_silly_name_is_valid(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(cli,"ROOT",Path(temporary)):
            (cli.ROOT / "state/jobs").mkdir(parents=True)
            self.assertEqual(validate("Journathan"),"Journathan")
