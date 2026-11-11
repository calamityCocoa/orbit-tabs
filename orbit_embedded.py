"""Orbit Tabs with a dedicated, persistent in-app browser profile."""
from __future__ import annotations

from html import escape
import json
import shutil
import sys
import time
import uuid
from pathlib import Path

import shiboken6

from PySide6.QtCore import QSize, QByteArray, QEasingCurve, QPropertyAnimation, QCoreApplication, QEvent, QFile, QIODevice, QLockFile, QObject, Property, Qt, QTimer, QUrl, QVariantAnimation, Signal, Slot
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent, QColor, QDesktopServices, QFontDatabase, QIcon, QKeySequence
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineScript
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QDockWidget, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPushButton,
    QSizePolicy, QSpinBox, QSystemTrayIcon, QTabBar, QTabWidget, QToolButton, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from orbit_covers import CoverStore
from orbit_guide import HINTS, MisoHint, QuickStartGuide, choose_hint, needs_quick_start, record_quick_start
from orbit_license import review_license
from orbit_secure import ProfileRestoreError, Vault, prepare_data_directory
from orbit_theme import ACCENTS, SLOGAN, THEMES, ElidedLabel, OrbitTitle, app_font, app_palette, native_titlebar, common_styles, desktop_styles, line_icon, orbit_icon, tokens
from orbit_wall import MonitorWall

from orbit_common import IDENTIFIER, ORIGIN, PLAYER, SCRIPT, WEEK, clock_text, data_path, login_entry, read_config, save_config

WORLD = QWebEngineScript.ScriptWorldId.ApplicationWorld.value
DASHBOARD = "/my-learning"
APP_ID = "io.github.calamitycocoa.orbittabs"
CAMERA_PLAYERS = {
    "catflix": ("Catflix · RSPCA Isle of Wight", "https://camsecure.uk/HLS/rspca1.m3u8",
                "https://www.rspca-isleofwight.org.uk/livestream/"),
    "streetcat": ("Street Cat feeder · Ms. Dress", "https://streetcatpull.hellobike.com/live/4154701567245307824_0.m3u8",
                  "https://meow.camera/viewer/#4154701567245307824"),
}
LAUNCH_READER = r"""
(() => {
  if (location.origin !== ORIGIN || location.pathname !== '/my-learning' ||
      !window.frameElement?.hasAttribute('data-orbit-tabs-catalog')) return;
  document.addEventListener('orbit-tabs-read-launch', ({ target }) => {
    if (!target.matches('button, [role="button"]')) return;
    const original = window.open;
    const restore = () => { if (window.open === capture) window.open = original; };
    const capture = (value) => {
      if (typeof value !== 'string') return null;
      const url = new URL(value, location.origin);
      if (url.origin === location.origin && /^\/course-player\/[\w-]+\/[\w-]+$/.test(url.pathname)) {
        target.setAttribute('data-orbit-tabs-launch', url.pathname);
        restore();
      }
      return null;
    };
    window.open = capture;
    setTimeout(restore, 2000);
    try {
      target.click();
    } catch { restore(); }
  });
})();
"""
# The remote document sees no Qt objects. Only the application script world gets this adapter.
ADAPTER = """
(() => {
  if (location.origin !== ORIGIN || !globalThis.qt?.webChannelTransport) return;
  new QWebChannel(qt.webChannelTransport, ({ objects: { bridge } }) => {
    const pending = new Map();
    let serial = 0;
    bridge.answer.connect((id, status, body) => {
      const request = pending.get(id);
      pending.delete(id);
      if (!request) return;
      if (status) request.onload({ status, responseText: body });
      else request.onerror();
    });
    const GM_xmlhttpRequest = (request) => {
      const id = ++serial;
      pending.set(id, request);
      bridge.request(id, request.method, request.url, request.data || '');
    };
    const GM_registerMenuCommand = () => {};
    globalThis.orbitEmbedded = {
      activity: (value, reason) => bridge.activity(value, reason),
      aiEnabled: () => bridge.aiEnabled,
      skipSubmitDelay: () => bridge.skipSubmitDelay,
      autoRun: () => bridge.autoRun,
    };
    bridge.aiEnabledChanged.connect(() => globalThis.orbitEmbedded.setAIEnabled?.(bridge.aiEnabled));
    USERSCRIPT
    globalThis.orbitEmbedded.scanAndReport = async (id) => {
      bridge.catalog(JSON.stringify(await globalThis.orbitEmbedded.scan(id)));
    };
    // Covers are read by the signed-in page so the browser attaches the session itself.
    globalThis.orbitEmbedded.fetchCover = async (url) => {
      try {
        const target = new URL(url, location.origin);
        if (target.origin !== location.origin || !/^\\/assets\\/img\\/course\\/[\\w-]+$/.test(target.pathname)) throw 0;
        const response = await fetch(target, { credentials: 'same-origin' });
        const bytes = new Uint8Array(await response.arrayBuffer());
        if (bytes.length > 4194304) throw 0;
        let binary = '';
        for (let i = 0; i < bytes.length; i += 32768) binary += String.fromCharCode(...bytes.subarray(i, i + 32768));
        bridge.cover(url, response.status, btoa(binary));
      } catch {
        bridge.cover(url, 0, '');
      }
    };
    bridge.ready();
  });
})();
"""


def same_origin(url: QUrl) -> bool:
    base = QUrl(ORIGIN)
    return (url.scheme(), url.host(), url.port()) == (base.scheme(), base.host(), base.port())


def course_path(url: QUrl) -> str:
    path = url.path()
    return path if same_origin(url) and PLAYER.fullmatch(path) else ""


def install_script(profile, name, source, *, world, frames=False, early=False):
    script = QWebEngineScript()
    script.setName(name)
    script.setSourceCode(source)
    script.setWorldId(world)
    script.setRunsOnSubFrames(frames)
    point = QWebEngineScript.InjectionPoint.DocumentCreation if early else QWebEngineScript.InjectionPoint.DocumentReady
    script.setInjectionPoint(point)
    profile.scripts().insert(script)


def setup_scripts(profile):
    resource = QFile(":/qtwebchannel/qwebchannel.js")
    if not resource.open(QIODevice.OpenModeFlag.ReadOnly):
        raise RuntimeError("Qt WebChannel JavaScript is unavailable.")
    webchannel = bytes(resource.readAll()).decode()
    origin = "const ORIGIN = " + json.dumps(ORIGIN) + ";\n"
    install_script(profile, "Read Orbit course links", origin + LAUNCH_READER,
                   world=QWebEngineScript.ScriptWorldId.MainWorld.value, frames=True, early=True)
    userscript = SCRIPT.read_text(encoding="utf-8")
    install_script(profile, "Orbit course tools", origin + webchannel + "\n" + ADAPTER.replace("USERSCRIPT", userscript),
                   world=WORLD)


