"""Shared desktop chrome, design tokens, and vector marks for Orbit Tabs."""
import atexit
from math import cos, radians, sin
import shutil
import tempfile
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QLabel, QSizePolicy

SLOGAN = "One launchpad for all your courses."
ACCENTS = {
    "Blue": ("#78aeed", "#1c71d8"),
    "Mint": ("#8ff0a4", "#237d52"),
    "Lilac": ("#dc8add", "#813d9c"),
    "Sunset": ("#ffbe6f", "#a64b00"),
}

_BASE = {
    True: {
        "bg": "#242424", "surface": "#303030", "raised": "#383838", "preview": "#171717",
        "text": "#f6f5f4", "muted": "#d0cecc", "subtle": "#a8a6a3", "line": "#494949", "hover": "#3d3d3d",
        "selected": "#3d4857", "success": "#8ff0a4", "warning": "#f9f06b", "danger": "#ff8a8a",
    },
    False: {
        "bg": "#fafafa", "surface": "#ffffff", "raised": "#f3f3f3", "preview": "#e9e9e9",
        "text": "#202020", "muted": "#515151", "subtle": "#696969", "line": "#deddda", "hover": "#ededed",
        "selected": "#e0edff", "success": "#1c7046", "warning": "#865e00", "danger": "#a51d2d",
    },
}

# Catppuccin palette values from catppuccin.com/palette.
_CAT_KEYS = ("bg", "surface", "raised", "preview", "text", "muted", "subtle", "line", "hover",
             "selected", "success", "warning", "danger")
_CAT_PALETTES = {
    "Catppuccin Latte": ("#eff1f5 #f7f8fb #e6e9ef #dce0e8 #4c4f69 #5c5f77 #6c6f85 #bcc0cc #ccd0da #dce6fb #287321 #875709 #b70d34",
                         ("#1e66f5", "#287321", "#8839ef", "#a4470b"), False),
    "Catppuccin Frappé": ("#303446 #292c3c #414559 #232634 #c6d0f5 #b5bfe2 #a5adce #51576d #414559 #51576d #a6d189 #e5c890 #e78284",
                          ("#8caaee", "#a6d189", "#ca9ee6", "#ef9f76"), True),
    "Catppuccin Macchiato": ("#24273a #1e2030 #363a4f #181926 #cad3f5 #b8c0e0 #a5adcb #494d64 #363a4f #494d64 #a6da95 #eed49f #ed8796",
                             ("#8aadf4", "#a6da95", "#c6a0f6", "#f5a97f"), True),
    "Catppuccin Mocha": ("#1e1e2e #181825 #313244 #11111b #cdd6f4 #bac2de #a6adc8 #45475a #313244 #45475a #a6e3a1 #f9e2af #f38ba8",
                         ("#89b4fa", "#a6e3a1", "#cba6f7", "#fab387"), True),
}
THEMES = ("Adwaita", *_CAT_PALETTES)


_ASSETS = None
_SVG = {
    "close": '<path d="M4.5 4.5l7 7M11.5 4.5l-7 7"/>',
    "float": '<rect x="3.5" y="5.5" width="7" height="7" rx="1.2"/><path d="M6.5 3.5h6v6"/>',
}


def chrome_asset(name, color):
    """Write a tiny stroked SVG for style-sheet sub-controls and return its url() path."""
    global _ASSETS
    if _ASSETS is None:
        _ASSETS = Path(tempfile.mkdtemp(prefix="orbit-tabs-ui-"))
        atexit.register(shutil.rmtree, _ASSETS, True)
    path = _ASSETS / f"{name}-{color.lstrip('#')}.svg"
    if not path.exists():
        path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16" fill="none" '
            f'stroke="{color}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">'
            f'{_SVG[name]}</svg>', encoding="utf-8")
    return path.as_posix()


class ElidedLabel(QLabel):
    """A label that ends with an ellipsis instead of clipping when space runs out."""

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self.full_text = ""
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.set_full_text(text)

    def set_full_text(self, text):
        self.full_text = text
        self.elide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.elide()

    def elide(self):
        width = max(0, self.contentsRect().width())
        text = self.fontMetrics().elidedText(self.full_text, Qt.TextElideMode.ElideRight, width) if width else self.full_text
        if self.text() != text:
            self.setText(text)


