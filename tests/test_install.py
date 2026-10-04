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


if __name__ == "__main__":
    unittest.main()