class PageBridge(QObject):
    answer = Signal(int, int, str)
    aiEnabledChanged = Signal()
    skipSubmitDelayChanged = Signal()
    autoRunChanged = Signal()

    @Property(bool, notify=aiEnabledChanged)
    def aiEnabled(self):
        return self.view.owner.ai_enabled()

    @Property(bool, notify=skipSubmitDelayChanged)
    def skipSubmitDelay(self):
        return bool(self.view.owner.settings.get("skip_submit_delay", False))

    @Property(bool, notify=autoRunChanged)
    def autoRun(self):
        return bool(self.view.owner.settings.get("auto_run_courses", False))

    def __init__(self, view):
        super().__init__(view)
        self.view = view
        self.network = QNetworkAccessManager(self)

    @Slot()
    def ready(self):
        self.view.ready = True
        self.view.owner.page_ready(self.view)

    @Slot(str, str)
    def activity(self, state, reason):
        if course_path(self.view.url()) and state in {"idle", "answering", "waiting", "running", "submitting"}:
            self.view.activity = state
            self.view.activity_reason = reason[:200]

    @Slot(str)
    def catalog(self, raw):
        if self.view is self.view.owner.dashboard and same_origin(self.view.url()) and len(raw) <= 128000:
            try:
                result = json.loads(raw)
            except ValueError:
                return
            if isinstance(result, dict):
                self.view.owner.accept_catalog(result)

    @Slot(str, int, str)
    def cover(self, address, status, data):
        if self.view is self.view.owner.dashboard and same_origin(self.view.url()):
            self.view.owner.covers.receive(address, status, data)

    @Slot(int, str, str, str)
    def request(self, serial, method, address, data):
        url = QUrl(address)
        allowed = (
            (method, url.host(), url.path()) == ("POST", "text.pollinations.ai", "/openai") and not url.hasQuery()
            or (method, url.host(), url.path()) == ("GET", "en.wikipedia.org", "/w/api.php")
        )
        if (not self.aiEnabled or not course_path(self.view.url()) or not allowed or url.scheme() != "https"
                or url.port(443) != 443 or url.userInfo() or len(data) > 128000 or len(address) > 4096):
            self.answer.emit(serial, 403, "")
            return
        request = QNetworkRequest(url)
        attrs = QNetworkRequest.Attribute
        request.setAttribute(attrs.RedirectPolicyAttribute, QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
        request.setAttribute(attrs.CookieLoadControlAttribute, QNetworkRequest.LoadControl.Manual)
        request.setAttribute(attrs.CookieSaveControlAttribute, QNetworkRequest.LoadControl.Manual)
        request.setTransferTimeout(45000)
        if method == "POST":
            request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
            reply = self.network.post(request, QByteArray(data.encode()))
        else:
            reply = self.network.get(request)

        def finished():
            status = reply.attribute(attrs.HttpStatusCodeAttribute) or 0
            data = bytes(reply.readAll()) if reply.bytesAvailable() <= 512000 else b""
            self.answer.emit(serial, status, data.decode(errors="replace"))
            reply.deleteLater()

        reply.downloadProgress.connect(lambda received, _: reply.abort() if received > 512000 else None)
        reply.finished.connect(finished)


class BrowserView(QWebEngineView):
    def __init__(self, owner, title, *, managed=False):
        super().__init__(owner)
        self.owner = owner
        self.label = title
        self.managed = managed
        self.opened = time.monotonic()
        self.course = ""
        self.expected = ""
        self.ready = False
        self.activity = "idle"
        self.activity_reason = ""
        self.question_epoch = 0
        self.question_pending = False
        self.question_snapshot = {}
        page = QWebEnginePage(owner.profile, self)
        self.setPage(page)
        self.channel = QWebChannel(self)
        self.bridge = PageBridge(self)
        self.channel.registerObject("bridge", self.bridge)
        page.setWebChannel(self.channel, WORLD)
        self.loadStarted.connect(self.loading)
        self.urlChanged.connect(lambda url: owner.page_navigated(self, url))
        self.titleChanged.connect(lambda _: owner.update_tab(self))
        self.iconChanged.connect(lambda icon: owner.update_tab_icon(self, icon))
        page.windowCloseRequested.connect(lambda: owner.close_view(self, deliberate=True))

    def loading(self):
        self.ready = False
        self.activity = "idle"
        self.activity_reason = ""
        self.question_epoch += 1
        self.question_pending = False
        self.question_snapshot = {}

    def read_questions(self):
        if not self.ready or not self.course or self.question_pending:
            return
        self.question_pending = True
        epoch = self.question_epoch

        def received(raw):
            if not shiboken6.isValid(self) or epoch != self.question_epoch:
                return
            self.question_pending = False
            try:
                data = json.loads(raw) if isinstance(raw, str) and len(raw) < 60000 else {}
            except ValueError:
                data = {}
            self.question_snapshot = data if isinstance(data, dict) else {}

        self.page().runJavaScript("JSON.stringify(globalThis.orbitEmbedded?.questionSnapshot?.())", WORLD, received)

    def createWindow(self, kind):
        return self.owner.new_browser("New tab", foreground=True)

    def command(self, command):
        if self.ready:
            self.page().runJavaScript("globalThis.orbitEmbedded?." + command, WORLD)


class OrbitWindow(QMainWindow):
    def __init__(self, settings_path, vault=None):
        super().__init__()
        self.settings_path = settings_path
        self.settings = read_config(settings_path)
        self.profile = QWebEngineProfile("OrbitTabs", self)
        self.profile.setPersistentStoragePath(str(settings_path.parent / "browser"))
        # Page resources stay in memory so course content is never cached readable on disk.
        self.profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.MemoryHttpCache)
        self.profile.setHttpCacheMaximumSize(128 * 1024 * 1024)
        shutil.rmtree(settings_path.parent / "browser-cache", ignore_errors=True)
        self.vault = vault
        self.profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)
        setup_scripts(self.profile)
        self.covers = CoverStore(ORIGIN, settings_path.parent / "covers", vault, self.request_cover, self)
        self.covers.changed.connect(self.covers_changed)
        self.cat_dock = None
        self.cat_view = None
        self.cat_player = None
        self.cat_audio = None
        self.cat_source = ""
        self.queue = {}
        self.queue_open_timer = QTimer(self)
        self.queue_open_timer.setSingleShot(True)
        self.queue_open_timer.setInterval(750)
        self.queue_open_timer.timeout.connect(self.fill_queue)
        self.pending_scan = ""
        self.scan_sent = False
        self.first_catalog = True
        self.needs_course_link = False
        self.scan_started = 0.0
        self.next_check = time.monotonic() + 3600
        self.quitting = False
        self.last_message = "Sign in to Orbit in this window to load your courses."
        self.setWindowTitle("Orbit Tabs")
        self.setWindowIcon(orbit_icon())
        self.apply_theme()
        self.resize(1200, 780)
        self.setMinimumSize(640, 410)
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.setIconSize(QSize(16, 16))
        self.tabs.tabBar().setElideMode(Qt.TextElideMode.ElideRight)
        self.tabs.tabBar().setExpanding(False)
        self.tabs.tabBar().setDrawBase(False)
        # Pages are switched from the sidebar; the stack keeps its tab-bar-free page container role.
        self.tabs.tabBar().hide()
        self.tabs.tabCloseRequested.connect(self.close_index)
        central = QWidget()
        central_layout = QHBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        self.sidebar_panel = self.build_sidebar()
        central_layout.addWidget(self.sidebar_panel)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        self.guide = None
        self.hint_event = ("", 0.0)
        self.hint = MisoHint()
        self.hint.dismissed.connect(self.dismiss_hint)
        self.hint.show_me.connect(self.show_quick_start)
        content_layout.addWidget(self.hint)
        content_layout.addWidget(self.tabs, 1)
        central_layout.addWidget(content, 1)
        self.setCentralWidget(central)
        self.build_controls()
        self.dashboard = self.new_browser("My Learning", foreground=True)
        self.wall = MonitorWall(self.wall_views, self.tab_title, self.tabs.setCurrentWidget, cover=self.cover_for,
                                timers_action=self.timer_dock.toggleViewAction())
        self.timer_dock.hide()
        self.tabs.insertTab(0, self.wall, "Monitor wall")
        for pinned in (self.wall, self.dashboard):
            index = self.tabs.indexOf(pinned)
            for side in (QTabBar.ButtonPosition.LeftSide, QTabBar.ButtonPosition.RightSide):
                self.tabs.tabBar().setTabButton(index, side, None)
        self.tabs.currentChanged.connect(self.sync_display)
        self.tabs.currentChanged.connect(lambda _: self.refresh_sidebar())
        self.tabs.currentChanged.connect(lambda _: self.fade_in_page())
        self.apply_theme()
        self.sidebar_action.setChecked(self.settings.get("show_sidebar", True))
        self.tray = self.build_tray()
        self.tick_timer = QTimer(self)
        self.tick_timer.timeout.connect(self.tick)
        self.tick_timer.start(1000)
        self.check()

    def build_controls(self):
        menu = self.menuBar()
        orbit = menu.addMenu("&Orbit")
        tools = self.addToolBar("Orbit")
        tools.setObjectName("orbitToolbar")
        tools.setMovable(False)
        tools.setFloatable(False)
        tools.setIconSize(QSize(18, 18))
        tools.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        tools.toggleViewAction().setVisible(False)
        self.sidebar_action = QAction("Show sidebar", self)
        self.sidebar_action.setCheckable(True)
        self.sidebar_action.setChecked(True)
        self.sidebar_action.setShortcut("F9")
        self.sidebar_action.setToolTip("Show or hide the sidebar (F9)")
        self.sidebar_action.toggled.connect(self.toggle_sidebar)
        tools.addAction(self.sidebar_action)
        tools.widgetForAction(self.sidebar_action).setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        logo = QLabel()
        logo.setPixmap(orbit_icon().pixmap(26, 26))
        logo.setContentsMargins(2, 0, 4, 0)
        tools.addWidget(logo)
        brand = QLabel("Orbit Tabs")
        brand.setObjectName("orbitBrand")
        brand.setToolTip(SLOGAN)
        tools.addWidget(brand)
        self.icon_actions = [(self.sidebar_action, "sidebar")]
        groups = (
            (("Back", self.go_back, "Alt+Left", "back", True), ("Reload", self.reload, "Ctrl+R", "reload", True)),
            (("Monitor wall", self.show_wall, "Ctrl+1", "wall", True),
             ("My Learning", self.show_dashboard, "Ctrl+2", "home", True),
             ("Check now", self.check, "Ctrl+Shift+R", "check", False), ("Course QA", self.open_qa, "", "qa", True),
             ("AI suggestions", self.suggest, "", "sparkle", True)),
        )
        for group in groups:
            tools.addSeparator()
            for title, callback, shortcut, glyph, icon_only in group:
                action = QAction(title, self)
                action.triggered.connect(callback)
                if shortcut:
                    action.setShortcut(shortcut)
                    action.setToolTip(f"{title}  ({QKeySequence(shortcut).toString(QKeySequence.SequenceFormat.NativeText)})")
                orbit.addAction(action)
                self.addAction(action)
                self.icon_actions.append((action, glyph))
                if callback in (self.show_wall, self.show_dashboard):
                    continue
                tools.addAction(action)
                button = tools.widgetForAction(action)
                button.setCursor(Qt.CursorShape.PointingHandCursor)
                if icon_only:
                    button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
                if callback == self.check:
                    button.setObjectName("primaryAction")
                    self.primary_action = action
                if callback == self.suggest:
                    self.suggest_action = action
                    action.setEnabled(self.ai_enabled())
        reveal_text = QAction("Reveal lesson text", self)
        reveal_text.setShortcut("Ctrl+Shift+L")
        reveal_text.triggered.connect(self.reveal_lesson_text)
        orbit.addAction(reveal_text)
        self.addAction(reveal_text)
        close_page = QAction("Close page", self)
        close_page.setShortcut("Ctrl+W")
        close_page.triggered.connect(lambda: self.close_index(self.tabs.currentIndex()))
        orbit.addAction(close_page)
        self.addAction(close_page)
        orbit.addSeparator()
        orbit.addAction("Quick Start", lambda: self.show_quick_start(0))
        orbit.addAction("Review license", self.show_license)
        orbit.addAction("Quit", self.quit)
        settings = menu.addMenu("&Settings")
        settings.addAction(self.sidebar_action)
        find_page = QAction("Find open page…", self)
        find_page.setShortcut("Ctrl+K")
        find_page.triggered.connect(self.find_open_page)
        orbit.addAction(find_page)
        self.addAction(find_page)
        self.dark_action = self.toggle_setting(settings, "Dark appearance", "dark_theme", self.apply_theme,
                                               default=False)
        theme_menu = settings.addMenu("Theme")
        theme_group = QActionGroup(theme_menu)
        theme_group.setExclusive(True)
        for name in THEMES:
            action = theme_menu.addAction(name)
            action.setCheckable(True)
            theme_group.addAction(action)
            action.setChecked(name == self.settings.get("theme", "Adwaita"))
        theme_group.triggered.connect(lambda action: self.set_theme(action.text()))
        self.toggle_setting(settings, "Reduce motion and effects", "reduce_motion", self.apply_theme, default=False)
        accents = settings.addMenu("Accent color")
        accent_group = QActionGroup(accents)
        accent_group.setExclusive(True)
        for name in ACCENTS:
            action = accents.addAction(name)
            action.setCheckable(True)
            accent_group.addAction(action)
            action.setChecked(name == self.settings.get("accent", "Blue"))
        accent_group.triggered.connect(lambda action: self.set_accent(action.text()))
        self.toggle_setting(settings, "Enable hosted AI suggestions", "hosted_ai", self.update_ai_setting)
        auto_run = settings.addAction("Auto-run supported courses")
        auto_run.setCheckable(True)
        auto_run.setChecked(self.settings.get("auto_run_courses", False))
        auto_run.toggled.connect(lambda enabled: self.set_auto_run(auto_run, enabled))
        self.toggle_setting(settings, "Skip Orbit Tabs submit delay", "skip_submit_delay",
                            self.update_submit_delay_setting, default=False)
        self.toggle_setting(settings, "Open unfinished courses", "auto_open", self.fill_queue)
        self.toggle_setting(settings, "Close finished course tabs", "auto_close")
        self.toggle_setting(settings, "Hide to tray when queue is empty", "auto_hide")
        startup = settings.addAction("Start at sign-in")
        startup.setCheckable(True)
        startup.setChecked(self.settings.get("autostart", False))
        startup.toggled.connect(lambda enabled: self.set_autostart(startup, enabled))
        cats = menu.addMenu("&Cats")
        self.toggle_setting(cats, "Show Miso the cat", "cat", self.update_mascot)
        self.hints_action = self.toggle_setting(cats, "Show Miso’s hints", "miso_hints", self.update_hint)
        for key, (title, _, _) in CAMERA_PLAYERS.items():
            action = cats.addAction(title)
            action.triggered.connect(lambda checked=False, source=key: self.show_camera(source))
        cats.addAction("meow.camera website", lambda: QDesktopServices.openUrl(QUrl("https://meow.camera/")))
        self.header_title = OrbitTitle("My Learning")
        self.header_title.setObjectName("headerTitle")
        self.header_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.header_title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tools.addWidget(self.header_title)
        camera = QAction("Cat cam", self)
        camera.setToolTip("Cat cam · strictly im-purr-tant")
        camera.triggered.connect(lambda: self.show_camera(self.cat_source or "catflix"))
        self.icon_actions.append((camera, "cat"))
        tools.addAction(camera)
        self.mascot = QToolButton()
        self.mascot.setObjectName("mascot")
        self.mascot.setText("Miso")
        self.mascot.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.mascot.setToolTip("Launch Miso around this tab")
        self.mascot.setAccessibleName("Launch Miso around the active tab")
        self.mascot.clicked.connect(self.mascot_joke)
        self.mascot.setIconSize(QSize(30, 30))
        self.mascot_art = QIcon(str(Path(__file__).resolve().parent / "assets" / "miso-rainbow.png"))
        self.mascot_motion = QVariantAnimation(self.mascot)
        self.mascot_motion.setDuration(1250)
        self.mascot_motion.setStartValue(0.0)
        self.mascot_motion.setEndValue(360.0)
        self.mascot_motion.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.mascot_motion.valueChanged.connect(self.header_title.set_orbit_angle)
        self.mascot_motion.stateChanged.connect(self.mascot_state_changed)
        self.mascot_joke_index = 0
        self.mascot_action = tools.addWidget(self.mascot)
        limit_label = QLabel("Managed tabs")
        limit_label.setContentsMargins(10, 0, 4, 0)
        tools.addWidget(limit_label)
        limit = QSpinBox()
        limit.setRange(0, 300)
        limit.setSpecialValueText("All")
        limit.setAccessibleName("Managed tab limit")
        limit_label.setBuddy(limit)
        limit.setValue(self.settings.get("tab_limit", 0))
        limit.valueChanged.connect(lambda value: self.set_limit(value))
        limit.setToolTip("All opens every unfinished course. Set a number to limit open tabs, or enter 0 for All.")
        limit.setMaximumWidth(76)
        tools.addWidget(limit)
        self.menu_button = QToolButton()
        self.menu_button.setObjectName("menuButton")
        self.menu_button.setToolTip("Menu")
        self.menu_button.setAccessibleName("Menu")
        self.menu_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        main_menu = QMenu(self.menu_button)
        self.menu_button.setMenu(main_menu)
        tools.addWidget(self.menu_button)
        self.update_mascot()
        self.timeline = QTreeWidget()
        self.timeline.setHeaderLabels(["Course", "State", "Open time"])
        self.clock_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        self.timeline.setIconSize(QSize(30, 20))
        self.timeline.setRootIsDecorated(False)
        self.timeline.setAlternatingRowColors(True)
        self.timeline.setAccessibleName("Course timers")
        self.timeline.setMinimumWidth(265)
        header = self.timeline.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.timeline.setUniformRowHeights(True)
        self.timeline.setFrameShape(QTreeWidget.Shape.NoFrame)
        self.timeline.setToolTip("Double-click a course to open its tab")
        self.timeline.itemDoubleClicked.connect(self.focus_row)
        dock = self.timer_dock = QDockWidget("Course timers", self)
        dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable | QDockWidget.DockWidgetFeature.DockWidgetMovable)
        dock.setWidget(self.timeline)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        self.resizeDocks([dock], [280], Qt.Orientation.Horizontal)
        settings.addAction(dock.toggleViewAction())
        settings.addSeparator()
        settings.addAction("Data protection…", self.show_protection)
        self.status_dot = QLabel("●")
        self.status_dot.setObjectName("statusDot")
        self.statusBar().addWidget(self.status_dot)
        self.scan_status = QLabel(self.last_message)
        self.statusBar().addWidget(self.scan_status, 1)
        self.status_count = QLabel()
        self.status_count.setObjectName("statusCount")
        self.statusBar().addPermanentWidget(self.status_count)
        self.statusBar().setSizeGripEnabled(False)
        # Keep every menu reachable from the toolbar; the classic menu bar stays native on macOS.
        for item in menu.actions():
            main_menu.addMenu(item.menu())
        if sys.platform != "darwin":
            menu.setVisible(False)

    def ai_enabled(self):
        return bool(self.settings.get("hosted_ai", True))

    def update_ai_setting(self):
        self.suggest_action.setEnabled(self.ai_enabled())
        for view in self.browsers():
            view.bridge.aiEnabledChanged.emit()

    def update_submit_delay_setting(self):
        for view in self.browsers():
            view.bridge.skipSubmitDelayChanged.emit()

    def set_auto_run(self, action, enabled):
        if enabled and QMessageBox.question(
            self, "Auto-run supported courses",
            "After sign-in, Orbit Tabs will start or resume supported courses, send readable quiz questions "
            "and choices to Pollinations and sometimes Wikipedia, apply suggested answers, and submit "
            "when Orbit enables an identifiable Submit button. Submissions can record course progress. "
            "Allow this for future runs on this profile?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            action.blockSignals(True)
            action.setChecked(False)
            action.blockSignals(False)
            return
        self.settings["auto_run_courses"] = enabled
        self.persist()
        for view in self.browsers():
            view.bridge.autoRunChanged.emit()

    def show_protection(self):
        vault = self.vault
        if vault is None:
            lines = [("Encryption", "Not active in this session.")]
        else:
            lines = [
                ("Encryption", vault.status),
                ("Sign-in and site data", vault.profile_status or "—"),
                ("Course covers", "Encrypted on disk." if vault.available else "Kept in memory only."),
            ]
        lines += [
            ("Page cache", "Memory only; cleared when the app quits."),
            ("Settings", "Preferences only, stored as plain JSON."),
        ]
        body = "".join(f"<p><b>{escape(name)}</b><br>{escape(value)}</p>" for name, value in lines)
        box = QMessageBox(self)
        box.setWindowTitle("Data protection")
        box.setIconPixmap(line_icon("shield", self.theme["accent"], 40).pixmap(QSize(40, 40), self.devicePixelRatioF()))
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(body)
        box.exec()

    def show_license(self):
        try:
            review_license(parent=self, preview=True, dark=self.settings.get("dark_theme", False),
                           accent=self.settings.get("accent", "Blue"),
                           theme_name=self.settings.get("theme", "Adwaita"))
        except (OSError, UnicodeError) as error:
            QMessageBox.warning(self, "Student License", str(error))

    def show_quick_start(self, step=0):
        """Open Miso's walkthrough. It replaces the old message box and can be replayed from the menu."""
        if self.guide is None:
            self.guide = QuickStartGuide(self, self.theme, motion_allowed=self.motion_allowed,
                                         hints_action=self.hints_action)
            self.guide.finished.connect(self.quick_start_finished)
        self.hint.withdraw()
        if self.guide.isVisible():
            self.guide.go(step)
            return
        self.guide.start(step)

    def quick_start_finished(self, result):
        completed = result == QDialog.DialogCode.Accepted
        record_quick_start(self.settings, completed=completed, step=self.guide.index)
        self.persist()
        if completed:
            self.statusBar().showMessage("Miso: Tour complete. Replay it any time from Orbit › Quick Start.", 5000)
            self.orbit_miso()
        else:
            self.statusBar().showMessage("Quick Start skipped. Replay it any time from Orbit › Quick Start.", 5000)
        self.update_hint()

    def motion_allowed(self):
        return (not self.settings.get("reduce_motion", False) and self.isVisible() and not self.isMinimized()
                and not self.mascot_art.isNull())

    def update_hint(self):
        """Show at most one of Miso's hints, based on what the wall and course tabs report."""
        if not hasattr(self, "hint"):
            return
        if not self.settings.get("miso_hints", True) or (self.guide and self.guide.isVisible()):
            self.hint.withdraw()
            return
        now = time.monotonic()
        event, expires = self.hint_event
        if event and (now > expires or (self.current_browser() and self.current_browser().course)):
            event = ""
            self.hint_event = ("", 0.0)
        tabs = [(view.activity, view.activity_reason, bool(view.question_snapshot.get("questions")), now - view.opened)
                for view in self.browsers() if view.course and view.ready]
        dismissed = set(self.settings.get("dismissed_hints", []))
        key = choose_hint(tabs, on_wall=self.tabs.currentWidget() is self.wall, dismissed=dismissed, event=event)
        if key:
            self.hint.present(key)
        else:
            self.hint.withdraw()

    def dismiss_hint(self, key):
        dismissed = self.settings.setdefault("dismissed_hints", [])
        if key in HINTS and key not in dismissed:
            dismissed.append(key)
            self.persist()
        if self.hint_event[0] == key:
            self.hint_event = ("", 0.0)

    def set_theme(self, name):
        self.settings["theme"] = name
        self.persist()
        self.apply_theme()

    def set_accent(self, name):
        self.settings["accent"] = name
        self.persist()
        self.apply_theme()

    def apply_theme(self):
        dark = self.settings.get("dark_theme", False)
        accent = self.settings.get("accent", "Blue")
        theme_name = self.settings.get("theme", "Adwaita")
        self.theme = tokens(dark, accent, theme_name)
        app = QApplication.instance()
        app.setPalette(app_palette(dark, accent, theme_name))
        # Dialogs, message boxes and the tray menu live outside this window.
        app.setStyleSheet(common_styles(self.theme))
        self.setStyleSheet(desktop_styles(dark, accent, theme_name))
        native_titlebar(self, self.theme["dark"], self.theme["surface"], self.theme["text"])
        if not hasattr(self, "tabs"):
            return
        self.dark_action.setEnabled(theme_name == "Adwaita")
        for action, glyph in self.icon_actions:
            color = self.theme["on_accent"] if action is self.primary_action else self.theme["text"]
            action.setIcon(line_icon(glyph, color))
        self.menu_button.setIcon(line_icon("menu", self.theme["text"]))
        if self.settings.get("reduce_motion", False):
            self.mascot_motion.stop()
        self.mascot.setIcon(self.mascot_art if not self.mascot_art.isNull()
                            else line_icon("cat", self.theme["accent"], 18))
        self.tabs.setTabIcon(self.tabs.indexOf(self.wall), line_icon("wall", self.theme["muted"], 16))
        if self.tabs.indexOf(self.dashboard) >= 0 and self.dashboard.icon().isNull():
            self.tabs.setTabIcon(self.tabs.indexOf(self.dashboard), line_icon("home", self.theme["muted"], 16))
        self.wall.apply_theme(self.theme, effects=not self.settings.get("reduce_motion", False))
        self.hint.apply_theme(self.theme)
        if self.guide:
            self.guide.apply_theme(self.theme)
            if self.settings.get("reduce_motion", False):
                self.guide.stop_motion()
        if self.settings.get("reduce_motion", False) and hasattr(self, "page_veil"):
            self.veil_animation.stop()
            self.page_veil.hide()
        self.sidebar_signature = None
        self.refresh_sidebar()
        if self.cat_dock:
            self.style_camera_controls()
        self.update_status()

    def toggle_setting(self, menu, title, name, callback=None, *, default=True):
        action = menu.addAction(title)
        action.setCheckable(True)
        action.setChecked(self.settings.get(name, default))

        def update(value):
            self.settings[name] = value
            self.persist()
            if callback:
                callback()

        action.toggled.connect(update)
        return action

    def persist(self):
        try:
            save_config(self.settings_path, self.settings)
        except OSError as error:
            self.statusBar().showMessage(f"Could not save settings: {error}")

    def set_autostart(self, action, enabled):
        try:
            login_entry(enabled, Path(__file__))
        except OSError as error:
            action.blockSignals(True)
            action.setChecked(not enabled)
            action.blockSignals(False)
            QMessageBox.warning(self, "Start at sign-in", str(error))
            return
        self.settings["autostart"] = enabled
        self.persist()

    def set_limit(self, limit):
        self.settings["tab_limit"] = limit
        self.persist()
        self.fill_queue()

    def update_mascot(self):
        visible = self.settings.get("cat", True)
        self.mascot_action.setVisible(visible)
        if not visible:
            self.mascot_motion.stop()

    def mascot_state_changed(self, state, _previous):
        if state == QVariantAnimation.State.Stopped:
            self.header_title.set_orbit_angle(None)

    def mascot_joke(self):
        jokes = (
            "Miso: Flight check complete. Keyboard secured. Snacks missing.",
            "Miso: One lap around the tab, then back to mission control.",
            "Miso: The ground crew says this is a keyboard. I say it’s a heated bed.",
        )
        self.statusBar().showMessage(jokes[self.mascot_joke_index], 4200)
        self.mascot_joke_index = (self.mascot_joke_index + 1) % len(jokes)
        self.orbit_miso()

    def orbit_miso(self):
        """Send Miso once around the active tab title, skipping it when motion is reduced or nobody can see it."""
        if not self.motion_allowed() or not self.settings.get("cat", True):
            return False
        self.mascot_motion.stop()
        self.header_title.sprite = self.mascot_art.pixmap(QSize(20, 20), self.header_title.devicePixelRatioF())
        self.mascot_motion.start()
        return True

    def build_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return None
        tray = QSystemTrayIcon(self.windowIcon(), self)
        tray.setToolTip("Orbit Tabs")
        from PySide6.QtWidgets import QMenu

        menu = QMenu(self)
        menu.addAction("Show Orbit Tabs", self.show_window)
        menu.addAction("Check now", self.check)
        menu.addAction("Quit", self.quit)
        tray.setContextMenu(menu)
        tray.activated.connect(lambda reason: self.show_window()
                               if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
        tray.show()
        return tray

    def show_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.sync_display()
        # A --startup launch can begin in the tray; offer the tour the first time the window appears.
        if needs_quick_start(self.settings) and not (self.guide and self.guide.isVisible()):
            QTimer.singleShot(0, self.show_quick_start)

    def show_wall(self):
        self.tabs.setCurrentWidget(self.wall)

    def sync_display(self, *_):
        if self.isMinimized():
            self.mascot_motion.stop()
        current = self.tabs.currentWidget()
        if current is not None:
            self.header_title.set_full_text(self.tabs.tabToolTip(self.tabs.currentIndex())
                                            or self.tabs.tabText(self.tabs.currentIndex()))
        self.sync_camera()
        if self.tabs.currentWidget() is self.wall and self.isVisible() and not self.isMinimized():
            self.wall.start()
        else:
            current = self.current_browser() if self.isVisible() and not self.isMinimized() else None
            self.wall.stop(current)

    def show_dashboard(self):
        self.tabs.setCurrentWidget(self.dashboard)
        if not same_origin(self.dashboard.url()) or self.dashboard.url().path() != DASHBOARD:
            self.dashboard.setUrl(QUrl(ORIGIN + DASHBOARD))

    def new_browser(self, title, *, managed=False, foreground=False):
        view = BrowserView(self, title, managed=managed)
        self.tabs.addTab(view, title)
        if foreground:
            self.tabs.setCurrentWidget(view)
        self.refresh_sidebar()
        return view

    def browsers(self):
        return [view for index in range(self.tabs.count())
                if isinstance(view := self.tabs.widget(index), BrowserView)]

    def wall_views(self):
        return [view for view in self.browsers()
                if view.course or view.expected or (hasattr(self, "wall") and self.wall.raw_mode.isChecked())]

    def current_browser(self):
        view = self.tabs.currentWidget()
        return view if isinstance(view, BrowserView) else None

    def go_back(self):
        if view := self.current_browser():
            view.back()

    def reload(self):
        if view := self.current_browser():
            view.reload()

    def page_navigated(self, view, url):
        path = course_path(url)
        if path and path != view.course:
            existing = next((other for other in self.browsers() if other is not view and other.course == path), None)
            if existing and view is not self.dashboard:
                if self.tabs.currentWidget() is view:
                    self.tabs.setCurrentWidget(existing)
                self.close_view(view)
                return
            view.opened = time.monotonic()
        view.course = path
        if path:
            view.expected = ""
            if self.needs_course_link:
                self.needs_course_link = False
                QTimer.singleShot(0, self.check)
        self.update_tab(view)
        if view is self.dashboard and view.ready:
            self.page_ready(view)

    def page_ready(self, view):
        if view is self.dashboard:
            self.covers.flush()
            if not self.pending_scan and self.last_message.startswith("Sign in") and view.url().path() == DASHBOARD:
                self.check()
                return
        if (view is self.dashboard and self.pending_scan and not self.scan_sent
                and same_origin(view.url()) and view.url().path() == DASHBOARD):
            self.scan_sent = True
            view.command("scanAndReport(" + json.dumps(self.pending_scan) + ")")

    def tab_title(self, view):
        if view is self.dashboard:
            return "My Learning"
        return self.queue.get(view.course) or view.title() or view.label

    def update_tab(self, view):
        index = self.tabs.indexOf(view)
        if index >= 0:
            title = self.tab_title(view)
            self.tabs.setTabText(index, title[:34])
            self.tabs.setTabToolTip(index, title)
            if self.tabs.currentWidget() is view:
                self.header_title.set_full_text(title)
            self.refresh_sidebar()

    def fade_in_page(self):
        """Use a short transition unless reduced motion is enabled."""
        if not self.isVisible() or not hasattr(self, "theme") or self.settings.get("reduce_motion", False):
            return
        veil = getattr(self, "page_veil", None)
        if veil is None:
            veil = self.page_veil = QWidget(self.tabs)
            veil.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            veil.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
            veil.setGraphicsEffect(QGraphicsOpacityEffect(veil))
            self.veil_animation = QPropertyAnimation(veil.graphicsEffect(), b"opacity", veil)
            self.veil_animation.setDuration(170)
            self.veil_animation.setStartValue(1.0)
            self.veil_animation.setEndValue(0.0)
            self.veil_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            self.veil_animation.finished.connect(veil.hide)
        veil.setStyleSheet(f"background: {self.theme['bg']};")
        veil.setGeometry(self.tabs.rect())
        veil.raise_()
        veil.show()
        self.veil_animation.stop()
        self.veil_animation.start()

    def build_sidebar(self):
        panel = QWidget()
        panel.setObjectName("sidebarPanel")
        panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        panel.setFixedWidth(230)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 12, 10, 10)
        title = QLabel("Workspace")
        title.setObjectName("sidebarHeading")
        layout.addWidget(title)
        self.sidebar_search = QLineEdit()
        self.sidebar_search.setObjectName("sidebarSearch")
        self.sidebar_search.setPlaceholderText("Find an open page…")
        self.sidebar_search.setAccessibleName("Find an open page")
        self.sidebar_search.setClearButtonEnabled(True)
        self.sidebar_search.textChanged.connect(self.refresh_sidebar)
        self.sidebar_search.returnPressed.connect(self.open_first_search_result)
        layout.addWidget(self.sidebar_search)
        self.sidebar = QListWidget()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setAccessibleName("Pages")
        self.sidebar.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.sidebar.setIconSize(QSize(16, 16))
        self.sidebar.currentItemChanged.connect(self.sidebar_selected)
        layout.addWidget(self.sidebar, 1)
        self.sidebar_pages = []
        self.sidebar_rows = {}
        self.sidebar_signature = None
        self.sidebar_updating = False
        return panel

    def toggle_sidebar(self, visible):
        self.sidebar_panel.setVisible(visible)
        self.settings["show_sidebar"] = visible
        self.persist()
        if visible:
            self.refresh_sidebar()

    def find_open_page(self):
        self.sidebar_action.setChecked(True)
        self.sidebar_search.setFocus()
        self.sidebar_search.selectAll()

    def open_first_search_result(self):
        if self.sidebar_search.text().strip():
            for _, page in self.sidebar_pages:
                if page not in (self.wall, self.dashboard):
                    self.tabs.setCurrentWidget(page)
                    return

    def refresh_sidebar(self, *_):
        if not hasattr(self, "sidebar") or not hasattr(self, "wall"):
            return
        pages = [self.tabs.widget(index) for index in range(self.tabs.count())]
        query = self.sidebar_search.text().strip().casefold()
        signature = (query, [(id(page), self.tabs.tabText(index), self.tabs.tabIcon(index).cacheKey(),
                             getattr(page, "activity", "")) for index, page in enumerate(pages)])
        if signature != self.sidebar_signature:
            self.sidebar_signature = signature
            self.sidebar_updating = True
            self.sidebar.clear()
            self.sidebar_pages = []
            self.sidebar_rows = {}
            self.add_sidebar_header("VIEWS")
            for page in (self.wall, self.dashboard):
                self.add_sidebar_page(page, closable=False)
            others = [page for page in pages if page not in (self.wall, self.dashboard)]
            if query:
                others = [page for page in others if query in (self.tabs.tabToolTip(self.tabs.indexOf(page))
                                                               or self.tabs.tabText(self.tabs.indexOf(page))).casefold()]
            self.add_sidebar_header(f"{'MATCHES' if query else 'OPEN PAGES'}  ·  {len(others)}")
            if not others:
                item = QListWidgetItem("No matching pages" if query else "Course pages appear here", self.sidebar)
                item.setFlags(Qt.ItemFlag.NoItemFlags)
                item.setForeground(QColor(self.theme["subtle"]))
            for page in others:
                self.add_sidebar_page(page, closable=True)
            self.sidebar_updating = False
        current = self.tabs.currentWidget()
        for item, page in self.sidebar_pages:
            if page is current and self.sidebar.currentItem() is not item:
                self.sidebar_updating = True
                self.sidebar.setCurrentItem(item)
                self.sidebar_updating = False
            row = self.sidebar_rows.get(id(item))
            if row is not None and row.indicator.isVisible() != (page is current):
                row.indicator.setVisible(page is current)

    def add_sidebar_header(self, text):
        item = QListWidgetItem(text, self.sidebar)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        item.setForeground(QColor(self.theme["subtle"]))
        font = item.font()
        font.setPointSizeF(font.pointSizeF() * 0.82)
        font.setBold(True)
        item.setFont(font)
        item.setSizeHint(QSize(0, 30))

    def add_sidebar_page(self, page, *, closable):
        index = self.tabs.indexOf(page)
        title = self.tabs.tabToolTip(index) or self.tabs.tabText(index)
        item = QListWidgetItem(self.sidebar)
        item.setToolTip(title)
        item.setData(Qt.ItemDataRole.AccessibleTextRole, title)
        item.setSizeHint(QSize(0, 36))
        row = QWidget()
        row.setObjectName("sidebarRow")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 4, 0)
        layout.setSpacing(9)
        indicator = QFrame()
        indicator.setObjectName("sidebarIndicator")
        indicator.setFixedSize(3, 16)
        policy = indicator.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        indicator.setSizePolicy(policy)
        indicator.setVisible(False)
        layout.addWidget(indicator)
        row.indicator = indicator
        icon = QLabel()
        icon.setFixedWidth(30)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cover = self.cover_for(page, QSize(30, 20), 4) if isinstance(page, BrowserView) else None
        if cover is not None:
            icon.setPixmap(cover)
        else:
            tab_icon = self.tabs.tabIcon(index)
            fallback = tab_icon if not tab_icon.isNull() else line_icon("popout", self.theme["muted"], 16)
            icon.setPixmap(fallback.pixmap(QSize(16, 16), self.devicePixelRatioF()))
        layout.addWidget(icon)
        label = ElidedLabel(title)
        activity = getattr(page, "activity", "idle")
        layout.addWidget(label, 1)
        if activity != "idle":
            dot = QLabel("●")
            dot.setStyleSheet(f"color: {self.state_color(activity.capitalize())}; font-size: 10px;")
            dot.setToolTip(activity.capitalize())
            layout.addWidget(dot)
        if closable:
            close = QToolButton()
            close.setObjectName("sidebarClose")
            close.setIcon(line_icon("close", self.theme["subtle"], 14))
            close.setToolTip("Close page")
            close.setAccessibleName(f"Close {title}")
            close.setCursor(Qt.CursorShape.PointingHandCursor)
            # Defer so the row (and this button) is not rebuilt inside its own click handler.
            close.clicked.connect(lambda checked=False, view=page: QTimer.singleShot(0, lambda: self.close_page(view)))
            layout.addWidget(close)
        self.sidebar.setItemWidget(item, row)
        self.sidebar_pages.append((item, page))
        self.sidebar_rows[id(item)] = row

    def sidebar_selected(self, current, _previous):
        if self.sidebar_updating or current is None:
            return
        page = next((page for item, page in self.sidebar_pages if item is current), None)
        if page is not None and self.tabs.currentWidget() is not page:
            self.tabs.setCurrentWidget(page)

    def close_page(self, view):
        index = self.tabs.indexOf(view) if shiboken6.isValid(view) else -1
        if index >= 0:
            self.close_index(index)

    def request_cover(self, url):
        view = getattr(self, "dashboard", None)
        if view is None or not view.ready or not same_origin(view.url()):
            return False
        view.command("fetchCover(" + json.dumps(url) + ")")
        return True

    def cover_for(self, view, size, radius=6, ratio=None):
        path = view.course or view.expected
        if not path or view is self.dashboard:
            return None
        return self.covers.thumbnail(path, size, radius, ratio or self.devicePixelRatioF())

    def covers_changed(self):
        self.sidebar_signature = None
        self.refresh_sidebar()

    def update_tab_icon(self, view, icon):
        index = self.tabs.indexOf(view)
        if index >= 0:
            if icon.isNull() and view is self.dashboard:
                icon = line_icon("home", self.theme["muted"], 16)
            self.tabs.setTabIcon(index, icon)
            self.refresh_sidebar()

    def close_index(self, index):
        view = self.tabs.widget(index)
        if isinstance(view, BrowserView):
            self.close_view(view, deliberate=True)

    def close_view(self, view, *, deliberate=False):
        index = self.tabs.indexOf(view)
        if index < 0 or view is self.dashboard:
            return
        self.wall.forget(view)
        self.tabs.removeTab(index)
        self.refresh_sidebar()
        view.stop()
        view.deleteLater()
        if deliberate and view.managed:
            QTimer.singleShot(500, self.fill_queue)

    def check(self):
        if self.pending_scan:
            return
        self.pending_scan = uuid.uuid4().hex
        self.scan_sent = False
        self.scan_started = time.monotonic()
        self.last_message = "Checking My Learning…"
        if self.dashboard.ready and self.dashboard.url().path() == DASHBOARD:
            self.page_ready(self.dashboard)
        else:
            self.dashboard.setUrl(QUrl(ORIGIN + DASHBOARD))

    def accept_catalog(self, result):
        if not self.pending_scan or result.get("id") != self.pending_scan:
            return
        self.pending_scan = ""
        courses = result.get("courses")
        if result.get("error") or not isinstance(courses, list) or len(courses) > 300:
            self.last_message = result.get("error") or "Could not read the complete course list."
            self.next_check = time.monotonic() + 3600
            return
        tenant = result.get("tenant")
        if not isinstance(tenant, str) or not IDENTIFIER.fullmatch(tenant):
            tenant = next((view.course.split("/")[2] for view in self.browsers() if view.course), "")
        if courses and not tenant:
            self.needs_course_link = True
            self.last_message = "Open one course from My Learning to identify the remaining course links."
            self.next_check = time.monotonic() + 3600
            return
        updated = {}
        for course in courses:
            if not isinstance(course, dict):
                continue
            identifier = course.get("id")
            if isinstance(identifier, str) and IDENTIFIER.fullmatch(identifier):
                path = f"/course-player/{tenant}/{identifier}"
                updated[path] = str(course.get("title") or "Orbit course")[:300]
                self.covers.set_cover(path, course.get("cover"))
        unresolved = result.get("unresolved") or 0
        if unresolved:
            updated = self.queue | updated
        self.queue = updated
        if self.settings.get("auto_close", True) and not unresolved:
            for view in self.browsers():
                if view.managed and (view.course or view.expected) not in self.queue:
                    self.close_view(view)
        self.next_check = time.monotonic() + (600 if self.queue else WEEK)
        self.last_message = f"{len(self.queue)} unfinished course(s)." if self.queue else "No unfinished courses."
        if unresolved:
            self.last_message += f" {unresolved} card(s) need a manual open."
        self.fill_queue()
        if self.first_catalog:
            self.first_catalog = False
            if self.queue and self.tabs.currentWidget() is self.dashboard:
                self.show_wall()
        if not self.queue and not unresolved and self.tray and self.settings.get("auto_hide", True):
            self.hide()

    def fill_queue(self):
        if self.quitting or not self.settings.get("auto_open", True):
            self.queue_open_timer.stop()
            return
        if self.queue_open_timer.isActive():
            return
        occupied = {view.course or view.expected for view in self.browsers()}
        pending = [path for path in self.queue if path not in occupied]
        limit = self.settings.get("tab_limit", 0)
        room = limit - len(occupied.intersection(self.queue)) if limit else len(pending)
        if not pending or room <= 0:
            return
        path = pending[0]
        view = self.new_browser(self.queue[path], managed=True)
        view.expected = path
        view.setUrl(QUrl(ORIGIN + path))
        if len(pending) > 1 and room > 1:
            self.queue_open_timer.start()

    def open_qa(self):
        if (view := self.current_browser()) and view.course:
            view.command("open()")
        else:
            self.statusBar().showMessage("Select a course tab to open Course QA.", 3500)
            self.hint_event = ("qa_needs_course", time.monotonic() + 20)
            self.update_hint()

    def reveal_lesson_text(self):
        view = self.current_browser()
        if not view or not view.course or not view.ready:
            self.statusBar().showMessage("Open a course lesson and wait for its page to load.", 4000)
            return

        def report(result):
            if shiboken6.isValid(self) and shiboken6.isValid(view) and self.current_browser() is view:
                self.statusBar().showMessage(result or "No supported text reveal is running on this slide.", 4000)

        view.page().runJavaScript("globalThis.orbitEmbedded?.revealLessonText?.()", WORLD, report)

    def suggest(self):
        if not self.ai_enabled():
            return
        if not (view := self.current_browser()) or not view.course:
            self.statusBar().showMessage("Select a course tab for AI suggestions.", 3500)
            return
        if QMessageBox.question(self, "AI suggestions", "Send visible questions and choices to Pollinations AI? "
                                "Questions it is unsure about may also be searched on Wikipedia.") == QMessageBox.StandardButton.Yes:
            view.command("suggest()")

    def show_camera(self, source):
        if not self.cat_dock:
            self.cat_dock = QDockWidget("Cat camera", self)
            self.cat_dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
            content = QWidget()
            layout = QVBoxLayout(content)
            layout.setContentsMargins(8, 8, 8, 8)
            layout.setSpacing(8)
            self.camera_feed = QComboBox()
            self.camera_feed.setAccessibleName("Cat camera feed")
            for key, (title, _, _) in CAMERA_PLAYERS.items():
                self.camera_feed.addItem(title, key)
            self.camera_feed.currentIndexChanged.connect(lambda _: self.show_camera(self.camera_feed.currentData()))
            layout.addWidget(self.camera_feed)
            controls = QHBoxLayout()
            controls.setSpacing(6)
            self.camera_mute = QPushButton()
            self.camera_mute.setCheckable(True)
            self.camera_mute.setChecked(True)
            self.camera_mute.toggled.connect(self.set_camera_muted)
            self.camera_mute.toggled.connect(lambda _: self.style_camera_controls())
            controls.addWidget(self.camera_mute)
            self.camera_popout = QPushButton("Pop out")
            self.camera_popout.setToolTip("Float the camera in its own window, or dock it again")
            self.camera_popout.clicked.connect(lambda: self.cat_dock.setFloating(not self.cat_dock.isFloating()))
            controls.addWidget(self.camera_popout)
            self.camera_source = QPushButton("Source")
            self.camera_source.setToolTip("Open the camera's page in your web browser")
            self.camera_source.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(CAMERA_PLAYERS[self.cat_source][2])))
            controls.addWidget(self.camera_source)
            self.camera_retry = QPushButton("Retry")
            self.camera_retry.setToolTip("Reconnect the camera")
            self.camera_retry.clicked.connect(self.retry_camera)
            controls.addWidget(self.camera_retry)
            controls.addStretch()
            for button in (self.camera_mute, self.camera_popout, self.camera_source, self.camera_retry):
                button.setCursor(Qt.CursorShape.PointingHandCursor)
            layout.addLayout(controls)
            self.camera_status = QLabel()
            self.camera_status.setWordWrap(True)
            self.camera_status.setTextFormat(Qt.TextFormat.PlainText)
            layout.addWidget(self.camera_status)
            self.cat_dock.setWidget(content)
            self.cat_dock.topLevelChanged.connect(lambda _: self.style_camera_controls())
            self.style_camera_controls()
            self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.cat_dock)
            self.splitDockWidget(self.timer_dock, self.cat_dock, Qt.Orientation.Vertical)
            self.cat_dock.visibilityChanged.connect(self.sync_camera)
            self.cat_dock.installEventFilter(self)
        if source != self.cat_source:
            self.stop_camera()
            self.cat_source = source
        self.camera_feed.blockSignals(True)
        self.camera_feed.setCurrentIndex(self.camera_feed.findData(source))
        self.camera_feed.blockSignals(False)
        self.cat_dock.setWindowTitle(CAMERA_PLAYERS[source][0])
        self.cat_dock.show()
        self.resizeDocks([self.cat_dock], [250], Qt.Orientation.Vertical)
        self.sync_camera()

    def style_camera_controls(self):
        muted = self.camera_mute.isChecked()
        self.camera_mute.setText("Muted" if muted else "Sound on")
        self.camera_mute.setToolTip("Turn the camera sound on" if muted else "Mute the camera")
        self.camera_mute.setIcon(line_icon("muted" if muted else "sound", self.theme["text"], 16))
        self.camera_popout.setText("Dock" if self.cat_dock.isFloating() else "Pop out")
        self.camera_popout.setIcon(line_icon("popout", self.theme["text"], 16))
        self.camera_source.setIcon(line_icon("link", self.theme["text"], 16))

    def set_camera_muted(self, muted):
        if self.cat_audio:
            self.cat_audio.setMuted(muted)

    def eventFilter(self, watched, event):
        if watched is self.cat_dock and event.type() == QEvent.Type.WindowStateChange:
            QTimer.singleShot(0, self.sync_camera)
        return super().eventFilter(watched, event)

    def stop_camera(self):
        if self.cat_view:
            view, player = self.cat_view, self.cat_player
            self.cat_view = None
            self.cat_player = None
            self.cat_audio = None
            player.stop()
            player.setSource(QUrl())
            view.hide()
            view.deleteLater()

    def retry_camera(self):
        self.stop_camera()
        self.sync_camera()

    def update_camera_status(self, player):
        if player is not self.cat_player:
            return
        error = player.error()
        if error != QMediaPlayer.Error.NoError or player.mediaStatus() == QMediaPlayer.MediaStatus.EndOfMedia:
            self.camera_status.setText("Camera unavailable. Retry or open the source page.")
            self.camera_status.setToolTip(player.errorString())
        elif player.mediaStatus() == QMediaPlayer.MediaStatus.StalledMedia:
            self.camera_status.setText("Waiting for the stream…")
        else:
            self.camera_status.setText("Live camera" if player.hasVideo() else "Connecting to camera…")
            self.camera_status.setToolTip("")

    def sync_camera(self, *_):
        if (not self.cat_dock or not self.cat_dock.isVisible() or self.cat_dock.isMinimized()
                or not self.isVisible() or self.isMinimized() or self.quitting):
            self.stop_camera()
        elif self.cat_source and not self.cat_view:
            self.cat_view = QVideoWidget(self.cat_dock.widget())
            self.cat_view.setMinimumSize(200, 130)
            player = self.cat_player = QMediaPlayer(self.cat_view)
            self.cat_audio = QAudioOutput(player)
            player.setAudioOutput(self.cat_audio)
            player.setVideoOutput(self.cat_view)
            self.set_camera_muted(self.camera_mute.isChecked())
            self.cat_dock.widget().layout().addWidget(self.cat_view, 1)
            player.hasVideoChanged.connect(lambda _: self.update_camera_status(player))
            player.mediaStatusChanged.connect(lambda _: self.update_camera_status(player))
            player.errorOccurred.connect(lambda *_: self.update_camera_status(player))
            self.update_camera_status(player)
            player.setSource(QUrl(CAMERA_PLAYERS[self.cat_source][1]))
            player.play()

    def focus_row(self, item, _):
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if view := next((view for view in self.browsers() if view.course == path), None):
            self.tabs.setCurrentWidget(view)

    def tick(self):
        now = time.monotonic()
        if self.pending_scan and now - self.scan_started > 300:
            self.pending_scan = ""
            self.next_check = now + 3600
            self.last_message = "Sign in on the My Learning tab, then click Check now."
        if not self.pending_scan and now >= self.next_check:
            self.check()
        if self.settings.get("auto_run_courses", False) and self.ai_enabled():
            for view in self.browsers():
                if view.course in self.queue:
                    view.command("autoStep()")
        if not self.isVisible() or self.isMinimized():
            return
        if self.scan_status.text() != self.last_message:
            self.scan_status.setText(self.last_message)
        self.update_status()
        self.refresh_sidebar()
        self.update_hint()
        rows = []
        paths = set()
        for view in self.browsers():
            path = view.course or view.expected
            if not path:
                continue
            paths.add(path)
            state = "Loading" if not view.course else "Visible" if view is self.current_browser() else "Open"
            if view.activity != "idle":
                state = view.activity.capitalize()
            rows.append((path, self.queue.get(path, view.title() or view.label), state, clock_text(now - view.opened)))
        rows.extend((path, title, "Queued", "—") for path, title in self.queue.items() if path not in paths)
        for index, (path, title, state, elapsed) in enumerate(rows):
            item = self.timeline.topLevelItem(index)
            if not item:
                item = QTreeWidgetItem(self.timeline)
            item.setData(0, Qt.ItemDataRole.UserRole, path)
            cover = self.covers.thumbnail(path, QSize(30, 20), 4, self.devicePixelRatioF())
            cover_key = cover.cacheKey() if cover is not None else 0
            if item.data(0, Qt.ItemDataRole.UserRole + 1) != cover_key:
                item.setData(0, Qt.ItemDataRole.UserRole + 1, cover_key)
                item.setIcon(0, QIcon(cover) if cover is not None else QIcon())
            item.setToolTip(0, title)
            item.setTextAlignment(2, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            for column, value in enumerate((title, state, elapsed)):
                if item.text(column) != value:
                    item.setText(column, value)
            color = QColor(self.state_color(state))
            if item.foreground(1).color() != color:
                item.setForeground(1, color)
            if item.font(2) != self.clock_font:
                item.setFont(2, self.clock_font)
        while self.timeline.topLevelItemCount() > len(rows):
            self.timeline.takeTopLevelItem(self.timeline.topLevelItemCount() - 1)

    def state_color(self, state):
        return {
            "Answering": self.theme["success"], "Waiting": self.theme["warning"], "Running": self.theme["accent"],
            "Submitting": self.theme["accent"], "Visible": self.theme["text"], "Loading": self.theme["accent"],
        }.get(state, self.theme["muted"])

    def update_status(self):
        if not hasattr(self, "status_dot"):
            return
        checking = bool(self.pending_scan)
        if checking:
            # Pulse while My Learning is being checked.
            self.status_pulse = not getattr(self, "status_pulse", False)
            color = self.theme["accent"] if self.status_pulse else self.theme["accent_line"]
        elif self.queue:
            color = self.theme["success"]
        else:
            color = self.theme["subtle"]
        label = "Checking…" if checking else "Check now"
        if self.primary_action.text() != label:
            self.primary_action.setText(label)
        style = f"color: {color};"
        if self.status_dot.styleSheet() != style:
            self.status_dot.setStyleSheet(style)
        open_paths = {view.course or view.expected for view in self.browsers()} - {""}
        queued = len(self.queue.keys() - open_paths)
        text = f"{len(open_paths)} open · {queued} queued"
        if self.status_count.text() != text:
            self.status_count.setText(text)
        detail = ""
        if queued:
            if not self.settings.get("auto_open", True):
                detail = "Opening unfinished courses is paused in Settings."
            elif self.queue_open_timer.isActive():
                detail = "Opening queued courses one at a time."
            elif limit := self.settings.get("tab_limit", 0):
                detail = f"Managed tabs is set to {limit}. Choose All to open every unfinished course."
        if self.status_count.toolTip() != detail:
            self.status_count.setToolTip(detail)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and hasattr(self, "tabs"):
            QTimer.singleShot(0, self.sync_display)

    def event(self, event):
        result = super().event(event)
        if event.type() == QEvent.Type.WindowActivate and hasattr(self, "tabs"):
            QTimer.singleShot(0, self.sync_display)
        return result

    def showEvent(self, event):
        super().showEvent(event)
        self.sync_display()

    def hideEvent(self, event):
        super().hideEvent(event)
        self.mascot_motion.stop()
        self.stop_camera()
        self.wall.stop()

    def closeEvent(self, event: QCloseEvent):
        if self.tray and not self.quitting:
            event.ignore()
            self.hide()
            return
        self.quitting = True
        self.stop_camera()
        super().closeEvent(event)

    def dispose(self):
        self.wall.stop()
        self.stop_camera()
        for view in self.browsers():
            view.stop()
            view.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def quit(self):
        self.quitting = True
        if self.tray:
            self.tray.hide()
        self.close()
        QApplication.quit()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Orbit Tabs")
    app.setDesktopFileName(APP_ID)
    app.setStyle("Fusion")
    app.setFont(app_font())
    if "--review-license" in sys.argv:
        try:
            review_license(preview=True)
        except (OSError, UnicodeError) as error:
            QMessageBox.critical(None, "Student License", str(error))
            return 1
        return 0
    directory = data_path()
    prepare_data_directory(directory)
    lock = QLockFile(str(directory / "embedded.lock"))
    if not lock.tryLock(0):
        QMessageBox.information(None, "Orbit Tabs", "Orbit Tabs is already running.")
        return 0
    settings_path = directory / "embedded-settings.json"
    saved = read_config(settings_path)
    app.setPalette(app_palette(saved.get("dark_theme", False), saved.get("accent", "Blue"), saved.get("theme", "Adwaita")))
    try:
        if not review_license(settings_path):
            return 0
    except (OSError, UnicodeError) as error:
        QMessageBox.critical(None, "Student License", str(error))
        return 1
    vault = Vault(directory)
    try:
        vault.open_profile(directory / "browser")
    except ProfileRestoreError as error:
        QMessageBox.critical(None, "Browser profile unavailable", str(error))
        return 1
    window = OrbitWindow(settings_path, vault)
    if not window.tray or "--startup" not in sys.argv:
        window.show()
        if needs_quick_start(saved):
            QTimer.singleShot(0, window.show_quick_start)
    exit_code = app.exec()
    window.dispose()
    # Destroy the window (and with it the browser profile) so every file is flushed before sealing.
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()
    del window
    try:
        vault.seal_profile(directory / "browser")
    except OSError:
        QMessageBox.warning(None, "Data protection", "The browser profile could not be fully sealed on quit.")
    lock.unlock()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
