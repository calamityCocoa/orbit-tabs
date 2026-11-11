"""Read-only native course monitor with an optional raw browser preview."""
from PySide6.QtCore import QEasingCurve, QRectF, QSize, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QFrame, QGraphicsDropShadowEffect, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy, QStackedLayout, QToolButton, QVBoxLayout, QWidget,
)

import time

from orbit_common import clock_text
from orbit_theme import line_icon, tokens, wall_styles

PAGE_SIZE = 6
BADGES = {
    "answering": "● ANSWERING",
    "waiting": "◷ WAITING",
    "submitting": "→ SUBMITTING",
    "running": "→ RUNNING",
}


def repolish(widget, state):
    if widget.property("state") != state:
        widget.setProperty("state", state)
        widget.style().unpolish(widget)
        widget.style().polish(widget)


def rounded(pixmap, radius=4):
    """Clip a preview to the card's rounded corners."""
    result = QPixmap(pixmap.size())
    result.setDevicePixelRatio(pixmap.devicePixelRatio())
    result.fill(Qt.GlobalColor.transparent)
    painter = QPainter(result)
    painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
    clip = QPainterPath()
    ratio = pixmap.devicePixelRatio()
    clip.addRoundedRect(QRectF(0, 0, pixmap.width() / ratio, pixmap.height() / ratio), radius, radius)
    painter.setClipPath(clip)
    painter.drawPixmap(0, 0, pixmap)
    painter.end()
    return result


