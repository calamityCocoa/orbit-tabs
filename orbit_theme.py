"""Shared desktop chrome and vector mark for Orbit Tabs."""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPen, QPixmap

SLOGAN = "Orbit the busywork."
ACCENTS = {
    "Blue": ("#9cbeff", "#214d9d"),
    "Mint": ("#74e4b4", "#14634d"),
    "Lilac": ("#d5b2ff", "#65398d"),
    "Sunset": ("#ffbb88", "#8b451d"),
}


def orbit_icon():
    mark = QIcon()
    for size in (16, 24, 32, 48, 64, 128):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(size / 64, size / 64)
        background = QLinearGradient(2, 1, 62, 64)
        background.setColorAt(0, QColor("#142344"))
        background.setColorAt(1, QColor("#382068"))
        painter.setPen(QPen(QColor("#5467a5"), 1.3))
        painter.setBrush(background)
        painter.drawRoundedRect(QRectF(2, 2, 60, 60), 14, 14)
        painter.save()
        painter.translate(32, 33)
        painter.rotate(-31)
        painter.setPen(QPen(QColor("#65efdf"), 3.8))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QRectF(-23, -11, 46, 22))
        painter.restore()
        planet = QLinearGradient(23, 23, 41, 43)
        planet.setColorAt(0, QColor("#eef5ff"))
        planet.setColorAt(1, QColor("#9ca2ff"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(planet)
        painter.drawEllipse(QPointF(31, 33), 10, 10)
        painter.setBrush(QColor("#ffd98c"))
        painter.drawEllipse(QPointF(49, 18), 5, 5)
        painter.setBrush(QColor("#bdd5ff"))
        painter.drawEllipse(QPointF(17, 16), 2, 2)
        painter.end()
        mark.addPixmap(pixmap)
    return mark


def desktop_styles(dark, accent_name="Blue"):
    bg, panel, text, muted, line, hover, selected = (
        ("#111827", "#192337", "#edf2fb", "#aab8ce", "#354359", "#263650", "#294877")
        if dark else
        ("#eef2f8", "#ffffff", "#182640", "#536581", "#cbd6e6", "#e0eaf9", "#d5e5ff")
    )
    accent = ACCENTS.get(accent_name, ACCENTS["Blue"])[0 if dark else 1]
    return f"""
      QMainWindow, QMenuBar, QStatusBar {{ background: {bg}; color: {text}; }}
      QToolBar {{ background: {panel}; border: 0; border-bottom: 1px solid {line}; spacing: 4px; padding: 6px; }}
      QToolBar QLabel, QStatusBar QLabel {{ color: {muted}; }}
      QLabel#orbitBrand {{ color: {text}; font-weight: bold; padding: 0 8px 0 4px; }}
      QToolButton, QMenuBar::item {{ color: {text}; border-radius: 5px; padding: 5px 7px; }}
      QToolButton:hover, QMenuBar::item:selected, QMenu::item:selected {{ background: {hover}; }}
      QToolButton:disabled {{ color: {muted}; }}
      QMenu, QSpinBox {{ background: {panel}; color: {text}; border: 1px solid {line}; }}
      QMenu::item {{ padding: 6px 24px; }}
      QSpinBox {{ padding: 4px; border-radius: 4px; selection-background-color: {selected}; }}
      QTabBar::tab {{ color: {muted}; background: {bg}; padding: 8px 10px; border-bottom: 2px solid transparent; }}
      QTabBar::tab:selected {{ color: {text}; background: {panel}; border-bottom-color: {accent}; }}
      QTabBar::tab:hover {{ background: {hover}; }}
      QTabWidget::pane {{ border: 1px solid {line}; }}
      QDockWidget {{ color: {text}; }}
      QDockWidget::title {{ background: {panel}; padding: 7px; border-bottom: 1px solid {line}; }}
      QTreeWidget {{ background: {panel}; alternate-background-color: {bg}; color: {text};
                    border: 1px solid {line}; selection-background-color: {selected}; selection-color: {text}; }}
      QTreeWidget::item {{ min-height: 26px; }}
      QHeaderView::section {{ color: {muted}; background: {bg}; border: 0;
                             border-bottom: 1px solid {line}; padding: 6px; }}
      QToolButton:focus, QSpinBox:focus {{ border: 1px solid {accent}; }}
    """