class OrbitTitle(ElidedLabel):
    """Draw Miso and a short rainbow trail around the active tab title."""

    def __init__(self, text):
        super().__init__(text)
        self.sprite = QPixmap()
        self.orbit_angle = None
        self.setMinimumHeight(44)
        self.setContentsMargins(12, 0, 12, 0)

    def set_orbit_angle(self, angle):
        self.orbit_angle = angle
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.orbit_angle is None or self.sprite.isNull() or self.width() < 36:
            return
        center_x, center_y = self.width() / 2, self.height() / 2
        title_width = self.fontMetrics().horizontalAdvance(self.text())
        radius_x = min(center_x - 10, max(14, title_width / 2 + 10))
        radius_y = min(14, center_y - 10)

        def point(angle):
            theta = radians(angle)
            return QPointF(center_x + radius_x * cos(theta), center_y + radius_y * sin(theta))

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setPen(Qt.PenStyle.NoPen)
        for index in range(8, 0, -1):
            angle = self.orbit_angle - index * 9
            painter.setBrush(QColor.fromHsvF((angle % 360) / 360, 0.72, 0.92, 1 - index / 10))
            painter.drawEllipse(point(angle), 2.4, 2.4)
        size = self.sprite.deviceIndependentSize()
        painter.drawPixmap(point(self.orbit_angle) - QPointF(size.width() / 2, size.height() / 2), self.sprite)


def rgba(color, alpha):
    value = QColor(color)
    return f"rgba({value.red()}, {value.green()}, {value.blue()}, {alpha})"


def tokens(dark=False, accent_name="Blue", theme_name="Adwaita"):
    """Return the colour tokens shared by the window, wall and dialogs."""
    if theme_name in _CAT_PALETTES:
        colors, accents, dark = _CAT_PALETTES[theme_name]
        values = dict(zip(_CAT_KEYS, colors.split()))
        accent = accents[list(ACCENTS).index(accent_name)] if accent_name in ACCENTS else accents[0]
    else:
        values = dict(_BASE[bool(dark)])
        accent = ACCENTS.get(accent_name, ACCENTS["Blue"])[0 if dark else 1]
    values.update(
        dark=bool(dark),
        accent=accent,
        on_accent="#0b1220" if dark else "#ffffff",
        accent_soft=rgba(accent, 0.16 if dark else 0.12),
        accent_line=rgba(accent, 0.55),
        accent_hover=QColor(accent).darker(112).name() if dark else QColor(accent).lighter(115).name(),
        shadow=(0, 0, 0, 65) if dark else (0, 0, 0, 28),
    )
    return values


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


