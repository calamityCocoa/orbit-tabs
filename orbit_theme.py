"""Shared desktop chrome and vector mark for Orbit Tabs."""
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap


def orbit_icon():
    mark = QIcon()
    for size in (16, 24, 32, 48, 64, 128):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(size / 64, size / 64)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#132039"))
        painter.drawRoundedRect(1, 1, 62, 62, 15, 15)
        painter.setPen(QPen(QColor("#93b7ff"), 3.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(32, 32), 19, 19)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#93b7ff"))
        painter.drawEllipse(QPointF(32, 32), 6, 6)
        painter.setBrush(QColor("#74e4b4"))
        painter.drawEllipse(QPointF(46, 19), 5, 5)
        painter.end()
        mark.addPixmap(pixmap)
    return mark


def desktop_styles(dark):
    bg, panel, text, muted, line, hover, selected, accent = (
        ("#111827", "#192337", "#edf2fb", "#aab8ce", "#354359", "#263650", "#294877", "#9cbeff")
        if dark else
        ("#eef2f8", "#ffffff", "#182640", "#536581", "#cbd6e6", "#e0eaf9", "#d5e5ff", "#214d9d")
    )
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
