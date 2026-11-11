"""Quick Start walkthrough, completion state and Miso's hints."""
import json
import os
import tempfile
import unittest
from pathlib import Path

from orbit_common import read_config

try:
    from PySide6.QtCore import QPoint, QRect, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QDialog, QLabel, QMainWindow

    import orbit_guide as guide_module
    from orbit_guide import (GUIDE_VERSION, STEPS, MisoHint, QuickStartGuide, choose_hint, needs_quick_start,
                             record_quick_start)
    from orbit_theme import THEMES, tokens
except ImportError:
    guide_module = None

GRAPHICAL = os.name == "nt" or os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY") or os.sys.platform == "darwin"


@unittest.skipUnless(guide_module, "Requires PySide6")
class CompletionStateTests(unittest.TestCase):
    def test_first_launch_and_existing_profiles(self):
        self.assertTrue(needs_quick_start({}))
        # Profiles that only dismissed the old message box see the new tour once.
        self.assertTrue(needs_quick_start({"quick_start_seen": True}))
        self.assertTrue(needs_quick_start({"quick_start": "corrupt"}))

    def test_skip_then_replay(self):
        settings = {}
        record_quick_start(settings, completed=False, step=1)
        self.assertFalse(needs_quick_start(settings))
        self.assertEqual(settings["quick_start"], {"version": GUIDE_VERSION, "completed": False, "last_step": 1})
        self.assertTrue(settings["quick_start_seen"])
        record_quick_start(settings, completed=True, step=len(STEPS) - 1)
        record_quick_start(settings, completed=False, step=2)
        # Skipping a replay never forgets that the tour was finished.
        self.assertTrue(settings["quick_start"]["completed"])

    def test_older_tour_version_is_shown_again(self):
        self.assertTrue(needs_quick_start({"quick_start": {"version": GUIDE_VERSION - 1, "completed": True}}))


@unittest.skipUnless(guide_module, "Requires PySide6")
class HintChoiceTests(unittest.TestCase):
    def test_waiting_for_a_question_needs_the_wall_and_some_patience(self):
        idle = [("idle", "", False, 45), ("idle", "", True, 45)]
        self.assertEqual(choose_hint(idle, on_wall=True, dismissed=set()), "waiting_question")
        self.assertIsNone(choose_hint(idle, on_wall=False, dismissed=set()))
        self.assertIsNone(choose_hint([("idle", "", False, 5)], on_wall=True, dismissed=set()))
        self.assertIsNone(choose_hint([], on_wall=True, dismissed=set()))
        self.assertIsNone(choose_hint(idle, on_wall=True, dismissed={"waiting_question"}))

    def test_course_qa_wait_reasons(self):
        reasons = {
            "The free AI endpoint is rate-limited. Retrying in 46 seconds…": "rate_limited",
            "Waiting for the course to enable Submit. Orbit controls when it becomes available.": "submit_locked",
            "Waiting for the delay set in Orbit Tabs. 06:59:59 remaining.": "plan_delay",
            "Waiting for the course to make step 2 available…": "step_missing",
        }
        for reason, key in reasons.items():
            tabs = [("waiting", reason, True, 60), ("idle", "", False, 60)]
            self.assertEqual(choose_hint(tabs, on_wall=True, dismissed=set()), key)
            # An active tab means the wall is not idle, so the launch-screen hint stays away.
            self.assertIsNone(choose_hint(tabs, on_wall=True, dismissed={key}))

    def test_user_triggered_hint_comes_first(self):
        tabs = [("waiting", "rate-limited", True, 60)]
        self.assertEqual(choose_hint(tabs, on_wall=True, dismissed=set(), event="qa_needs_course"), "qa_needs_course")
        self.assertEqual(choose_hint(tabs, on_wall=True, dismissed={"qa_needs_course"}, event="qa_needs_course"),
                         "rate_limited")


