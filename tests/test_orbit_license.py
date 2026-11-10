import hashlib
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

try:
    from PySide6.QtWidgets import QApplication, QDialog
    import orbit_license as license_ui
except ImportError:
    license_ui = None

APP = None


@unittest.skipUnless(license_ui and (os.name == "nt" or os.environ.get("DISPLAY")
                                    or os.environ.get("WAYLAND_DISPLAY") or os.sys.platform == "darwin"),
                     "Requires Qt and a graphical session")
class LicenseDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global APP
        APP = QApplication.instance() or QApplication([])

    def test_countdown_highlights_and_eligibility(self):
        dialog = license_ui.LicenseDialog("# Test license")
        try:
            dialog.eligibility.setChecked(True)
            self.assertFalse(dialog.agree.isEnabled())
            dialog.accept()
            self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)

            dialog.deadline = time.monotonic() + 2.5
            dialog.update_countdown()
            self.assertIn("background:", dialog.highlights[0].styleSheet())
            self.assertIn("background:", dialog.highlights[1].styleSheet())
            self.assertNotIn("background:", dialog.highlights[2].styleSheet())

            dialog.eligibility.setChecked(False)
            dialog.deadline = time.monotonic() - 1
            dialog.update_countdown()
            self.assertFalse(dialog.agree.isEnabled())
            self.assertIn("background:", dialog.highlights[2].styleSheet())
            dialog.eligibility.setChecked(True)
            self.assertTrue(dialog.agree.isEnabled())
            dialog.agree.click()
            self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        finally:
            dialog.timer.stop()
            dialog.close()

    def test_versioned_acceptance_and_preview(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            license_path, settings_path = root / "LICENSE.md", root / "settings.json"
            license_path.write_bytes(b"Version 1")
            with patch.object(license_ui, "LICENSE", license_path), patch.object(license_ui, "LicenseDialog") as dialog:
                dialog.return_value.exec.return_value = QDialog.DialogCode.Rejected
                self.assertFalse(license_ui.review_license(settings_path))
                self.assertFalse(settings_path.exists())

                dialog.return_value.exec.return_value = QDialog.DialogCode.Accepted
                self.assertTrue(license_ui.review_license(settings_path, preview=True))
                self.assertFalse(settings_path.exists())
                self.assertTrue(license_ui.review_license(settings_path))
                saved = license_ui.read_config(settings_path)
                self.assertEqual(saved[license_ui.ACCEPTANCE_KEY], hashlib.sha256(b"Version 1").hexdigest())
                self.assertTrue(license_ui.review_license(settings_path))
                self.assertEqual(dialog.call_count, 3)

                license_path.write_bytes(b"Version 2")
                dialog.return_value.exec.return_value = QDialog.DialogCode.Rejected
                self.assertFalse(license_ui.review_license(settings_path))
                self.assertEqual(dialog.call_count, 4)