def _glyph(name):
    """Line-icon outlines on a 24-unit grid."""
    path = QPainterPath()
    if name == "wall":
        for x, y in ((3, 4), (10, 4), (17, 4), (3, 13), (10, 13), (17, 13)):
            path.addRoundedRect(QRectF(x, y, 4.5, 7), 1.2, 1.2)
    elif name == "home":
        path.moveTo(3.5, 11)
        path.lineTo(12, 4)
        path.lineTo(20.5, 11)
        path.moveTo(6, 9.5)
        path.lineTo(6, 20)
        path.lineTo(18, 20)
        path.lineTo(18, 9.5)
        path.moveTo(10, 20)
        path.lineTo(10, 14.5)
        path.lineTo(14, 14.5)
        path.lineTo(14, 20)
    elif name == "back":
        path.moveTo(19, 12)
        path.lineTo(5.5, 12)
        path.moveTo(11, 6)
        path.lineTo(5, 12)
        path.lineTo(11, 18)
    elif name == "reload":
        path.arcMoveTo(QRectF(4.5, 4.5, 15, 15), 60)
        path.arcTo(QRectF(4.5, 4.5, 15, 15), 60, 300)
        path.moveTo(18.5, 3.5)
        path.lineTo(17.6, 8.9)
        path.lineTo(12.4, 7.6)
    elif name == "check":
        path.addEllipse(QRectF(3.5, 3.5, 17, 17))
        path.moveTo(8, 12.3)
        path.lineTo(10.8, 15)
        path.lineTo(16, 9.3)
    elif name == "qa":
        path.addRoundedRect(QRectF(5, 4.5, 14, 16.5), 2, 2)
        path.moveTo(9, 3)
        path.lineTo(15, 3)
        for y in (10, 13.5, 17):
            path.moveTo(8.5, y)
            path.lineTo(9.5, y)
            path.moveTo(11.5, y)
            path.lineTo(15.5, y)
    elif name == "sparkle":
        path.moveTo(11, 3)
        path.quadTo(12, 10, 19, 11)
        path.quadTo(12, 12, 11, 19)
        path.quadTo(10, 12, 3, 11)
        path.quadTo(10, 10, 11, 3)
        path.moveTo(18.5, 15.5)
        path.lineTo(18.5, 21)
        path.moveTo(15.75, 18.25)
        path.lineTo(21.25, 18.25)
    elif name == "sidebar":
        path.addRoundedRect(QRectF(3, 4, 18, 16), 3, 3)
        path.moveTo(9, 4)
        path.lineTo(9, 20)
    elif name == "cat":
        path.moveTo(5, 11)
        path.lineTo(5, 5)
        path.lineTo(10, 8.5)
        path.lineTo(14, 8.5)
        path.lineTo(19, 5)
        path.lineTo(19, 11)
        path.cubicTo(23, 21, 1, 21, 5, 11)
        path.moveTo(9, 13)
        path.lineTo(9.1, 13)
        path.moveTo(15, 13)
        path.lineTo(15.1, 13)
        path.moveTo(11, 16)
        path.lineTo(13, 16)
    elif name == "menu":
        for y in (6.5, 12, 17.5):
            path.moveTo(4, y)
            path.lineTo(20, y)
    elif name == "prev":
        path.moveTo(14.5, 6)
        path.lineTo(8.5, 12)
        path.lineTo(14.5, 18)
    elif name == "next":
        path.moveTo(9.5, 6)
        path.lineTo(15.5, 12)
        path.lineTo(9.5, 18)
    elif name == "sound":
        path.moveTo(4, 9.5)
        path.lineTo(7.5, 9.5)
        path.lineTo(12, 5.5)
        path.lineTo(12, 18.5)
        path.lineTo(7.5, 14.5)
        path.lineTo(4, 14.5)
        path.closeSubpath()
        path.arcMoveTo(QRectF(10, 7, 9, 10), -50)
        path.arcTo(QRectF(10, 7, 9, 10), -50, 100)
    elif name == "muted":
        path.moveTo(4, 9.5)
        path.lineTo(7.5, 9.5)
        path.lineTo(12, 5.5)
        path.lineTo(12, 18.5)
        path.lineTo(7.5, 14.5)
        path.lineTo(4, 14.5)
        path.closeSubpath()
        path.moveTo(15.5, 9.5)
        path.lineTo(20.5, 14.5)
        path.moveTo(20.5, 9.5)
        path.lineTo(15.5, 14.5)
    elif name == "popout":
        path.moveTo(13, 4)
        path.lineTo(20, 4)
        path.lineTo(20, 11)
        path.moveTo(20, 4)
        path.lineTo(11.5, 12.5)
        path.moveTo(17, 14.5)
        path.lineTo(17, 20)
        path.lineTo(4, 20)
        path.lineTo(4, 7)
        path.lineTo(9.5, 7)
    elif name == "shield":
        path.moveTo(12, 3)
        path.lineTo(19.5, 6)
        path.lineTo(19.5, 11.5)
        path.cubicTo(19.5, 16, 16, 19.5, 12, 21)
        path.cubicTo(8, 19.5, 4.5, 16, 4.5, 11.5)
        path.lineTo(4.5, 6)
        path.closeSubpath()
        path.moveTo(8.8, 12)
        path.lineTo(11, 14.2)
        path.lineTo(15.4, 9.6)
    elif name == "close":
        path.moveTo(7, 7)
        path.lineTo(17, 17)
        path.moveTo(17, 7)
        path.lineTo(7, 17)
    elif name == "link":
        path.moveTo(10, 14)
        path.lineTo(14, 10)
        path.addRoundedRect(QRectF(3.2, 11.2, 9.5, 6.5), 3.2, 3.2)
        path.addRoundedRect(QRectF(11.3, 6.3, 9.5, 6.5), 3.2, 3.2)
    return path


