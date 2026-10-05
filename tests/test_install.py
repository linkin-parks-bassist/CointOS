import json
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest import mock

from cointos import config


INSTALL = Path(__file__).resolve().parents[1] / "scripts/install"


class LiveInstallBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.script = runpy.run_path(str(INSTALL), run_name="cointos_install_test")
        self.install = self.script["install"]
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        target = Path(self.temporary.name) / ".CointOS"
        target.mkdir()
        (target / ".runtime-install").write_text("test\n")
        self.install.__globals__["target"] = target
        self.target = target

    def write_installed_config(self, value):
        path = self.target / "config/cointos.json"
        path.parent.mkdir()
        path.write_text(json.dumps(value))

    def test_process_identity_drift_is_rejected_before_daemon_contact(self):
        installed = config.load()
        installed["port"] += 1
        self.write_installed_config(installed)

        with mock.patch("urllib.request.urlopen") as contact, mock.patch.object(
                self.install.__globals__["subprocess"], "run") as systemd:
            with self.assertRaisesRegex(SystemExit, r"preserved-process configuration changed \(port\)"):
                self.install(live=True)

        contact.assert_not_called()
        systemd.assert_not_called()

    def test_missing_installed_config_is_rejected_before_daemon_contact(self):
        with mock.patch("urllib.request.urlopen") as contact, mock.patch.object(
                self.install.__globals__["subprocess"], "run") as systemd:
            with self.assertRaisesRegex(SystemExit, "installed runtime configuration is unavailable"):
                self.install(live=True)

        contact.assert_not_called()
        systemd.assert_not_called()

    def test_daemon_changes_are_detected_and_projects_ignored(self):
        changed = self.install.__globals__["daemon_changed"]
        source = self.install.__globals__["source"]
        for part in ("cointos", "config", "systemd"):
            import shutil
            shutil.copytree(source / part, self.target / part, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        (self.target / "config/projects.json").write_text("[]")
        self.assertFalse(changed(), "an identical daemon with different enrollment needs no restart")
        (self.target / "cointos/state.py").write_text("# older\n")
        self.assertTrue(changed())

    def test_an_interrupted_drain_releases_the_daemon(self):
        calls = []

        def api(url, action, body=None):
            calls.append(action)
            if action == "prepare-restart":
                raise KeyboardInterrupt
            return {"ok": True}

        with mock.patch.dict(self.install.__globals__, api=api):
            with self.assertRaises(KeyboardInterrupt):
                self.install.__globals__["drain"]("http://x/api/ledger", 60)
        self.assertEqual(calls, ["prepare-restart", "cancel-restart"])


if __name__ == "__main__":
    unittest.main()
