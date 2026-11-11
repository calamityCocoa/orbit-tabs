"""Miso's Quick Start walkthrough and the small context hints shown in the main window."""
from __future__ import annotations

from pathlib import Path

import shiboken6

from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QRect, QRectF, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QKeySequence, QPainter, QPen, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFrame, QHBoxLayout, QLabel, QLayout, QPushButton, QScrollArea, QSizePolicy, QStackedWidget,
    QToolButton, QVBoxLayout, QWidget, QWidgetItem,
)

from orbit_theme import OrbitTitle, common_styles, line_icon, wall_styles
from orbit_wall import BADGES, QuestionPreview, repolish

MISO_PATH = Path(__file__).resolve().parent / "assets" / "miso-rainbow.png"
# Bump when the tour changes enough that everyone should see it once more.
GUIDE_VERSION = 2
STANDBY = "○ STANDBY"
# The Course QA panel is drawn by the page with these fixed colours in every theme.
QA = {"bg": "#192337", "line": "#536581", "text": "#edf2fb", "muted": "#bdcbe4", "button": "#3a4760"}

_miso_cache: dict[tuple[int, float], QPixmap] = {}


def miso_pixmap(size, ratio=1.0):
    """Return Miso scaled once per size; the source PNG is large."""
    key = (size, round(ratio, 2))
    if key not in _miso_cache:
        source = QPixmap(str(MISO_PATH))
        if source.isNull():
            return QPixmap()
        pixmap = source.scaled(round(size * ratio), round(size * ratio), Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
        pixmap.setDevicePixelRatio(ratio)
        _miso_cache[key] = pixmap
    return _miso_cache[key]


# --- Completion state (stored in the profile's settings file) -------------------------------------

def tour_state(settings):
    state = settings.get("quick_start")
    return state if isinstance(state, dict) else {}


def needs_quick_start(settings):
    """True until this profile has finished or skipped the current tour version."""
    return tour_state(settings).get("version", 0) < GUIDE_VERSION


def record_quick_start(settings, *, completed, step):
    previous = tour_state(settings)
    finished_before = previous.get("version") == GUIDE_VERSION and previous.get("completed", False)
    settings["quick_start"] = {"version": GUIDE_VERSION, "completed": bool(completed or finished_before),
                               "last_step": step}
    # Older builds only know this flag; keep it so they do not show their message box again.
    settings["quick_start_seen"] = True


# --- Context hints --------------------------------------------------------------------------------

HINTS = {
    "rate_limited": ("Pollinations is busy, not broken. Course QA retries on its own in under a minute.", 6),
    "submit_locked": ("Orbit decides when Submit unlocks. Course QA clicks it once the course enables it.", 6),
    "plan_delay": ("That countdown is the delay saved in your plan. Keep Orbit Tabs running, "
                   "or stop the plan in Course QA.", 6),
    "step_missing": ("Course QA is waiting for a control that isn’t on screen. "
                     "Open that course and go to the matching page.", 6),
    "waiting_question": ("“Waiting for a question” usually means the course is still on its launch screen. "
                         "Click a card’s thumbnail, then Start or Resume.", 2),
    "qa_needs_course": ("Course QA works inside a course tab. Click a card’s thumbnail on the Monitor wall first.", 3),
}
# Reasons come from the Course QA status line (orbit-course-qa.user.js).
REASON_HINTS = (
    ("rate-limited", "rate_limited"),
    ("enable Submit", "submit_locked"),
    ("delay set in Orbit Tabs", "plan_delay"),
    ("to make step", "step_missing"),
)
QUESTION_GRACE = 20


def choose_hint(tabs, *, on_wall, dismissed, event=None):
    """Pick the most useful hint for the current state.

    ``tabs`` holds ``(activity, reason, has_questions, seconds_open)`` for each loaded course tab.
    ``event`` is a one-off hint key raised by a user action, such as Course QA without a course.
    """
    candidates = []
    if event:
        candidates.append(event)
    for needle, key in REASON_HINTS:
        if any(activity == "waiting" and needle in reason for activity, reason, *_ in tabs):
            candidates.append(key)
    busy = any(activity != "idle" for activity, *_ in tabs)
    if on_wall and tabs and not busy and any(not questions and age >= QUESTION_GRACE
                                             for _, _, questions, age in tabs):
        candidates.append("waiting_question")
    return next((key for key in candidates if key not in dismissed), None)


class MisoHint(QFrame):
    """A slim, dismissible strip where Miso offers one hint at a time."""

    dismissed = Signal(str)
    show_me = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("misoHint")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setAccessibleName("Hint from Miso")
        self.key = ""
        self.step = 0
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 8, 6)
        layout.setSpacing(10)
        self.icon = QLabel()
        self.icon.setFixedSize(30, 30)
        layout.addWidget(self.icon)
        self.text = QLabel()
        self.text.setObjectName("misoHintText")
        self.text.setWordWrap(True)
        self.text.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.text, 1)
        self.action = QPushButton("Show me")
        self.action.setObjectName("misoHintAction")
        self.action.setToolTip("Open this part of Quick Start")
        self.action.clicked.connect(lambda: self.show_me.emit(self.step))
        layout.addWidget(self.action)
        self.close_button = QToolButton()
        self.close_button.setObjectName("misoHintClose")
        self.close_button.setText("×")
        self.close_button.setToolTip("Dismiss this hint")
        self.close_button.setAccessibleName("Dismiss hint")
        self.close_button.clicked.connect(self.dismiss)
        layout.addWidget(self.close_button)
        self.hide()

    def present(self, key):
        message, self.step = HINTS[key]
        if self.key != key:
            self.key = key
            self.text.setText("Miso: " + message)
            self.setAccessibleDescription(message)
        if self.isHidden():
            self.show()

    def withdraw(self):
        self.key = ""
        self.hide()

    def dismiss(self):
        key = self.key
        self.withdraw()
        if key:
            self.dismissed.emit(key)

    def apply_theme(self, t):
        self.icon.setPixmap(miso_pixmap(30, self.devicePixelRatioF()))
        self.setStyleSheet(f"""
          QFrame#misoHint {{ background: {t['accent_soft']}; border-bottom: 1px solid {t['accent_line']}; }}
          QLabel#misoHintText {{ color: {t['text']}; }}
          QPushButton#misoHintAction {{ padding: 4px 10px; min-height: 16px; }}
          QToolButton#misoHintClose {{ color: {t['muted']}; border: 1px solid transparent; border-radius: 6px;
                                       padding: 0 6px; font-size: 16px; min-height: 22px; }}
          QToolButton#misoHintClose:hover {{ background: {t['hover']}; color: {t['text']}; }}
          QToolButton#misoHintClose:focus {{ border-color: {t['accent']}; }}
        """)