def line_icon(name, color, size=20):
    """Render a crisp single-colour line icon at 1x and 2x."""
    icon = QIcon()
    glyph = _glyph(name)
    for scale in (1, 2):
        pixmap = QPixmap(size * scale, size * scale)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(size * scale / 24, size * scale / 24)
        pen = QPen(QColor(color), 1.9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(glyph)
        painter.end()
        pixmap.setDevicePixelRatio(scale)
        icon.addPixmap(pixmap)
    return icon


def app_font():
    """Prefer GNOME interface fonts when available, with a system-font fallback."""
    from PySide6.QtGui import QFont, QFontDatabase
    families = set(QFontDatabase.families())
    font = QFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont))
    for family in ("Adwaita Sans", "Cantarell", "Inter"):
        if family in families:
            font.setFamily(family)
            font.setPixelSize(14)
            break
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return font


def native_titlebar(window, dark, caption, text):
    """On Windows 11, colour the system title bar to match the theme; elsewhere this does nothing."""
    import sys
    if sys.platform != "win32":
        return
    try:
        import ctypes
        hwnd = int(window.winId())
        dwm = ctypes.windll.dwmapi

        def put(attribute, value):
            data = ctypes.c_int(value)
            dwm.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(data), ctypes.sizeof(data))

        def colorref(hex_color):
            color = QColor(hex_color)
            return color.red() | (color.green() << 8) | (color.blue() << 16)

        put(20, 1 if dark else 0)        # DWMWA_USE_IMMERSIVE_DARK_MODE
        put(33, 2)                       # DWMWA_WINDOW_CORNER_PREFERENCE: round
        put(35, colorref(caption))       # DWMWA_CAPTION_COLOR (Windows 11)
        put(36, colorref(text))          # DWMWA_TEXT_COLOR
    except Exception:
        pass


def app_palette(dark=False, accent_name="Blue", theme_name="Adwaita"):
    """A Fusion palette so native-drawn widgets, dialogs and menus follow the theme."""
    t = tokens(dark, accent_name, theme_name)
    palette = QPalette()
    role = QPalette.ColorRole
    for item, value in (
        (role.Window, t["bg"]), (role.WindowText, t["text"]), (role.Base, t["surface"]),
        (role.AlternateBase, t["raised"]), (role.Text, t["text"]), (role.Button, t["raised"]),
        (role.ButtonText, t["text"]), (role.ToolTipBase, t["raised"]), (role.ToolTipText, t["text"]),
        (role.PlaceholderText, t["subtle"]), (role.Highlight, t["accent"]),
        (role.HighlightedText, t["on_accent"]), (role.Link, t["accent"]), (role.Mid, t["line"]),
        (role.Midlight, t["hover"]), (role.Dark, t["preview"]), (role.Shadow, "#000000"),
    ):
        palette.setColor(item, QColor(value))
    for item in (role.WindowText, role.Text, role.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, item, QColor(t["subtle"]))
    return palette


def common_styles(t):
    """Widget rules shared by the main window and stand-alone dialogs."""
    return f"""
      QToolTip {{ background: {t['raised']}; color: {t['text']}; border: 1px solid {t['line']};
                  border-radius: 4px; padding: 5px 8px; }}
      QMenu {{ background: {t['surface']}; color: {t['text']}; border: 1px solid {t['line']};
               border-radius: 12px; padding: 5px; }}
      QMenu::item {{ padding: 7px 26px 7px 12px; border-radius: 4px; }}
      QMenu::item:selected {{ background: {t['hover']}; }}
      QMenu::item:disabled {{ color: {t['subtle']}; }}
      QMenu::separator {{ height: 1px; background: {t['line']}; margin: 5px 8px; }}
      QMenu::indicator {{ width: 14px; height: 14px; left: 6px; }}
      QPushButton {{ background: {t['raised']}; color: {t['text']}; border: 1px solid {t['line']};
                     border-radius: 8px; padding: 7px 14px; min-height: 18px; }}
      QPushButton:hover {{ background: {t['hover']}; }}
      QPushButton:pressed, QPushButton:checked {{ background: {t['selected']}; }}
      QPushButton:disabled {{ color: {t['subtle']}; background: {t['surface']}; }}
      QPushButton:focus {{ border-color: {t['accent']}; }}
      QPushButton[primary="true"] {{ background: {t['accent']}; color: {t['on_accent']};
                                     border-color: {t['accent']}; font-weight: 600; }}
      QPushButton[primary="true"]:disabled {{ background: {t['raised']}; color: {t['subtle']};
                                              border-color: {t['line']}; }}
      QDialogButtonBox {{ dialogbuttonbox-buttons-have-icons: 0; }}
      QCheckBox {{ color: {t['text']}; spacing: 8px; }}
      QProgressBar {{ background: {t['raised']}; border: 0; border-radius: 3px; max-height: 6px; }}
      QProgressBar::chunk {{ background: {t['accent']}; border-radius: 3px; }}
      QTextBrowser {{ background: {t['surface']}; color: {t['text']}; border: 1px solid {t['line']};
                      border-radius: 8px; padding: 10px; }}
      QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
      QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
      QScrollBar::handle {{ background: {t['line']}; border-radius: 3px; min-height: 28px; min-width: 28px; }}
      QScrollBar::handle:hover {{ background: {t['subtle']}; }}
      QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
      QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    """