class QuestionPreview(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("questionPreview")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.snapshot = {}
        self.position = 0
        self.previous_title = ""
        self.effects_enabled = True
        self.layout_box = QVBoxLayout(self)
        self.layout_box.setContentsMargins(16, 12, 16, 12)
        self.layout_box.setSpacing(8)
        navigation = QHBoxLayout()
        self.caption = QLabel()
        self.caption.setObjectName("questionCaption")
        navigation.addWidget(self.caption, 1)
        self.previous = QToolButton()
        self.next = QToolButton()
        for button, name, symbol in ((self.previous, "Previous question", "‹"),
                                     (self.next, "Next question", "›")):
            button.setText(symbol)
            button.setAccessibleName(name)
            button.setToolTip(name)
            navigation.addWidget(button)
        self.previous.clicked.connect(lambda: self.turn(-1))
        self.next.clicked.connect(lambda: self.turn(1))
        self.layout_box.addLayout(navigation)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(7)
        self.title = QLabel()
        self.title.setObjectName("questionTitle")
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        self.title.setWordWrap(True)
        self.body_layout.addWidget(self.title)
        self.choices = []
        for _ in range(4):
            label = QLabel()
            label.setObjectName("questionChoice")
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(True)
            self.body_layout.addWidget(label)
            self.choices.append(label)
        self.note = QLabel()
        self.note.setObjectName("questionCaption")
        self.note.setWordWrap(True)
        self.body_layout.addWidget(self.note)
        self.layout_box.addWidget(self.body)
        self.layout_box.addStretch(1)
        self.animation = QVariantAnimation(self)
        self.animation.setDuration(200)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.valueChanged.connect(self.transition)

    def transition(self, progress):
        self.body_layout.setContentsMargins(0, round((1 - progress) * 9), 0, 0)

    def set_snapshot(self, snapshot):
        if snapshot == self.snapshot and self.caption.text():
            return
        old_titles = [question["title"] for question in self.snapshot.get("questions", [])]
        new_titles = [question["title"] for question in snapshot.get("questions", [])]
        if old_titles != new_titles:
            current = old_titles[self.position] if self.position < len(old_titles) else ""
            self.position = new_titles.index(current) if current in new_titles else 0
        self.snapshot = snapshot
        self.render()

    def turn(self, amount):
        self.position += amount
        self.render()

    def render(self):
        questions = self.snapshot.get("questions", [])
        total = len(questions)
        self.position = min(max(0, self.position), max(0, total - 1))
        self.previous.setVisible(total > 1)
        self.next.setVisible(total > 1)
        self.previous.setEnabled(self.position > 0)
        self.next.setEnabled(self.position + 1 < total)
        self.caption.setText(f"QUESTION {self.position + 1:02d} / {total:02d}" if total else "COURSE PAGE")
        question = questions[self.position] if total else {}
        title = question.get("title") or ("Quiz embedded by another site" if self.snapshot.get("blocked") else "Waiting for a question")
        self.title.setText(title)
        self.title.setToolTip(title)
        choices = question.get("choices", [])
        for index, label in enumerate(self.choices):
            choice = choices[index] if index < len(choices) else None
            label.setVisible(choice is not None)
            if choice:
                prefix = "✓" if choice["selected"] else chr(ord("A") + index)
                label.setText(f"{prefix}   {choice['text']}")
                repolish(label, "selected" if choice["selected"] else "idle")
        remaining = question.get("total", 0) - len(self.choices)
        if remaining > 0:
            note = f"+ {remaining} more in the course page"
        elif total:
            note = "" if choices else "Open the course page to enter your response."
        else:
            note = "Nothing to inspect yet. Miso recommends opening the course page."
        self.note.setText(note)
        self.note.setVisible(bool(note))
        if title != self.previous_title:
            self.previous_title = title
            self.animation.stop()
            if self.effects_enabled:
                self.animation.start()
            else:
                self.transition(1)

    def set_effects(self, enabled):
        self.effects_enabled = enabled
        if not enabled:
            self.animation.stop()
            self.transition(1)


class Tile(QFrame):
    def __init__(self, open_view):
        super().__init__()
        self.view = None
        self.effects_enabled = True
        self.glow_color = "#5ad79a"
        self.shadow_color = (0, 0, 0, 110)
        self.setObjectName("orbitTile")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(8)
        header = QHBoxLayout()
        header.setSpacing(8)
        self.cover = QLabel()
        self.cover.setFixedSize(34, 22)
        self.cover.hide()
        header.addWidget(self.cover)
        self.title = QPushButton()
        self.title.setObjectName("tileTitle")
        self.title.setCursor(Qt.CursorShape.PointingHandCursor)
        self.title.setToolTip("Open full-size tab")
        self.title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.title.clicked.connect(lambda: open_view(self.view) if self.view else None)
        header.addWidget(self.title, 1)
        self.mini = QToolButton()
        self.mini.setObjectName("tileMini")
        self.mini.setToolTip("Live browser view · Click to open this course")
        self.mini.setAccessibleName("Open full browser view")
        self.mini.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mini.setFixedSize(110, 65)
        self.mini.setIconSize(QSize(104, 59))
        self.mini.clicked.connect(self.title.click)
        header.addWidget(self.mini)
        layout.addLayout(header)
        self.preview = QLabel("Waiting for first frame…")
        self.preview.setObjectName("tilePreview")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(130, 85)
        self.preview.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.preview.setCursor(Qt.CursorShape.PointingHandCursor)
        self.preview.mouseReleaseEvent = lambda event: self.title.click()
        surface = QWidget()
        self.surface = QStackedLayout(surface)
        self.surface.setContentsMargins(0, 0, 0, 0)
        self.question = QuestionPreview()
        self.surface.addWidget(self.question)
        self.surface.addWidget(self.preview)
        layout.addWidget(surface, 1)
        footer = QHBoxLayout()
        self.badge = QLabel()
        self.badge.setObjectName("tileBadge")
        footer.addWidget(self.badge)
        footer.addStretch(1)
        self.elapsed = QLabel()
        self.elapsed.setObjectName("tileElapsed")
        self.elapsed.setToolTip("Time this tab has been open")
        footer.addWidget(self.elapsed)
        layout.addLayout(footer)

    def bind(self, view, name, cover=None):
        if self.view is not view:
            self.view = view
            self.preview.setText("Waiting for first frame…")
            self.mini.setIcon(QIcon())
            self.question.set_snapshot({})
        if cover is None:
            self.cover.hide()
        elif self.cover.pixmap().cacheKey() != cover.cacheKey():
            self.cover.setPixmap(cover)
            self.cover.show()
        else:
            self.cover.show()
        self.name = name
        self.elide_title()
        self.title.setToolTip(name + " · Open full-size tab")
        self.setVisible(view is not None)

    def elide_title(self):
        # The button's text area is its width minus the style-sheet padding and frame.
        width = max(40, self.title.width() - 26)
        text = self.title.fontMetrics().elidedText(getattr(self, "name", ""), Qt.TextElideMode.ElideRight, width)
        if self.title.text() != text:
            self.title.setText(text)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.elide_title()

    def set_glow(self, on):
        """Keep the answering highlight subtle and skip effects when motion is reduced."""
        if not self.effects_enabled:
            self.setGraphicsEffect(None)
            return
        effect = QGraphicsDropShadowEffect(self)
        if on:
            effect.setBlurRadius(18)
            effect.setOffset(0, 0)
            effect.setColor(QColor(self.glow_color))
        else:
            effect.setBlurRadius(12)
            effect.setOffset(0, 2)
            effect.setColor(QColor(*self.shadow_color))
        self.setGraphicsEffect(effect)

    def draw(self, raw=False):
        if not self.view:
            return
        state = self.view.activity
        answering = state == "answering"
        badge_state = state if state in BADGES else "idle"
        text = BADGES.get(state, "○ STANDBY")
        if self.badge.text() != text:
            self.badge.setText(text)
        if self.badge.toolTip() != self.view.activity_reason:
            self.badge.setToolTip(self.view.activity_reason)
        self.elapsed.setText(clock_text(time.monotonic() - self.view.opened) if self.view.course else "—")
        repolish(self.badge, badge_state)
        if self.property("state") != badge_state:
            self.set_glow(answering)
        repolish(self, badge_state)
        self.surface.setCurrentWidget(self.preview if raw else self.question)
        self.mini.setVisible(not raw)
        if not raw:
            self.view.read_questions()
            self.question.set_snapshot(self.view.question_snapshot)
        pixmap = self.view.grab()
        if pixmap.isNull():
            return
        # Scale (smoothly, at the screen's pixel density) before conversion so the wall only
        # retains a small grayscale preview per tab.
        target = self.preview.size() if raw else self.mini.iconSize()
        ratio = self.devicePixelRatioF()
        pixmap = pixmap.scaled(target * ratio, Qt.AspectRatioMode.KeepAspectRatio,
                              Qt.TransformationMode.SmoothTransformation)
        if not answering:
            pixmap = QPixmap.fromImage(pixmap.toImage().convertToFormat(QImage.Format.Format_Grayscale8))
        pixmap.setDevicePixelRatio(ratio)
        image = rounded(pixmap)
        if raw:
            self.preview.setPixmap(image)
        else:
            self.mini.setIcon(QIcon(image))

    def capture_size(self):
        """Render pages at the preview's shape (never narrower than 440 px) so they fill the card."""
        width = max(480, self.width())
        return QSize(width, round(width * 9 / 16))


class MonitorWall(QWidget):
    def __init__(self, views, title, open_view, cover=None, timers_action=None):
        super().__init__()
        self.views = views
        self.cover_for = cover
        self.title_for = title
        self.page = 0
        self.showing = set()
        self.setObjectName("orbitWall")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(14)

        toolbar = QHBoxLayout()
        heading = QVBoxLayout()
        heading.setSpacing(2)
        title_label = QLabel("Monitor wall")
        title_label.setObjectName("wallHeading")
        heading.addWidget(title_label)
        self.summary = QLabel("Live course questions")
        self.summary.setObjectName("wallSummary")
        heading.addWidget(self.summary)
        toolbar.addLayout(heading)
        toolbar.addStretch()
        self.raw_mode = QToolButton()
        self.raw_mode.setText("Page previews")
        self.raw_mode.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.raw_mode.setToolTip("Switch between question cards and full browser previews. No tiny binoculars needed.")
        self.raw_mode.setCheckable(True)
        self.raw_mode.toggled.connect(self.refresh)
        toolbar.addWidget(self.raw_mode)
        if timers_action:
            timers = QToolButton()
            timers.setDefaultAction(timers_action)
            timers.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            toolbar.addWidget(timers)
        self.previous = QPushButton()
        self.next = QPushButton()
        for button, tip in ((self.previous, "Previous page"), (self.next, "Next page")):
            button.setObjectName("wallPager")
            button.setToolTip(tip)
            button.setAccessibleName(tip)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.counter = QLabel()
        self.counter.setObjectName("wallCounter")
        self.previous.clicked.connect(lambda: self.turn(-1))
        self.next.clicked.connect(lambda: self.turn(1))
        for widget in (self.previous, self.counter, self.next):
            toolbar.addWidget(widget)
        layout.addLayout(toolbar)

        body = QWidget()
        self.stack = QStackedLayout(body)
        grid_host = QWidget()
        self.grid = QGridLayout(grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(16)
        self.grid.setContentsMargins(4, 2, 4, 8)  # room for the card shadows
        self.empty = QLabel("No open courses yet.\nMiso is supervising the empty wall. Open a course from My Learning.")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(grid_host)
        self.stack.addWidget(scroll)
        self.stack.addWidget(self.empty)
        layout.addWidget(body, 1)

        self.columns = 0
        self.tiles = [Tile(open_view) for _ in range(PAGE_SIZE)]
        self.reflow(3)
        self.apply_theme(tokens())
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.refresh)

    def apply_theme(self, theme, *, effects=True):
        self.setStyleSheet(wall_styles(theme))
        self.previous.setIcon(line_icon("prev", theme["text"], 16))
        self.next.setIcon(line_icon("next", theme["text"], 16))
        for tile in self.tiles:
            tile.effects_enabled = effects
            tile.question.set_effects(effects)
            tile.glow_color = theme["success"]
            tile.shadow_color = theme["shadow"]
            tile.set_glow(tile.property("state") == "answering")

    def reflow(self, columns):
        if columns == self.columns:
            return
        self.columns = columns
        for index in range(PAGE_SIZE):
            self.grid.setRowStretch(index, 0)
            self.grid.setColumnStretch(index, 0)
        for index, tile in enumerate(self.tiles):
            self.grid.removeWidget(tile)
            row, column = divmod(index, columns)
            self.grid.addWidget(tile, row, column)
            self.grid.setColumnStretch(column, 1)
            self.grid.setRowStretch(row, 1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        width = event.size().width()
        self.reflow(1 if width < 580 else 2 if width < 1040 else 3)

    def turn(self, amount):
        self.page += amount
        self.refresh()

    def start(self):
        if not self.timer.isActive():
            self.refresh()
            self.timer.start()

    def stop(self, current=None):
        self.timer.stop()
        for view in self.showing:
            view.page().setVisible(view is current and view.isVisible())
        self.showing.clear()

    def forget(self, view):
        self.showing.discard(view)
        for tile in self.tiles:
            if tile.view is view:
                tile.bind(None, "")

    def refresh(self, *_):
        views = self.views()
        pages = max(1, (len(views) + PAGE_SIZE - 1) // PAGE_SIZE)
        self.page = min(pages - 1, max(0, self.page))
        self.previous.setEnabled(self.page > 0)
        self.next.setEnabled(self.page + 1 < pages)
        self.counter.setText(f"{self.page + 1} / {pages}")
        for widget in (self.previous, self.counter, self.next):
            widget.setVisible(pages > 1)
        active = sum(view.activity == "answering" for view in views)
        raw = self.raw_mode.isChecked()
        mode = "1 frame per second" if raw else "Live question cards"
        summary = f"{len(views)} open · {active} answering · {mode}"
        if self.summary.text() != summary:
            self.summary.setText(summary)
        self.stack.setCurrentIndex(0 if views else 1)
        displayed = views[self.page * PAGE_SIZE:(self.page + 1) * PAGE_SIZE]
        visible = set(displayed)
        for view in self.showing - visible:
            view.page().setVisible(False)
        for index, tile in enumerate(self.tiles):
            view = displayed[index] if index < len(displayed) else None
            cover = self.cover_for(view, QSize(34, 22), 5) if view and self.cover_for else None
            tile.bind(view, self.title_for(view) if view else "", cover)
            if view:
                # These pages are on screen as wall previews, even though their full widgets are hidden.
                size = tile.capture_size()
                if view.size() != size:
                    view.resize(size)
                if not view.page().isVisible():
                    view.page().setVisible(True)
                tile.draw(raw)
        self.showing = visible