# --- Small building blocks for the walkthrough pages ----------------------------------------------

class FlowLayout(QLayout):
    """Lay chips out left to right and wrap them when the dialog is narrow."""

    def __init__(self, parent=None, spacing=6):
        super().__init__(parent)
        self.items = []
        self.setSpacing(spacing)
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self.items.append(item)

    def addWidget(self, widget):
        self.addChildWidget(widget)
        self.addItem(QWidgetItem(widget))

    def count(self):
        return len(self.items)

    def itemAt(self, index):
        return self.items[index] if 0 <= index < len(self.items) else None

    def takeAt(self, index):
        return self.items.pop(index) if 0 <= index < len(self.items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self.arrange(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self.arrange(rect, apply=True)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self.items:
            size = size.expandedTo(item.minimumSize())
        return size

    def arrange(self, rect, *, apply):
        x, y, line = rect.x(), rect.y(), 0
        gap = self.spacing()
        for item in self.items:
            hint = item.sizeHint()
            if x + hint.width() > rect.right() + 1 and line:
                x, y, line = rect.x(), y + line + gap, 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + gap
            line = max(line, hint.height())
        return y + line - rect.y()


def para(html, name="guideBody"):
    label = QLabel(html)
    label.setObjectName(name)
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.RichText)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
    label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    return label


def chip(t, text, glyph=None, primary=False, shortcut=""):
    """A non-interactive copy of a toolbar button or menu item."""
    button = QToolButton()
    button.setObjectName("guideChip")
    button.setProperty("primary", primary)
    button.setText(text + (f"   {shortcut}" if shortcut else ""))
    button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    button.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    if glyph:
        button.setIcon(line_icon(glyph, t["on_accent"] if primary else t["text"], 16))
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    return button


def chip_row(t, *chips, path=False):
    host = QWidget()
    flow = FlowLayout(host)
    for index, item in enumerate(chips):
        if path and index:
            arrow = QLabel("›")
            arrow.setObjectName("guideSep")
            flow.addWidget(arrow)
        flow.addWidget(item if isinstance(item, QWidget) else chip(t, *item))
    host.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
    return host


def menu_path(t, *names):
    return chip_row(t, ("Menu", "menu"), *((name,) for name in names), path=True)


def badge(state, text=None):
    label = QLabel(text or BADGES.get(state, STANDBY))
    label.setObjectName("tileBadge")
    repolish(label, state if state in BADGES else "idle")
    return label


def card(t, *, name="guideCard", walled=False):
    frame = QFrame()
    frame.setObjectName(name)
    frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
    if walled:
        # Borrow the monitor wall's rules so badges and question cards look exactly as they do there.
        frame.setStyleSheet(wall_styles(t) + f"QLabel#guideBody {{ color: {t['text']}; }}"
                            f"QLabel#guideNote {{ color: {t['muted']}; font-size: 12px; }}"
                            f"QLabel#guideCode {{ color: {t['text']}; }}")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(14, 12, 14, 12)
    layout.setSpacing(8)
    return frame, layout


def launch_screen(t, size, ratio, *, ring=False):
    """Paint a course launch screen with Start and Resume, as seen in a wall thumbnail."""
    width, height = size.width(), size.height()
    pixmap = QPixmap(round(width * ratio), round(height * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(t["preview"]))
    painter.setPen(QPen(QColor(t["accent"] if ring else t["line"]), 2 if ring else 1))
    painter.drawRoundedRect(QRectF(1, 1, width - 2, height - 2), 7, 7)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(t["subtle"]))
    painter.drawRoundedRect(QRectF(width * .1, height * .18, width * .58, height * .09), 3, 3)
    painter.setBrush(QColor(t["line"]))
    painter.drawRoundedRect(QRectF(width * .1, height * .34, width * .4, height * .07), 3, 3)
    pills = ((QRectF(width * .1, height * .56, width * .3, height * .22), "Start", True),
             (QRectF(width * .44, height * .56, width * .34, height * .22), "Resume", False))
    font = QFont(painter.font())
    font.setPixelSize(max(6, round(height * .12)))
    font.setBold(True)
    painter.setFont(font)
    for rect, label, filled in pills:
        painter.setBrush(QColor(t["accent"]) if filled else Qt.BrushStyle.NoBrush)
        painter.setPen(Qt.PenStyle.NoPen if filled else QPen(QColor(t["accent"]), 1.2))
        painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        if font.pixelSize() >= 9:
            painter.setPen(QColor(t["on_accent"] if filled else t["accent"]))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)
    painter.end()
    return pixmap