def desktop_styles(dark, accent_name="Blue", theme_name="Adwaita"):
    t = tokens(dark, accent_name, theme_name)
    return common_styles(t) + f"""
      QMainWindow, QStatusBar {{ background: {t['bg']}; color: {t['text']}; }}
      QMainWindow::separator {{ background: {t['line']}; width: 1px; height: 1px; }}
      QMenuBar {{ background: {t['surface']}; color: {t['text']}; border-bottom: 1px solid {t['line']}; padding: 2px 6px; }}
      QMenuBar::item {{ padding: 5px 9px; border-radius: 4px; background: transparent; }}
      QMenuBar::item:selected {{ background: {t['hover']}; }}

      QToolBar#orbitToolbar {{ background: {t['surface']}; border: 0; border-bottom: 1px solid {t['line']};
                               spacing: 4px; padding: 8px 12px; }}
      QToolBar#orbitToolbar::separator {{ background: {t['line']}; width: 1px; margin: 6px 7px; }}
      QToolBar QLabel {{ color: {t['muted']}; }}
      QLabel#headerTitle {{ color: {t['text']}; font-weight: 600; }}
      QLabel#orbitBrand {{ color: {t['text']}; font-weight: 700; font-size: 14px; padding: 0 10px 0 2px; }}
      QToolButton {{ color: {t['text']}; background: transparent; border: 1px solid transparent;
                     border-radius: 8px; padding: 5px 10px; min-height: 24px; }}
      QToolButton:hover {{ background: {t['hover']}; }}
      QToolButton:pressed, QToolButton:checked {{ background: {t['selected']}; }}
      QToolButton:disabled {{ color: {t['subtle']}; }}
      QToolButton:focus {{ border-color: {t['accent_line']}; }}
      QToolButton#primaryAction {{ background: {t['accent']}; color: {t['on_accent']}; font-weight: 600; }}
      QToolButton#primaryAction:hover {{ background: {t['accent_hover']}; }}
      QToolButton#primaryAction:pressed {{ background: {t['accent_line']}; }}
      QToolButton#menuButton::menu-indicator {{ image: none; width: 0; }}
      QToolButton#mascot {{ color: {t['text']}; background: {t['accent_soft']}; border-radius: 9px; padding: 3px 9px; }}
      QSpinBox {{ background: {t['raised']}; color: {t['text']}; border: 1px solid {t['line']}; border-bottom: 1px solid {t['subtle']}; border-radius: 4px;
                  padding: 4px 6px; min-width: 46px; selection-background-color: {t['selected']};
                  selection-color: {t['text']}; }}
      QSpinBox:focus {{ border-color: {t['accent']}; }}
      QSpinBox::up-button, QSpinBox::down-button {{ width: 16px; border: 0; background: transparent; }}

      QTabWidget::pane {{ border: 0; }}
      QWidget#sidebarPanel {{ background: {t['surface']}; border-right: 1px solid {t['line']}; }}
      QListWidget#sidebar {{ background: transparent; border: 0; outline: 0; }}
      QLabel#sidebarHeading {{ color: {t['text']}; font-weight: bold; padding: 3px 7px; }}
      QLineEdit#sidebarSearch {{ color: {t['text']}; background: {t['raised']}; border: 1px solid {t['line']};
                                border-radius: 9px; padding: 6px 8px; selection-background-color: {t['accent']};
                                selection-color: {t['on_accent']}; }}
      QLineEdit#sidebarSearch:focus {{ border-color: {t['accent']}; }}
      QListWidget#sidebar::item {{ border-radius: 8px; margin: 1px 0; padding-left: 0; color: {t['text']}; }}
      QListWidget#sidebar::item:hover {{ background: {t['hover']}; }}
      QListWidget#sidebar::item:selected {{ background: {t['accent_soft']}; }}
      QFrame#sidebarIndicator {{ background: {t['accent']}; border-radius: 1px; }}
      QWidget#sidebarRow, QWidget#sidebarRow QLabel {{ background: transparent; color: {t['text']}; }}
      QToolButton#sidebarClose {{ border: 0; padding: 3px; border-radius: 4px; background: transparent; }}
      QToolButton#sidebarClose:hover {{ background: {t['line']}; }}
      QTabBar {{ background: {t['bg']}; }}
      QTabBar::tab {{ color: {t['muted']}; background: transparent; padding: 8px 12px; margin: 6px 2px 0 2px;
                      border: 1px solid transparent; border-bottom: 0; border-top-left-radius: 9px;
                      border-top-right-radius: 9px; min-width: 120px; max-width: 220px; }}
      QTabBar::tab:first {{ margin-left: 8px; }}
      QTabBar::tab:hover:!selected {{ background: {t['hover']}; color: {t['text']}; }}
      QTabBar::tab:selected {{ color: {t['text']}; background: {t['surface']}; border-color: {t['line']};
                               border-top: 2px solid {t['accent']}; }}
      QTabBar::close-button {{ image: url({chrome_asset("close", t['subtle'])}); subcontrol-position: right;
                               border-radius: 4px; margin: 1px; }}
      QTabBar::close-button:hover {{ image: url({chrome_asset("close", t['text'])}); background: {t['hover']}; }}
      QTabBar::scroller {{ width: 26px; }}
      QTabBar QToolButton {{ background: {t['bg']}; border-radius: 6px; padding: 2px; }}

      QDockWidget {{ color: {t['text']}; font-weight: 600;
                     titlebar-close-icon: url({chrome_asset("close", t['muted'])});
                     titlebar-normal-icon: url({chrome_asset("float", t['muted'])}); }}
      QDockWidget::close-button, QDockWidget::float-button {{ border: 0; background: transparent;
                                                             border-radius: 5px; padding: 0; icon-size: 14px; }}
      QDockWidget::close-button:hover, QDockWidget::float-button:hover {{ background: {t['hover']}; }}
      QDockWidget::title {{ background: {t['surface']}; padding: 9px 12px; border-bottom: 1px solid {t['line']};
                            text-align: left; }}
      QDockWidget > QWidget {{ background: {t['surface']}; }}
      QDockWidget QPushButton {{ padding: 5px 10px; font-weight: 400; }}
      QTreeWidget {{ background: {t['surface']}; alternate-background-color: {t['raised']}; color: {t['text']};
                     border: 0; outline: 0; selection-background-color: {t['selected']}; selection-color: {t['text']};
                     font-weight: 400; }}
      QTreeWidget::item {{ min-height: 30px; padding: 0 4px; border: 0; }}
      QTreeWidget::item:hover {{ background: {t['hover']}; }}
      QTreeWidget::item:selected {{ background: {t['selected']}; color: {t['text']}; }}
      QHeaderView {{ background: {t['surface']}; }}
      QHeaderView::section {{ color: {t['subtle']}; background: {t['surface']}; border: 0;
                             border-bottom: 1px solid {t['line']}; padding: 7px 8px; font-size: 11px;
                             font-weight: 600; }}

      QStatusBar {{ border-top: 1px solid {t['line']}; color: {t['muted']}; }}
      QStatusBar::item {{ border: 0; }}
      QStatusBar QLabel {{ color: {t['muted']}; padding: 3px 4px; }}
      QLabel#statusDot {{ font-size: 10px; padding: 3px 0 3px 8px; }}
      QLabel#statusCount {{ background: {t['raised']}; border: 1px solid {t['line']}; border-radius: 9px;
                            padding: 1px 9px; margin: 3px 8px 3px 0; }}
    """