@unittest.skipUnless(guide_module and GRAPHICAL, "Requires PySide6 and a graphical session")
class WalkthroughTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = QMainWindow()
        self.window.resize(1200, 780)
        self.window.show()
        self.motion = True
        self.guide = QuickStartGuide(self.window, tokens(), motion_allowed=lambda: self.motion)
        self.results = []
        self.guide.finished.connect(self.results.append)

    def tearDown(self):
        self.guide.close()
        self.guide.deleteLater()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def key(self, key, modifier=Qt.KeyboardModifier.NoModifier):
        QTest.keyClick(self.app.focusWidget() or self.guide, key, modifier)
        # Button mnemonics (Alt+B, Alt+N) click through animateClick(), which lands a moment later.
        QTest.qWait(160 if modifier == Qt.KeyboardModifier.AltModifier else 0)
        self.app.processEvents()

    def start(self, step=0):
        self.guide.start(step)
        self.guide.activateWindow()
        QTest.qWaitForWindowActive(self.guide, 2000)
        self.app.processEvents()

    def test_keyboard_navigation_and_finish(self):
        self.start()
        self.assertIs(self.app.focusWidget(), self.guide.next_button)
        self.assertFalse(self.guide.back_button.isEnabled())
        self.key(Qt.Key.Key_Left)
        self.assertEqual(self.guide.index, 0)
        self.key(Qt.Key.Key_Right)
        self.assertEqual(self.guide.index, 1)
        self.key(Qt.Key.Key_Return)
        self.assertEqual(self.guide.index, 2)
        self.key(Qt.Key.Key_B, Qt.KeyboardModifier.AltModifier)
        self.assertEqual(self.guide.index, 1)
        self.key(Qt.Key.Key_N, Qt.KeyboardModifier.AltModifier)
        self.assertEqual(self.guide.index, 2)
        # Tab reaches every footer control.
        reached = set()
        for _ in range(12):
            self.key(Qt.Key.Key_Tab)
            reached.add(self.app.focusWidget())
        self.assertTrue({self.guide.skip_button, self.guide.back_button, self.guide.next_button} <= reached)
        for _ in range(len(STEPS) + 2):
            self.key(Qt.Key.Key_Right)
        # The arrow key stops on the last step; only Enter or Finish completes the tour.
        self.assertEqual(self.guide.index, len(STEPS) - 1)
        self.assertTrue(self.guide.isVisible())
        self.assertEqual(self.guide.next_button.text(), "&Finish")
        self.assertFalse(self.guide.skip_button.isVisible())
        self.guide.next_button.setFocus()
        self.key(Qt.Key.Key_Return)
        self.assertEqual(self.results, [QDialog.DialogCode.Accepted])

    def test_escape_and_skip_button_skip(self):
        self.start(2)
        self.key(Qt.Key.Key_Escape)
        self.assertEqual(self.results, [QDialog.DialogCode.Rejected])
        self.start()
        self.assertEqual(self.guide.index, 0)
        self.guide.skip_button.click()
        self.assertEqual(self.results[-1], QDialog.DialogCode.Rejected)

    def test_every_step_names_what_people_will_see(self):
        self.start()
        text = []
        for index in range(len(STEPS)):
            self.guide.go(index)
            text.append(" ".join(widget.text() for widget in self.guide.pages.currentWidget().findChildren(QLabel)))
            text.append(" ".join(chip.text() for chip in self.guide.pages.currentWidget().findChildren(
                guide_module.QToolButton, "guideChip")))
        everything = " ".join(text)
        for name in ("Check now", "Monitor wall", "My Learning", "Waiting for a question", "Start", "Resume",
                     "Course QA", "Prepare answers", "Suggest & apply", "Finish now…", "Add submit", "Run plan",
                     "Pollinations", "Wikipedia", "Enable hosted AI suggestions", "Quick Start", "rate-limited",
                     "enable Submit", "STANDBY", "ANSWERING", "WAITING"):
            self.assertIn(name, everything)

    def test_small_window_fits_without_horizontal_scrolling(self):
        self.window.resize(640, 410)
        self.app.processEvents()
        self.start(1)
        frame = self.window.geometry()
        self.assertTrue(self.guide.compact)
        self.assertTrue(frame.contains(self.guide.geometry()), (frame, self.guide.geometry()))
        for index in range(len(STEPS)):
            self.guide.go(index)
            self.app.processEvents()
            page = self.guide.pages.currentWidget()
            self.assertLessEqual(page.widget().minimumSizeHint().width(), page.viewport().width(), index)
            self.assertEqual(page.horizontalScrollBar().maximum(), 0)
        self.window.resize(1200, 780)
        self.app.processEvents()
        self.assertFalse(self.guide.compact)

    def test_light_dark_and_catppuccin_themes(self):
        self.start(1)
        for name in THEMES:
            for dark in (False, True):
                theme = tokens(dark, "Mint", name)
                self.guide.apply_theme(theme)
                self.app.processEvents()
                self.assertIn(theme["bg"], self.guide.styleSheet())
                self.assertEqual(self.guide.index, 1)
                self.assertFalse(self.guide.grab().isNull())

    def test_reduce_motion_and_hidden_window(self):
        self.motion = False
        self.start()
        self.assertFalse(self.guide.orbit())
        self.assertEqual(self.guide.motion.state().name, "Stopped")
        self.motion = True
        self.assertTrue(self.guide.orbit())
        self.assertEqual(self.guide.motion.state().name, "Running")
        self.window.showMinimized()
        self.app.processEvents()
        self.window.hide()
        self.app.processEvents()
        self.assertEqual(self.guide.motion.state().name, "Stopped")
        self.assertIsNone(self.guide.title.orbit_angle)

    def test_hint_is_dismissible(self):
        hint = MisoHint()
        hint.apply_theme(tokens(True))
        dismissed, shown = [], []
        hint.dismissed.connect(dismissed.append)
        hint.show_me.connect(shown.append)
        hint.present("waiting_question")
        self.assertIn("launch screen", hint.text.text())
        hint.action.click()
        self.assertEqual(shown, [2])
        hint.close_button.click()
        self.assertEqual(dismissed, ["waiting_question"])
        self.assertTrue(hint.isHidden())
        self.assertEqual(hint.close_button.accessibleName(), "Dismiss hint")


