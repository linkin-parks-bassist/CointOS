"""Writing a knowledge-tree answer through the `kt` command. Standalone: the installer uses it too."""
from __future__ import annotations

import re
import subprocess
import hashlib
from pathlib import Path


def prepare(root) -> None:
    """Register an existing checkout tree before its tools enter the write boundary.

    kt add registers unregistered local trees. That administrative write belongs to
    the launcher, not the confined author. Registration keeps ask policy and grants
    no access to other projects; existing policy is left intact by kt.
    """
    root = Path(root).resolve()
    tree = root / '.knowledge'
    if tree.is_dir():
        name = 'root-' + hashlib.sha256(str(tree).encode()).hexdigest()[:12]
        subprocess.run(['kt', 'register', name, str(tree)], cwd=root,
                       check=True, capture_output=True, text=True)


def write(root, question: str, body: str) -> bool:
    """Make the generated local leaf answering `question` in the tree at `root` say exactly
    `body`; returns whether it changed.

    Generated leaves (runtime guides, published queues) are copies of a source of truth, not
    answers an agent maintains, so they are rewritten with `--force`: kt's growth
    reconsideration exists to make editors reconsider a leaf, and a copier cannot."""
    address = "local:" + question.replace(" ", "/") + ".md"
    opened = subprocess.run(["kt", "--lean", "open", address], cwd=root, capture_output=True, text=True)
    if opened.returncode:
        command = ["kt", "add", "--local", question, body]
    elif opened.stdout.strip() == body.strip():
        return False
    else:
        revision = re.search(r"Revision: ([0-9a-f]{64})", opened.stderr)
        if revision is None:
            raise RuntimeError(f"kt did not return a revision for {address}")
        command = ["kt", "rewrite", "--force", "--", address, revision[1], body]
    subprocess.run(command, cwd=root, check=True, capture_output=True, text=True)
    return True
