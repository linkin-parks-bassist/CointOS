"""Recovery preserves unfinished native turns without consuming completed ones."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from cointos import opencode


def user():
    return {"info": {"id": "msg_original", "role": "user", "sessionID": "ses_original",
                     "time": {"created": 123}, "agent": "build", "model": {"providerID": "p", "modelID": "m"}},
            "parts": [{"type": "text", "text": "Original assignment"}]}


class UnfinishedTurnResume(unittest.TestCase):
    def test_model_switch_preserves_pending_turn_identity_and_uses_the_selected_model(self):
        with tempfile.TemporaryDirectory() as temp:
            original = user()
            model = {"providerID": "cointos", "modelID": "new-model"}
            spec = {"text": "Continue.", "session": "ses_original", "task": {"worktree": temp}, "model": model}
            with mock.patch.object(opencode, "session_request", return_value=[original]):
                self.assertTrue(opencode.prepare_resume(Path(temp), "url", spec))
            info = json.loads((Path(temp) / "resume.json").read_text())["info"]
            self.assertEqual(info, {**original["info"], "model": model})
            self.assertEqual(original["info"]["model"]["modelID"], "m")
    def test_pending_input_empty_reply_and_completed_tool_steps_reuse_their_user(self):
        for finish in (None, "tool-calls", "unknown"):
            with self.subTest(finish=finish), tempfile.TemporaryDirectory() as temp:
                original = user()
                messages = [original, {"info": {"role": "assistant", "finish": finish}, "parts": []}]
                spec = {"text": "Continue.", "session": "ses_original", "task": {"worktree": temp}}
                with mock.patch.object(opencode, "session_request", return_value=messages):
                    self.assertTrue(opencode.prepare_resume(Path(temp), "url", spec))
                packet = Path(temp) / "resume.json"
                self.assertEqual(json.loads(packet.read_text()), {"info": original["info"]})
                self.assertEqual(packet.stat().st_mode & 0o777, 0o600)
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(opencode, "session_request", return_value=[user()]):
            self.assertTrue(opencode.prepare_resume(Path(temp), "url", spec))

    def test_completed_answers_and_compaction_do_not_reuse_an_exhausted_turn(self):
        cases = [[user(), {"info": {"role": "assistant", "finish": "stop"}, "parts": []}],
                 [{**user(), "parts": [{"type": "compaction"}]}], []]
        for messages in cases:
            with self.subTest(messages=messages), tempfile.TemporaryDirectory() as temp:
                spec = {"text": "Continue.", "session": "ses_original", "task": {"worktree": temp}}
                with mock.patch.object(opencode, "session_request", return_value=messages):
                    self.assertFalse(opencode.prepare_resume(Path(temp), "url", spec))
                self.assertFalse((Path(temp) / "resume.json").exists())

    def test_reviews_and_reorientation_remain_real_new_messages(self):
        for text in ("The integrator sent your work back", "Paused for several hours"):
            with mock.patch.object(opencode, "session_request") as request:
                self.assertFalse(opencode.prepare_resume(Path("unused"), "url", {"text": text}))
                request.assert_not_called()

    def test_native_hook_preserves_metadata_and_is_scoped_to_one_resume(self):
        with tempfile.TemporaryDirectory() as temp:
            packet = Path(temp) / "resume.json"
            packet.write_text(json.dumps({"info": user()["info"]}))
            module = (Path(opencode.__file__).parent / "opencode_resume.mjs").as_uri()
            script = """
import hook from MODULE;
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
const original = JSON.parse(readFileSync(process.env.COINTOS_RESUME_PACKET, 'utf8')).info;
const hooks = await hook();
const output = {message: {id: 'msg_new', time: {created: 999}, system: 'unwanted'}, parts: [{type: 'text', text: 'Continue.'}]};
await assert.rejects(hooks['chat.message']({sessionID: 'wrong'}, output));
assert.equal(output.message.id, 'msg_new');
await hooks['chat.message']({sessionID: original.sessionID}, output);
assert.deepEqual(output.message, original);
assert.deepEqual(output.parts, []);
const next = {message: {id: 'msg_actual_new'}, parts: [{type: 'text', text: 'New instruction'}]};
await hooks['chat.message']({sessionID: original.sessionID}, next);
assert.equal(next.parts[0].text, 'New instruction');
assert.equal(next.message.id, 'msg_actual_new');
""".replace("MODULE", json.dumps(module))
            subprocess.run(["node", "--input-type=module", "-e", script], check=True,
                           env={**os.environ, "COINTOS_RESUME_PACKET": str(packet)}, capture_output=True)


if __name__ == "__main__":
    unittest.main()
