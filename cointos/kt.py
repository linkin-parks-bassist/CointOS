"""Writing a knowledge-tree answer through the `kt` command. Standalone: the installer uses it too."""
from __future__ import annotations

import re
import subprocess


def write(root, question: str, body: str) -> bool:
    """Make the generated local leaf answering `question` in the tree at `root` say exactly
    `body`; returns whether it changed.

    Generated leaves (runtime guides, published queues) are copies of a source of truth, not
    answers an agent maintains, so they are replaced rather than rewritten: kt's growth
    reconsideration exists to make editors reconsider a leaf, and a copier cannot."""
    address = "local:" + question.replace(" ", "/") + ".md"
    opened = subprocess.run(["kt", "--lean", "open", address], cwd=root, capture_output=True, text=True)
    if not opened.returncode:
        if opened.stdout.strip() == body.strip():
            return False
        revision = re.search(r"Revision: ([0-9a-f]{64})", opened.stderr)
        if revision is None:
            raise RuntimeError(f"kt did not return a revision for {address}")
        subprocess.run(["kt", "rm", "--expect", revision[1], address], cwd=root, check=True, capture_output=True, text=True)
    subprocess.run(["kt", "add", "--local", question, body], cwd=root, check=True, capture_output=True, text=True)
    return True