@unittest.skipUnless(guide_module and GRAPHICAL, "Requires PySide6, Qt WebEngine and a graphical session")
class WindowWalkthroughTests(unittest.TestCase):
    """The tour inside the real window, with Orbit pointed at a closed local port."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        import orbit_embedded
        cls.orbit = orbit_embedded

    def test_first_launch_skip_replay_and_hints(self):
        orbit = self.orbit
        saved_origin = orbit.ORIGIN
        orbit.ORIGIN = "http://127.0.0.1:9"
        with tempfile.TemporaryDirectory() as temp:
            settings_path = Path(temp) / "settings.json"
            settings_path.write_text(json.dumps({"quick_start_seen": True, "reduce_motion": True}))
            window = orbit.OrbitWindow(settings_path)
            window.show()
            try:
                self.assertTrue(needs_quick_start(read_config(settings_path)))
                window.show_quick_start()
                tour = window.guide
                self.assertTrue(tour.isVisible())
                self.assertFalse(window.motion_allowed())
                self.assertEqual(tour.motion.state().name, "Stopped")
                QTest.keyClick(tour, Qt.Key.Key_Escape)
                self.app.processEvents()
                state = read_config(settings_path)
                self.assertFalse(needs_quick_start(state))
                self.assertFalse(state["quick_start"]["completed"])
                self.assertIn("Quick Start skipped", window.statusBar().currentMessage())

                replay = next(action for menu in window.menuBar().actions() if menu.menu()
                              for action in menu.menu().actions() if action.text() == "Quick Start")
                tour.go(4)
                replay.trigger()
                self.assertTrue(tour.isVisible())
                self.assertEqual(tour.index, 0)
                tour.go(len(STEPS) - 1)
                tour.next_button.click()
                self.app.processEvents()
                self.assertTrue(read_config(settings_path)["quick_start"]["completed"])
                self.assertIn("Tour complete", window.statusBar().currentMessage())
                self.assertEqual(window.mascot_motion.state().name, "Stopped")

                # Theme changes reach an open tour.
                window.show_quick_start(3)
                window.set_theme("Catppuccin Frappé")
                self.assertIn(tokens(theme_name="Catppuccin Frappé")["bg"], tour.styleSheet())
                self.assertEqual(tour.index, 3)
                tour.reject()

                # Course QA without a course raises a hint; dismissing it is remembered for the profile.
                window.show_wall()
                window.open_qa()
                self.assertEqual(window.hint.key, "qa_needs_course")
                self.assertFalse(window.hint.isHidden())
                window.hint.close_button.click()
                self.assertEqual(read_config(settings_path)["dismissed_hints"], ["qa_needs_course"])
                window.open_qa()
                self.assertTrue(window.hint.isHidden())

                # The hint toggle in the Cats menu silences hints.
                window.settings["dismissed_hints"] = []
                window.hints_action.setChecked(False)
                window.open_qa()
                self.assertTrue(window.hint.isHidden())
                self.assertFalse(read_config(settings_path)["miso_hints"])
            finally:
                orbit.ORIGIN = saved_origin
                window.quit()
                window.dispose()
                window.deleteLater()
                self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
