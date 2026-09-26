import copy
import threading
import unittest
from unittest.mock import patch

from cointos import state


class Persistence(unittest.TestCase):
    def test_a_newer_save_cannot_overtake_an_older_write(self):
        previous = copy.deepcopy(state.L)
        first_writing = threading.Event()
        release_first = threading.Event()
        second_attempting = threading.Event()
        written = []

        def write(path, value):
            if value["value"] == "old":
                first_writing.set()
                release_first.wait(2)
            written.append(value["value"])

        def newer():
            second_attempting.set()
            with state.LOCK:
                state.L["value"] = "new"
            state.save()

        state.L.clear()
        state.L["value"] = "old"
        first = threading.Thread(target=state.save)
        second = threading.Thread(target=newer)
        try:
            with patch.object(state.configuration, "write_json", side_effect=write):
                first.start()
                self.assertTrue(first_writing.wait(1))
                second.start()
                self.assertTrue(second_attempting.wait(1))
                # The second writer must be unable to finish while the first is writing.
                second.join(0.1)
                self.assertTrue(second.is_alive())
                release_first.set()
                first.join(2)
                second.join(2)
            self.assertEqual(written, ["old", "new"])
        finally:
            release_first.set()
            first.join(2)
            if second.ident is not None:
                second.join(2)
            state.L.clear()
            state.L.update(previous)