def wall_styles(t):
    return f"""
      QWidget#orbitWall {{ background: {t['bg']}; }}
      QLabel {{ color: {t['muted']}; }}
      QLabel#wallHeading {{ font-size: 24px; font-weight: 700; color: {t['text']}; }}
      QLabel#wallSummary {{ color: {t['muted']}; }}
      QLabel#wallCounter {{ color: {t['text']}; padding: 0 6px; font-weight: 600; }}
      QPushButton#wallPager {{ background: {t['surface']}; border: 1px solid {t['line']}; border-radius: 15px;
                               min-width: 30px; max-width: 30px; min-height: 30px; max-height: 30px; padding: 0; }}
      QPushButton#wallPager:hover {{ background: {t['hover']}; }}
      QPushButton#wallPager:disabled {{ background: transparent; }}
      QPushButton#wallPager:focus {{ border-color: {t['accent']}; }}
      QFrame#orbitTile {{ background: {t['surface']}; border: 1px solid {t['line']}; border-radius: 12px; }}
      QFrame#orbitTile:hover {{ border-color: {t['accent_line']}; }}
      QFrame#orbitTile[state="answering"] {{ border: 1px solid {t['success']}; }}
      QPushButton#tileTitle {{ background: transparent; border: 0; border-radius: 4px; color: {t['text']};
                               font-weight: 600; text-align: left; padding: 3px 4px; }}
      QPushButton#tileTitle:hover {{ background: {t['hover']}; }}
      QPushButton#tileTitle:focus {{ background: {t['hover']}; }}
      QLabel#tilePreview {{ background: {t['preview']}; color: {t['subtle']}; border-radius: 4px; }}
      QWidget#questionPreview {{ background: {t['preview']}; border-radius: 10px; }}
      QLabel#questionCaption {{ color: {t['muted']}; font-size: 11px; }}
      QLabel#questionTitle {{ color: {t['text']}; font-size: 17px; font-weight: 700; }}
      QLabel#questionChoice {{ color: {t['text']}; background: {t['surface']}; padding: 8px 10px;
                              border: 1px solid {t['line']}; border-radius: 7px; }}
      QLabel#questionChoice[state="selected"] {{ background: {t['accent_soft']}; border-color: {t['accent_line']}; }}
      QToolButton#tileMini {{ background: {t['preview']}; border: 1px solid {t['line']}; border-radius: 7px; padding: 2px; }}
      QToolButton#tileMini:hover, QToolButton#tileMini:focus {{ border-color: {t['accent']}; }}
      QLabel#tileElapsed {{ color: {t['muted']}; font-size: 12px; }}
      QLabel#tileBadge {{ border-radius: 10px; padding: 3px 9px; font-size: 11px; font-weight: 600;
                          color: {t['muted']}; background: {t['surface']}; border: 1px solid {t['line']}; }}
      QLabel#tileBadge[state="answering"] {{ color: {t['success']}; border-color: {t['success']}; }}
      QLabel#tileBadge[state="waiting"] {{ color: {t['warning']}; border-color: {t['warning']}; }}
      QLabel#tileBadge[state="running"], QLabel#tileBadge[state="submitting"] {{
          color: {t['accent']}; border-color: {t['accent']}; }}
    """


def license_styles(dark=False, accent_name="Blue", theme_name="Adwaita"):
    t = tokens(dark, accent_name, theme_name)
    return common_styles(t) + f"""
      QDialog {{ background: {t['bg']}; color: {t['text']}; }}
      QLabel {{ color: {t['text']}; }}
      QLabel#licenseTitle {{ font-size: 20px; font-weight: 600; }}
      QLabel#licenseSlogan, QLabel#licenseCountdown {{ color: {t['muted']}; }}
    """


def highlight_style(active, dark=False, accent_name="Blue", theme_name="Adwaita"):
    t = tokens(dark, accent_name, theme_name)
    if active:
        return (f"background:{t['accent_soft']};color:{t['text']};border-left:3px solid {t['accent']};"
                "padding:7px 10px;border-radius:4px;font-weight:600;")
    return f"color:{t['muted']};border-left:3px solid {t['line']};padding:7px 10px;"