def mock_tile(t, ratio, *, title="Workplace Safety 101", ring=False):
    """A monitor-wall card in its resting state, built from the real QuestionPreview."""
    tile, layout = card(t, name="orbitTile", walled=True)
    header = QHBoxLayout()
    name = QLabel(title)
    name.setObjectName("guideCode")
    name.setStyleSheet("font-weight: 600;")
    header.addWidget(name, 1)
    mini = QLabel()
    mini.setPixmap(launch_screen(t, QSize(104, 59), ratio, ring=ring))
    mini.setToolTip("Live browser view")
    header.addWidget(mini)
    layout.addLayout(header)
    question = QuestionPreview()
    question.set_effects(False)
    question.set_snapshot({})
    question.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    for button in (question.previous, question.next):
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    question.setMinimumHeight(120)
    layout.addWidget(question)
    footer = QHBoxLayout()
    footer.addWidget(badge("idle"))
    footer.addStretch(1)
    elapsed = QLabel("00:14:32")
    elapsed.setObjectName("tileElapsed")
    footer.addWidget(elapsed)
    layout.addLayout(footer)
    return tile


def qa_panel():
    """A copy of the Course QA panel that appears inside a course page."""
    panel = QFrame()
    panel.setObjectName("qaPanel")
    panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(14, 12, 14, 12)
    layout.setSpacing(7)
    title = QLabel("Orbit Course QA")
    title.setObjectName("qaTitle")
    layout.addWidget(title)

    def buttons(*names):
        host = QWidget()
        flow = FlowLayout(host, 5)
        for text in names:
            label = QLabel(text)
            label.setObjectName("qaButton")
            flow.addWidget(label)
        return host

    layout.addWidget(buttons("Prepare answers", "Suggest & apply", "Finish now…"))
    hint = QLabel("Prepare for review, or apply suggestions together. Finish now needs separate permission.")
    hint.setObjectName("qaHint")
    hint.setWordWrap(True)
    layout.addWidget(hint)
    plan = QLabel("Answer plan")
    plan.setObjectName("qaPlan")
    plan.setMinimumHeight(38)
    plan.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    layout.addWidget(plan)
    layout.addWidget(buttons("Inspect", "Preview", "Reveal lesson text", "Add submit", "Run plan"))
    return panel


