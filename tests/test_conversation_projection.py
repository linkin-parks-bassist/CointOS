import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ecosystem import cli, conversation as conv


def with_root(function):
    def run():
        with tempfile.TemporaryDirectory() as t, patch.object(cli, "ROOT", Path(t)):
            function(Path(t))
    run.__name__ = function.__name__
    return run


@with_root
def test_projection_carries_id_state_sender_and_untouched_history(_root):
    def lifecycle_for(turn_id):
        return {"lifecycle": "closed"} if turn_id == "telegram-9" else {"lifecycle": "open"}
    # seeded via append (v2 rows); v1 row has no reply_to
    conv.append(7, "user", "first", source_id="telegram-9")
    conv.append(7, "assistant", "second", source_id="telegram-10", reply_to="telegram-9")
    rows = conv.recent_state(7, lifecycle_for)
    assert [r["id"] for r in rows] == ["telegram-9", "telegram-10"]
    assert [r["lifecycle"] for r in rows] == ["closed", "open"]
    assert rows[1]["reply_to"] == "telegram-9"
    assert rows[0]["sender"] == 7 and rows[1]["provenance"]["kind"] == "assistant"


def load_tests(loader, tests, pattern):
    fns = [v for n, v in globals().items() if n.startswith("test_") and callable(v)]
    return unittest.TestSuite(unittest.FunctionTestCase(f) for f in fns)
