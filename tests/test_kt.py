"""Generated leaves are replaced exactly, however much they grow."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from cointos import kt


@unittest.skipUnless(shutil.which("kt"), "kt is not installed")
class GeneratedLeaves(unittest.TestCase):
    def test_a_generated_leaf_grows_past_the_reconsideration_threshold(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        subprocess.run(["kt", "init", "A scratch tree."], cwd=root, check=True, capture_output=True)
        self.assertTrue(kt.write(root, "what is queued", "Short."))
        self.assertFalse(kt.write(root, "what is queued", "Short."))
        long = " ".join(["word"] * 1500)
        self.assertTrue(kt.write(root, "what is queued", long))
        self.assertTrue(kt.write(root, "what is queued", long + " more"))
        opened = subprocess.run(["kt", "--lean", "open", "local:what/is/queued.md"], cwd=root,
                                capture_output=True, text=True, check=True)
        self.assertEqual(opened.stdout.strip(), long + " more")