def guide_styles(t, compact):
    return common_styles(t) + f"""
      QDialog#quickStart {{ background: {t['bg']}; }}
      QWidget#guidePage {{ background: transparent; }}
      QScrollArea#guideScroll {{ background: {t['bg']}; border: 0; }}
      QScrollArea#guideScroll:focus {{ border: 1px solid {t['accent_line']}; }}
      QFrame#guideHeader {{ background: {t['surface']}; border-bottom: 1px solid {t['line']}; }}
      QFrame#guideFooter {{ background: {t['surface']}; border-top: 1px solid {t['line']}; }}
      QLabel#guideStep {{ color: {t['muted']}; font-size: 11px; font-weight: 600; }}
      QLabel#guideTitle {{ color: {t['text']}; font-size: {16 if compact else 19}px; font-weight: 700; }}
      QFrame#guideSpeech {{ background: {t['accent_soft']}; border: 1px solid {t['accent_line']}; border-radius: 12px; }}
      QLabel#guideSpeechText {{ color: {t['text']}; background: transparent; }}
      QLabel#guideBody {{ color: {t['text']}; }}
      QLabel#guideNote {{ color: {t['muted']}; font-size: 12px; }}
      QLabel#guideCode {{ color: {t['text']}; }}
      QLabel#guideSep {{ color: {t['subtle']}; padding: 4px 0; }}
      QFrame#guideCard {{ background: {t['surface']}; border: 1px solid {t['line']}; border-radius: 12px; }}
      QFrame#guideCard[tone="key"] {{ border: 1px solid {t['accent_line']}; background: {t['accent_soft']}; }}
      QToolButton#guideChip {{ background: {t['raised']}; color: {t['text']}; border: 1px solid {t['line']};
                               border-radius: 8px; padding: 4px 9px; }}
      QToolButton#guideChip[primary="true"] {{ background: {t['accent']}; color: {t['on_accent']};
                                               border-color: {t['accent']}; font-weight: 600; }}
      QFrame#guideDot {{ background: {t['line']}; border-radius: 3px; min-width: 6px; max-width: 6px;
                         min-height: 6px; max-height: 6px; }}
      QFrame#guideDot[state="done"] {{ background: {t['accent_line']}; }}
      QFrame#guideDot[state="current"] {{ background: {t['accent']}; min-width: 18px; max-width: 18px; }}
      QPushButton#guideSkip {{ background: transparent; border-color: transparent; color: {t['muted']}; }}
      QPushButton#guideSkip:hover {{ background: {t['hover']}; color: {t['text']}; }}
      QPushButton#guideSkip:focus {{ border-color: {t['accent']}; }}
      QFrame#qaPanel {{ background: {QA['bg']}; border: 1px solid {QA['line']}; border-radius: 12px; }}
      QLabel#qaTitle {{ color: {QA['text']}; font-weight: 700; font-size: 15px; }}
      QLabel#qaButton {{ color: {QA['text']}; background: {QA['button']}; border: 1px solid {QA['line']};
                         border-radius: 4px; padding: 2px 7px; }}
      QLabel#qaHint {{ color: {QA['muted']}; font-size: 12px; }}
      QLabel#qaPlan {{ color: {QA['muted']}; background: #111827; border: 1px solid {QA['line']}; border-radius: 6px;
                       padding: 6px 8px; font-size: 12px; }}
      QLabel#consentTitle {{ color: {t['text']}; font-weight: 700; }}
    """


# --- The walkthrough -------------------------------------------------------------------------------

STEPS = (
    ("Find your courses", "Hi, I’m Miso, your co-pilot. Seven quick stops, then you’re cleared for launch."),
    ("Open isn’t the same as answering", "10 open, 0 answering? Nothing’s stuck. Nobody answers until you ask."),
    ("Get to a quiz", "Paws on the thumbnail. That’s the door to the full course."),
    ("Open Course QA", "Course QA lives inside the course tab, like me in a cardboard box."),
    ("Prepare, apply, submit", "Three buttons, three jobs. Only one of them hands in your work."),
    ("When questions leave your computer", "Nothing leaves without your yes."),
    ("What the waits mean", "Waiting usually means someone else is holding the door. That’s the tour!"),
)


