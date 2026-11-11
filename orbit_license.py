"""First-run acceptance for the bundled Orbit Tabs desktop app."""
import hashlib
import math
from pathlib import Path
import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QProgressBar, QTextBrowser, QVBoxLayout,
)

from orbit_common import read_config, save_config
from orbit_theme import SLOGAN, highlight_style, license_styles, orbit_icon

LICENSE = Path(__file__).with_name("LICENSE.md")
ACCEPTANCE_KEY = "accepted_license_sha256"
READ_SECONDS = 10


class LicenseDialog(QDialog):
    def __init__(self, text, parent=None, *, preview=False, dark=False, accent="Blue", theme_name="Adwaita"):
        super().__init__(parent)
        self.dark = dark
        self.accent = accent
        self.theme_name = theme_name
        self.setStyleSheet(license_styles(dark, accent, theme_name))
        self.setWindowTitle("Orbit Tabs · Student License")
        self.setWindowIcon(orbit_icon())
        self.resize(690, 640)
        self.setMinimumSize(470, 430)
        self.deadline = time.monotonic() + READ_SECONDS
        self.last_second = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(10)
        header = QHBoxLayout()
        header.setSpacing(14)
        icon = QLabel()
        icon.setPixmap(orbit_icon().pixmap(52, 52))
        header.addWidget(icon)
        titles = QVBoxLayout()
        titles.setSpacing(1)
        heading = QLabel("Orbit Tabs Student License")
        heading.setObjectName("licenseTitle")
        titles.addWidget(heading)
        slogan = QLabel(SLOGAN)
        slogan.setObjectName("licenseSlogan")
        titles.addWidget(slogan)
        header.addLayout(titles, 1)
        layout.addLayout(header)
        layout.addSpacing(4)

        self.highlights = []
        for label in (
            "Authorized use • Follow platform, institutional, and assessment rules.",
            "Student permission • Use and modify for free, with credit to calamityCocoa.",
            "Staff condition • Read the college-staff restriction and the Steven exception.",
        ):
            highlight = QLabel(label)
            highlight.setWordWrap(True)
            layout.addWidget(highlight)
            self.highlights.append(highlight)
        license_text = QTextBrowser()
        license_text.setAccessibleName("Full Orbit Tabs Student License")
        license_text.setOpenLinks(False)
        license_text.setMarkdown(text)
        layout.addWidget(license_text, 1)

        self.eligibility = QCheckBox("I confirm that I’m eligible to use the app under this license.")
        layout.addWidget(self.eligibility)
        self.countdown = QLabel()
        self.countdown.setObjectName("licenseCountdown")
        self.countdown.setAccessibleName("License reading countdown")
        layout.addWidget(self.countdown)
        self.progress = QProgressBar()
        self.progress.setRange(0, READ_SECONDS)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)
        buttons = QDialogButtonBox()
        decline = buttons.addButton("Close preview" if preview else "Decline", QDialogButtonBox.ButtonRole.RejectRole)
        self.agree = buttons.addButton("Test acceptance" if preview else "Accept and continue",
                                       QDialogButtonBox.ButtonRole.AcceptRole)
        self.agree.setDefault(False)
        self.agree.setProperty("primary", True)
        decline.setDefault(True)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
        self.eligibility.toggled.connect(self.update_countdown)
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.update_countdown)
        self.timer.start()
        self.update_countdown()

    def update_countdown(self):
        seconds = max(0, math.ceil(self.deadline - time.monotonic()))
        if seconds != self.last_second:
            self.last_second = seconds
            self.progress.setValue(READ_SECONDS - seconds)
            self.countdown.setText(f"Review the terms · {seconds} s remaining" if seconds else
                                   "You can accept once you confirm eligibility.")
            for label, threshold in zip(self.highlights, (6, 3, 1)):
                label.setStyleSheet(highlight_style(seconds <= threshold, self.dark, self.accent, self.theme_name))
        self.agree.setEnabled(seconds == 0 and self.eligibility.isChecked())
        if seconds == 0:
            self.timer.stop()

    def accept(self):
        if time.monotonic() >= self.deadline and self.eligibility.isChecked():
            super().accept()


def review_license(settings_path=None, *, parent=None, preview=False, dark=None, accent=None, theme_name=None):
    raw = LICENSE.read_bytes()
    fingerprint = hashlib.sha256(raw).hexdigest()
    config = read_config(settings_path) if settings_path is not None else {}
    if not preview and config.get(ACCEPTANCE_KEY) == fingerprint:
        return True
    dark = config.get("dark_theme", False) if dark is None else dark
    accent = config.get("accent", "Blue") if accent is None else accent
    theme_name = config.get("theme", "Adwaita") if theme_name is None else theme_name
    dialog = LicenseDialog(raw.decode("utf-8"), parent, preview=preview, dark=dark, accent=accent,
                           theme_name=theme_name)
    accepted = dialog.exec() == QDialog.DialogCode.Accepted
    if accepted and not preview and settings_path is not None:
        config[ACCEPTANCE_KEY] = fingerprint
        save_config(settings_path, config)
    return accepted
