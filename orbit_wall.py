"""Low-rate thumbnail monitor for existing Orbit browser views."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

PAGE_SIZE = 6


class Tile(QFrame):
    def __init__(self, open_view):
        super().__init__()
        self.view = None
        self.setObjectName("orbitTile")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(self)
        self.title = QPushButton()
        self.title.setToolTip("Open full-size tab")
        self.title.clicked.connect(lambda: open_view(self.view) if self.view else None)
        layout.addWidget(self.title)
        self.preview = QLabel("Waiting for first frame…")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(130, 85)
        self.preview.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.preview.setStyleSheet("background: #20242c; color: #a7adb8;")
        layout.addWidget(self.preview, 1)
        self.badge = QLabel()
        layout.addWidget(self.badge)

    def bind(self, view, name):
        if self.view is not view:
            self.view = view
            self.preview.setText("Waiting for first frame…")
        self.title.setText(self.title.fontMetrics().elidedText(name, Qt.TextElideMode.ElideRight, max(100, self.width() - 32)))
        self.title.setToolTip(name + " · Open full-size tab")
        self.setVisible(view is not None)

    def draw(self):
        if not self.view:
            return
        state = self.view.activity
        answering = state == "answering"
        self.badge.setText({
            "answering": "● ANSWERING",
            "waiting": "◷ WAITING",
            "submitting": "→ SUBMITTING",
            "running": "→ RUNNING",
        }.get(state, "○ STANDBY"))
        self.badge.setStyleSheet("font-weight: bold; color: #75df9d;" if answering else "color: #a1a7b2;")
        pixmap = self.view.grab()
        if pixmap.isNull():
            return
        # Scale before conversion so the wall only retains a small grayscale preview per tab.
        pixmap = pixmap.scaled(self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio,
                              Qt.TransformationMode.FastTransformation)
        if not answering:
            pixmap = QPixmap.fromImage(pixmap.toImage().convertToFormat(QImage.Format.Format_Grayscale8))
        self.preview.setPixmap(pixmap)


class MonitorWall(QWidget):
    def __init__(self, views, title, open_view):
        super().__init__()
        self.views = views
        self.title_for = title
        self.page = 0
        self.showing = set()
        self.setObjectName("orbitWall")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setStyleSheet("""
            QWidget#orbitWall { background: #171a21; }
            QFrame#orbitTile { background: #262b34; border: 1px solid #3b4250; border-radius: 7px; }
            QLabel { color: #bdc6d4; }
            QPushButton { background: #323946; color: #e0e5ee; border: 0; border-radius: 4px; padding: 6px; }
            QPushButton:hover { background: #485367; }
            QPushButton:disabled { color: #a1aaba; }
            QPushButton:focus { border: 1px solid #a2c2ff; }
            QLabel#wallHeading { font-size: 21px; font-weight: bold; color: #edf2fb; }
        """)
        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)
        heading = QVBoxLayout()
        heading.setSpacing(2)
        title_label = QLabel("Monitor wall")
        title_label.setObjectName("wallHeading")
        heading.addWidget(title_label)
        self.summary = QLabel("1 frame per second")
        heading.addWidget(self.summary)
        toolbar.addLayout(heading)
        toolbar.addStretch()
        self.previous = QPushButton("‹ Previous")
        self.next = QPushButton("Next ›")
        self.counter = QLabel()
        self.previous.clicked.connect(lambda: self.turn(-1))
        self.next.clicked.connect(lambda: self.turn(1))
        for widget in (self.previous, self.counter, self.next):
            toolbar.addWidget(widget)
        layout.addLayout(toolbar)
        self.grid = QGridLayout()
        self.grid.setSpacing(9)
        self.columns = 0
        self.tiles = [Tile(open_view) for _ in range(PAGE_SIZE)]
        layout.addLayout(self.grid, 1)
        self.reflow(3)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.refresh)

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
        self.reflow(2 if event.size().width() < 740 else 3)

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

    def refresh(self):
        views = self.views()
        pages = max(1, (len(views) + PAGE_SIZE - 1) // PAGE_SIZE)
        self.page = min(pages - 1, max(0, self.page))
        self.previous.setEnabled(self.page > 0)
        self.next.setEnabled(self.page + 1 < pages)
        self.counter.setText(f"{self.page + 1} / {pages}")
        active = sum(view.activity == "answering" for view in views)
        summary = f"{len(views)} open · {active} answering · 1 frame per second"
        if self.summary.text() != summary:
            self.summary.setText(summary)
        displayed = views[self.page * PAGE_SIZE:(self.page + 1) * PAGE_SIZE]
        visible = set(displayed)
        for view in self.showing - visible:
            view.page().setVisible(False)
        for index, tile in enumerate(self.tiles):
            view = displayed[index] if index < len(displayed) else None
            tile.bind(view, self.title_for(view) if view else "")
            if view:
                # These pages are on screen as wall previews, even though their full widgets are hidden.
                if view not in self.showing:
                    view.resize(440, 270)
                if not view.page().isVisible():
                    view.page().setVisible(True)
                tile.draw()
        self.showing = visible