class QuickStartGuide(QDialog):
    """A short, skippable tour narrated by Miso. ``finished`` reports Accepted only when completed."""

    def __init__(self, parent, theme, *, motion_allowed=lambda: True, hints_action=None):
        super().__init__(parent)
        self.setObjectName("quickStart")
        self.setWindowTitle("Orbit Tabs Quick Start")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setSizeGripEnabled(False)
        self.theme = theme
        self.motion_allowed = motion_allowed
        self.hints_action = hints_action
        self.index = 0
        self.compact = False
        self.built_for = None
        self.miso_size = 0

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        header = QFrame()
        header.setObjectName("guideHeader")
        self.header_layout = QHBoxLayout(header)
        self.header_layout.setSpacing(14)
        self.miso = QLabel()
        self.miso.setAccessibleName("Miso, the rainbow astronaut cat")
        self.miso.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.header_layout.addWidget(self.miso, 0, Qt.AlignmentFlag.AlignTop)
        words = QVBoxLayout()
        words.setSpacing(3)
        self.step_label = QLabel()
        self.step_label.setObjectName("guideStep")
        words.addWidget(self.step_label)
        self.title = OrbitTitle("")
        self.title.setObjectName("guideTitle")
        self.title.setContentsMargins(0, 0, 0, 0)
        self.title.setMinimumHeight(34)
        words.addWidget(self.title)
        # Padding lives on the bubble frame: QLabel's height-for-width ignores style-sheet padding.
        bubble = QFrame()
        bubble.setObjectName("guideSpeech")
        self.bubble_layout = QHBoxLayout(bubble)
        self.speech = QLabel()
        self.speech.setObjectName("guideSpeechText")
        self.speech.setWordWrap(True)
        self.speech.setTextFormat(Qt.TextFormat.RichText)
        self.speech.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.bubble_layout.addWidget(self.speech)
        words.addWidget(bubble)
        self.header_layout.addLayout(words, 1)
        root.addWidget(header)

        self.pages = QStackedWidget()
        root.addWidget(self.pages, 1)

        footer = QFrame()
        footer.setObjectName("guideFooter")
        bar = QHBoxLayout(footer)
        bar.setContentsMargins(14, 10, 14, 10)
        bar.setSpacing(8)
        self.skip_button = QPushButton("S&kip tour")
        self.skip_button.setObjectName("guideSkip")
        self.skip_button.setAutoDefault(False)
        self.skip_button.setToolTip("Close the tour (Esc). Replay it from Menu › Orbit › Quick Start.")
        self.skip_button.clicked.connect(self.reject)
        bar.addWidget(self.skip_button)
        bar.addStretch(1)
        self.dots = []
        dots = QHBoxLayout()
        dots.setSpacing(5)
        for _ in STEPS:
            dot = QFrame()
            dot.setObjectName("guideDot")
            dots.addWidget(dot)
            self.dots.append(dot)
        bar.addLayout(dots)
        bar.addStretch(1)
        self.back_button = QPushButton("&Back")
        self.back_button.setAutoDefault(False)
        self.back_button.setToolTip("Previous step (←)")
        self.back_button.clicked.connect(self.back)
        bar.addWidget(self.back_button)
        self.next_button = QPushButton("&Next")
        self.next_button.setProperty("primary", True)
        self.next_button.setDefault(True)
        self.next_button.clicked.connect(self.advance)
        bar.addWidget(self.next_button)
        root.addWidget(footer)

        QShortcut(QKeySequence(Qt.Key.Key_Right), self, self.forward)
        QShortcut(QKeySequence(Qt.Key.Key_Left), self, self.back)

        self.motion = QVariantAnimation(self)
        self.motion.setDuration(1250)
        self.motion.setStartValue(0.0)
        self.motion.setEndValue(360.0)
        self.motion.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.motion.valueChanged.connect(self.title.set_orbit_angle)
        self.motion.finished.connect(lambda: self.title.set_orbit_angle(None))
        if parent is not None:
            parent.window().installEventFilter(self)

    # Navigation ------------------------------------------------------------------------------------
    def start(self, step=0):
        self.fit()
        self.rebuild()
        self.go(step)
        self.open()
        self.next_button.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
        self.orbit()

    def go(self, index):
        self.index = max(0, min(len(STEPS) - 1, index))
        last = self.index == len(STEPS) - 1
        title, line = STEPS[self.index]
        self.pages.setCurrentIndex(self.index)
        self.pages.currentWidget().verticalScrollBar().setValue(0)
        self.step_label.setText(f"STEP {self.index + 1} OF {len(STEPS)}")
        self.title.set_full_text(title)
        self.title.setAccessibleName(title)
        self.speech.setText("<b>Miso:</b> " + line)
        self.back_button.setEnabled(self.index > 0)
        self.skip_button.setVisible(not last)
        self.next_button.setText("&Finish" if last else "&Next")
        self.next_button.setToolTip("Finish the tour (Enter)" if last else "Next step (Enter or →)")
        for position, dot in enumerate(self.dots):
            repolish(dot, "current" if position == self.index else "done" if position < self.index else "todo")
        self.pages.currentWidget().setAccessibleName(f"Step {self.index + 1} of {len(STEPS)}: {title}")
        self.setWindowTitle(f"Orbit Tabs Quick Start · {self.index + 1} of {len(STEPS)}")

    def advance(self):
        if self.index == len(STEPS) - 1:
            self.accept()
        else:
            self.go(self.index + 1)

    def forward(self):
        # The arrow key never finishes the tour; Enter or Finish does.
        if self.index < len(STEPS) - 1:
            self.go(self.index + 1)

    def back(self):
        if self.index:
            self.go(self.index - 1)
            if not self.back_button.isEnabled():
                self.next_button.setFocus()

    # Motion ------------------------------------------------------------------------------------------
    def orbit(self):
        """One lap of Miso around the step title, unless motion is reduced or nothing is on screen."""
        if not self.motion_allowed() or self.compact and self.width() < 360:
            return False
        self.motion.stop()
        self.title.sprite = miso_pixmap(18, self.devicePixelRatioF())
        self.motion.start()
        return True

    def stop_motion(self):
        if shiboken6.isValid(self.motion):
            self.motion.stop()
        if shiboken6.isValid(self.title):
            self.title.set_orbit_angle(None)

    def hideEvent(self, event):
        super().hideEvent(event)
        self.stop_motion()

    def eventFilter(self, watched, event):
        # Only a visible tour reacts; this also keeps teardown from touching deleted children.
        if not shiboken6.isValid(self) or not self.isVisible():
            return False
        kind = event.type()
        if kind in (QEvent.Type.Hide, QEvent.Type.WindowStateChange):
            if not watched.isVisible() or watched.isMinimized():
                self.stop_motion()
        elif kind in (QEvent.Type.Resize, QEvent.Type.Move) and self.isVisible():
            self.fit()
        return False

    # Layout and theme --------------------------------------------------------------------------------
    def fit(self):
        """Stay inside the main window (and the screen), switching to a compact layout when small."""
        owner = self.parentWidget().window() if self.parentWidget() else None
        screen = (owner.screen() if owner else None) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry() if screen else QRect(0, 0, 1280, 800)
        frame = owner.geometry() if owner and owner.isVisible() else area
        width = max(300, min(640, frame.width() - 32, area.width() - 16))
        height = max(280, min(590, frame.height() - 32, area.height() - 16))
        compact = width < 540 or height < 480
        self.resize(width, height)
        center = frame.center() - QPoint(width // 2, height // 2)
        x = min(max(center.x(), area.left()), area.right() - width)
        y = min(max(center.y(), area.top()), area.bottom() - height)
        self.move(x, y)
        if compact != self.compact:
            self.compact = compact
            self.built_for = None
            if self.pages.count():
                self.rebuild()

    def apply_theme(self, theme):
        self.theme = theme
        self.built_for = None
        if self.pages.count():
            self.rebuild()

    def rebuild(self):
        signature = (tuple(sorted((k, str(v)) for k, v in self.theme.items())), self.compact)
        if signature == self.built_for:
            return
        self.built_for = signature
        self.setStyleSheet(guide_styles(self.theme, self.compact))
        self.miso_size = 48 if self.compact else 84
        self.miso.setPixmap(miso_pixmap(self.miso_size, self.devicePixelRatioF()))
        self.miso.setFixedSize(self.miso_size, self.miso_size)
        margin = (12, 10, 14, 10) if self.compact else (18, 14, 20, 14)
        self.header_layout.setContentsMargins(*margin)
        self.bubble_layout.setContentsMargins(11, 4 if self.compact else 7, 11, 4 if self.compact else 7)
        # Reserve two lines in the roomy layout so the page does not jump between steps.
        self.speech.setMinimumHeight(0 if self.compact else self.speech.fontMetrics().lineSpacing() * 2)
        focused = self.pages.currentIndex()
        while self.pages.count():
            page = self.pages.widget(0)
            self.pages.removeWidget(page)
            page.deleteLater()
        builders = (self.page_courses, self.page_open, self.page_quiz, self.page_qa, self.page_buttons,
                    self.page_privacy, self.page_waits)
        for builder in builders:
            body = QWidget()
            body.setObjectName("guidePage")
            layout = QVBoxLayout(body)
            side = 14 if self.compact else 22
            layout.setContentsMargins(side, 14, side, 16)
            layout.setSpacing(12)
            builder(layout)
            layout.addStretch(1)
            scroll = QScrollArea()
            scroll.setObjectName("guideScroll")
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            scroll.setWidget(body)
            self.pages.addWidget(scroll)
        if focused >= 0:
            self.go(focused)

    # Pages ---------------------------------------------------------------------------------------------
    def page_courses(self, layout):
        t = self.theme
        layout.addWidget(para("Sign in on <b>My Learning</b>, then press <b>Check now</b>. Orbit Tabs opens each "
                              "unfinished course in its own tab, one at a time."))
        layout.addWidget(chip_row(t, ("Check now", "check", True), ("Monitor wall", "wall", False, "Ctrl+1"),
                                  ("My Learning", "home", False, "Ctrl+2")))
        frame, inner = card(t)
        inner.addWidget(para("The status bar keeps count:", "guideNote"))
        inner.addWidget(chip_row(t, ("10 open · 0 queued",)))
        inner.addWidget(para("<b>Managed tabs</b> in the toolbar limits how many courses open at once. "
                             "<b>All</b> opens every unfinished course.", "guideNote"))
        layout.addWidget(frame)
        layout.addWidget(para("More shortcuts: <b>F9</b> shows the sidebar and <b>Ctrl+K</b> finds an open page.",
                              "guideNote"))

    def page_open(self, layout):
        t = self.theme
        heading, inner = card(t, walled=True)
        top = QLabel("Monitor wall")
        top.setObjectName("wallHeading")
        top.setStyleSheet("font-size: 18px;")
        inner.addWidget(top)
        inner.addWidget(para(f"10 open · <span style='background:{t['accent_soft']};color:{t['text']};'>"
                             "&nbsp;0 answering&nbsp;</span> · Live question cards", "guideNote"))
        layout.addWidget(heading)
        layout.addWidget(para("<b>Open</b> counts course tabs that have loaded. <b>Answering</b> counts only tabs "
                              "where Course QA is asking for or applying answers right now. Opening a course never "
                              "starts a quiz, so <b>0 answering</b> is the normal resting state."))
        layout.addWidget(mock_tile(t, self.devicePixelRatioF()))
        layout.addWidget(para("A card that says <b>Waiting for a question</b> has no readable question on screen "
                              "yet. The course is usually on its launch screen, a video, or a lesson slide."))
        legend, inner = card(t, walled=True)
        row = QWidget()
        flow = FlowLayout(row, 6)
        for state in ("idle", "answering", "waiting", "running", "submitting"):
            flow.addWidget(badge(state))
        inner.addWidget(row)
        inner.addWidget(para("Hover over a card’s badge to see exactly what it is doing.", "guideNote"))
        layout.addWidget(legend)

    def page_quiz(self, layout):
        t = self.theme
        picture = QLabel()
        width = 220 if self.compact else 260
        picture.setPixmap(launch_screen(t, QSize(width, round(width * 9 / 16)), self.devicePixelRatioF(), ring=True))
        picture.setAccessibleName("A course launch screen with Start and Resume buttons")
        row = QHBoxLayout()
        row.addWidget(picture)
        row.addStretch(1)
        layout.addLayout(row)
        steps = (
            "Click the live thumbnail in a card’s top-right corner, or the card’s title, to open the full course.",
            "If the course shows <b>Start</b> or <b>Resume</b>, click it yourself. Orbit Tabs never presses it "
            "for you. <b>Resume</b> picks up where you left off.",
            "Move through the lesson with the course’s own buttons until a quiz appears. Its card then shows "
            "<b>QUESTION 01 / 05</b> instead of Waiting for a question.",
        )
        for number, text in enumerate(steps, 1):
            layout.addWidget(para(f"<b style='color:{t['accent']}'>{number}.</b>&nbsp; {text}"))
        layout.addWidget(chip_row(t, ("Back", "back", False, "Alt+Left"), ("Monitor wall", "wall", False, "Ctrl+1")))
        layout.addWidget(para("Slide text hidden behind an animation? Try <b>Orbit › Reveal lesson text</b> "
                              "(Ctrl+Shift+L).", "guideNote"))

    def page_qa(self, layout):
        t = self.theme
        layout.addWidget(para("With a course tab in front, click the <b>Course QA</b> icon in the toolbar or choose "
                              "it from the menu. The <b>Orbit Course QA</b> panel opens in the top-right of the page."))
        layout.addWidget(chip_row(t, ("Course QA", "qa"), ("AI suggestions", "sparkle")))
        layout.addWidget(menu_path(t, "Orbit", "Course QA"))
        layout.addWidget(qa_panel())
        layout.addWidget(para("From the Monitor wall, open a course first. Otherwise the status bar says "
                              "<i>Select a course tab to open Course QA.</i>", "guideNote"))

    def page_buttons(self, layout):
        t = self.theme
        rows = (
            ("Prepare answers", "Drafts an answer plan in the panel for you to review. It selects nothing on the "
             "page. The toolbar’s <b>AI suggestions</b> does the same for the open course.", False),
            ("Suggest & apply", "Selects the suggested answers on the current screen once the whole batch is "
             "ready. Questions without a confident suggestion stay blank. It does not submit.", False),
            ("Submitting", "Happens only when you click the course’s own <b>Submit</b>, or run a plan that "
             "includes <b>Add submit</b> (<b>Run plan</b> asks first). <b>Finish now…</b> needs a separate "
             "<b>Dangerous permission</b>. Orbit decides when Submit unlocks.", True),
        )
        for title, text, key in rows:
            frame, inner = card(t)
            frame.setProperty("tone", "key" if key else "")
            label = QLabel(title)
            # The two Course QA buttons are drawn as they look in the page; submitting is a concept, not a button.
            label.setObjectName("guideCode" if key else "qaButton")
            label.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
            if key:
                label.setStyleSheet("font-weight: 700;")
            inner.addWidget(label)
            inner.addWidget(para(text))
            layout.addWidget(frame)
        layout.addWidget(para("Review what’s selected before you hand anything in.", "guideNote"))

    def page_privacy(self, layout):
        t = self.theme
        layout.addWidget(para("Question text leaves Orbit Tabs only after you say <b>Yes</b> to this prompt, "
                              "which appears for Prepare answers, Suggest &amp; apply, and AI suggestions:"))
        box, inner = card(t)
        title = QLabel("AI suggestions")
        title.setObjectName("consentTitle")
        inner.addWidget(title)
        inner.addWidget(para("Send visible questions and choices to Pollinations AI? Questions it is unsure about "
                             "may also be searched on Wikipedia."))
        inner.addWidget(chip_row(t, ("No",), ("Yes",)))
        layout.addWidget(box)
        points = (
            "It sends the questions and choices visible on that screen. No API key or account is involved.",
            "Questions the AI is unsure about may be searched on Wikipedia.",
            "Nothing is sent while you browse, open tabs, or watch the Monitor wall.",
            "Use it only where your course and institution allow AI help.",
        )
        layout.addWidget(para("".join(f"<p style='margin:0 0 6px 0'>•&nbsp; {text}</p>" for text in points)))
        layout.addWidget(para("Turn it off any time. Prepare answers and Suggest &amp; apply disappear:", "guideNote"))
        layout.addWidget(menu_path(t, "Settings", "Enable hosted AI suggestions"))

    def page_waits(self, layout):
        t = self.theme
        frame, inner = card(t, walled=True)
        rows = (
            ("answering", "Asking Pollinations AI about questions 1–20 of 24…", "A request is in flight. Usually seconds."),
            ("answering", "Searching Wikipedia for question 3…", "Double-checking an uncertain question."),
            ("waiting", "The free AI endpoint is rate-limited. Retrying in 46 seconds…",
             "The free service is busy. Course QA retries on its own."),
            ("waiting", "Waiting for the delay set in Orbit Tabs.", "The delay saved in your plan is counting down."),
            ("waiting", "Waiting for the course to enable Submit.", "The course controls when Submit unlocks."),
            ("waiting", "Waiting for the course to make step 2 available…",
             "That control isn’t on screen. Go to the matching page."),
            ("idle", "Waiting for a question", "No readable quiz on screen yet. See step 3."),
        )
        for index, (state, message, meaning) in enumerate(rows):
            if index:
                line = QFrame()
                line.setFixedHeight(1)
                line.setStyleSheet(f"background: {t['line']};")
                inner.addWidget(line)
            top = QHBoxLayout()
            top.setSpacing(8)
            top.addWidget(badge(state), 0, Qt.AlignmentFlag.AlignTop)
            top.addWidget(para(f"<i>{message}</i>"), 1)
            inner.addLayout(top)
            inner.addWidget(para(meaning, "guideNote"))
        layout.addWidget(frame)
        layout.addWidget(para("Hover over a badge on the Monitor wall for the live reason. Miso pops up a short "
                              "hint when something looks stuck. Dismiss any hint with ×."))
        if self.hints_action is not None:
            toggle = QCheckBox("Show Miso’s hints")
            toggle.setChecked(self.hints_action.isChecked())
            toggle.toggled.connect(self.hints_action.setChecked)
            layout.addWidget(toggle)
        layout.addWidget(para("Replay this tour any time:", "guideNote"))
        layout.addWidget(menu_path(t, "Orbit", "Quick Start"))
