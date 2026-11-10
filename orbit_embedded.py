"""Orbit Tabs with a dedicated, persistent in-app browser profile."""
from __future__ import annotations

from html import escape
import json
import sys
import time
import uuid
from pathlib import Path

from PySide6.QtCore import QByteArray, QCoreApplication, QEvent, QFile, QIODevice, QLockFile, QObject, Property, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent, QDesktopServices
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineScript
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QApplication, QDockWidget, QHBoxLayout, QHeaderView, QLabel, QMainWindow, QMessageBox, QPushButton, QSpinBox,
    QSystemTrayIcon, QTabBar, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from orbit_license import review_license
from orbit_theme import ACCENTS, SLOGAN, desktop_styles, orbit_icon
from orbit_wall import MonitorWall

from orbit_common import IDENTIFIER, ORIGIN, PLAYER, SCRIPT, WEEK, clock_text, data_path, login_entry, read_config, save_config

WORLD = QWebEngineScript.ScriptWorldId.ApplicationWorld.value
DASHBOARD = "/my-learning"
APP_ID = "io.github.calamitycocoa.orbittabs"
CAMERA_PLAYERS = {
    "kittens": ("Kitten Rescue Sanctuary", "https://www.youtube.com/embed/OOT6YlOYgaU?playsinline=1",
                "https://explore.org/livecams/kitten-rescue/kitten-rescue-cam"),
    "nursery": ("Kitten Rescue Nursery", "https://www.youtube.com/embed/gBdqOuhj2P4?playsinline=1",
                "https://explore.org/livecams/cats/kitten-rescue-baby-kittens"),
}
LAUNCH_READER = r"""
(() => {
  if (location.origin !== ORIGIN || location.pathname !== '/my-learning') return;
  document.addEventListener('orbit-tabs-read-launch', ({ target }) => {
    if (!target.matches('button, [role="button"]')) return;
    const original = window.open;
    try {
      window.open = (value) => {
        if (typeof value !== 'string') return null;
        const url = new URL(value, location.origin);
        if (url.origin === location.origin && /^\/course-player\/[\w-]+\/[\w-]+$/.test(url.pathname)) {
          target.setAttribute('data-orbit-tabs-launch', url.pathname);
        }
        return null;
      };
      target.click();
    } finally {
      window.open = original;
    }
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
      activity: (value) => bridge.activity(value),
      aiEnabled: () => bridge.aiEnabled,
    };
    bridge.aiEnabledChanged.connect(() => globalThis.orbitEmbedded.setAIEnabled?.(bridge.aiEnabled));
    USERSCRIPT
    globalThis.orbitEmbedded.scanAndReport = async (id) => {
      bridge.catalog(JSON.stringify(await globalThis.orbitEmbedded.scan(id)));
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

    @Property(bool, notify=aiEnabledChanged)
    def aiEnabled(self):
        return self.view.owner.ai_enabled()

    def __init__(self, view):
        super().__init__(view)
        self.view = view
        self.network = QNetworkAccessManager(self)

    @Slot()
    def ready(self):
        self.view.ready = True
        self.view.owner.page_ready(self.view)

    @Slot(str)
    def activity(self, state):
        if course_path(self.view.url()) and state in {"idle", "answering", "waiting", "running", "submitting"}:
            self.view.activity = state

    @Slot(str)
    def catalog(self, raw):
        if self.view is self.view.owner.dashboard and same_origin(self.view.url()) and len(raw) <= 128000:
            try:
                result = json.loads(raw)
            except ValueError:
                return
            if isinstance(result, dict):
                self.view.owner.accept_catalog(result)

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
        page = QWebEnginePage(owner.profile, self)
        self.setPage(page)
        self.channel = QWebChannel(self)
        self.bridge = PageBridge(self)
        self.channel.registerObject("bridge", self.bridge)
        page.setWebChannel(self.channel, WORLD)
        self.loadStarted.connect(self.loading)
        self.urlChanged.connect(lambda url: owner.page_navigated(self, url))
        self.titleChanged.connect(lambda _: owner.update_tab(self))
        page.windowCloseRequested.connect(lambda: owner.close_view(self, deliberate=True))

    def loading(self):
        self.ready = False
        self.activity = "idle"

    def createWindow(self, kind):
        return self.owner.new_browser("New tab", foreground=True)

    def command(self, command):
        if self.ready:
            self.page().runJavaScript("globalThis.orbitEmbedded?." + command, WORLD)


class OrbitWindow(QMainWindow):
    def __init__(self, settings_path):
        super().__init__()
        self.settings_path = settings_path
        self.settings = read_config(settings_path)
        self.profile = QWebEngineProfile("OrbitTabs", self)
        self.profile.setPersistentStoragePath(str(settings_path.parent / "browser"))
        self.profile.setCachePath(str(settings_path.parent / "browser-cache"))
        self.profile.setHttpCacheMaximumSize(128 * 1024 * 1024)
        self.profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)
        setup_scripts(self.profile)
        self.cat_profile = None
        self.cat_dock = None
        self.cat_view = None
        self.cat_source = ""
        self.queue = {}
        self.pending_scan = ""
        self.scan_sent = False
        self.first_catalog = True
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
        self.tabs.tabCloseRequested.connect(self.close_index)
        self.setCentralWidget(self.tabs)
        self.build_controls()
        self.dashboard = self.new_browser("My Learning", foreground=True)
        self.wall = MonitorWall(self.browsers, self.tab_title, self.tabs.setCurrentWidget)
        self.tabs.insertTab(0, self.wall, "Monitor wall")
        for pinned in (self.wall, self.dashboard):
            index = self.tabs.indexOf(pinned)
            for side in (QTabBar.ButtonPosition.LeftSide, QTabBar.ButtonPosition.RightSide):
                self.tabs.tabBar().setTabButton(index, side, None)
        self.tabs.currentChanged.connect(self.sync_display)
        self.tray = self.build_tray()
        self.tick_timer = QTimer(self)
        self.tick_timer.timeout.connect(self.tick)
        self.tick_timer.start(1000)
        self.check()

    def build_controls(self):
        menu = self.menuBar()
        orbit = menu.addMenu("&Orbit")
        tools = self.addToolBar("Orbit")
        tools.setMovable(False)
        brand = QLabel("Orbit Tabs")
        brand.setObjectName("orbitBrand")
        brand.setToolTip(SLOGAN)
        tools.addWidget(brand)
        for title, callback, shortcut in (
            ("Monitor wall", self.show_wall, "Ctrl+1"), ("My Learning", self.show_dashboard, "Ctrl+2"),
            ("Back", self.go_back, "Alt+Left"), ("Reload", self.reload, "Ctrl+R"),
            ("Check now", self.check, "Ctrl+Shift+R"), ("Course QA", self.open_qa, ""),
            ("AI suggestions", self.suggest, ""),
        ):
            action = QAction(title, self)
            action.triggered.connect(callback)
            if shortcut:
                action.setShortcut(shortcut)
            orbit.addAction(action)
            tools.addAction(action)
            if callback == self.suggest:
                self.suggest_action = action
                action.setEnabled(self.ai_enabled())
        orbit.addSeparator()
        orbit.addAction("Review license", self.show_license)
        orbit.addAction("Quit", self.quit)
        settings = menu.addMenu("&Settings")
        self.toggle_setting(settings, "Dark appearance", "dark_theme", self.apply_theme)
        accents = settings.addMenu("Accent color")
        accent_group = QActionGroup(accents)
        accent_group.setExclusive(True)
        for name in ACCENTS:
            action = accents.addAction(name)
            action.setCheckable(True)
            accent_group.addAction(action)
            action.setChecked(name == self.settings.get("accent", "Blue"))
        accent_group.triggered.connect(lambda action: self.set_accent(action.text()))
        self.toggle_setting(settings, "Enable hosted AI suggestions", "hosted_ai",
                            self.update_ai_setting, default=False)
        self.toggle_setting(settings, "Open unfinished courses", "auto_open", self.fill_queue)
        self.toggle_setting(settings, "Close finished course tabs", "auto_close")
        self.toggle_setting(settings, "Hide to tray when queue is empty", "auto_hide")
        startup = settings.addAction("Start at sign-in")
        startup.setCheckable(True)
        startup.setChecked(self.settings.get("autostart", False))
        startup.toggled.connect(lambda enabled: self.set_autostart(startup, enabled))
        cats = menu.addMenu("&Cats")
        self.toggle_setting(cats, "Add a cat", "cat", self.update_mascot, default=False)
        for key, (title, _, _) in CAMERA_PLAYERS.items():
            action = cats.addAction(title)
            action.triggered.connect(lambda checked=False, source=key: self.show_camera(source))
        cats.addAction("meow.camera website", lambda: QDesktopServices.openUrl(QUrl("https://meow.camera/")))
        tools.addSeparator()
        limit_label = QLabel("Managed tabs")
        tools.addWidget(limit_label)
        limit = QSpinBox()
        limit.setRange(1, 300)
        limit.setAccessibleName("Managed tab limit")
        limit_label.setBuddy(limit)
        limit.setValue(self.settings.get("tab_limit", 2))
        limit.valueChanged.connect(lambda value: self.set_limit(value))
        tools.addWidget(limit)
        self.mascot = QLabel("   (=^･ω･^=)   ")
        tools.addWidget(self.mascot)
        self.update_mascot()
        self.timeline = QTreeWidget()
        self.timeline.setHeaderLabels(["Course", "State", "Open time"])
        self.timeline.setRootIsDecorated(False)
        self.timeline.setAlternatingRowColors(True)
        self.timeline.setAccessibleName("Course timers")
        header = self.timeline.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.timeline.itemDoubleClicked.connect(self.focus_row)
        dock = self.timer_dock = QDockWidget("Course timers", self)
        dock.setWidget(self.timeline)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        self.resizeDocks([dock], [310], Qt.Orientation.Horizontal)
        settings.addAction(dock.toggleViewAction())
        self.scan_status = QLabel(self.last_message)
        self.statusBar().addWidget(self.scan_status, 1)

    def ai_enabled(self):
        return bool(self.settings.get("hosted_ai", False))

    def update_ai_setting(self):
        self.suggest_action.setEnabled(self.ai_enabled())
        for view in self.browsers():
            view.bridge.aiEnabledChanged.emit()

    def show_license(self):
        try:
            review_license(parent=self, preview=True)
        except (OSError, UnicodeError) as error:
            QMessageBox.warning(self, "Student License", str(error))

    def set_accent(self, name):
        self.settings["accent"] = name
        self.persist()
        self.apply_theme()

    def apply_theme(self):
        self.setStyleSheet(desktop_styles(self.settings.get("dark_theme", True),
                                          self.settings.get("accent", "Blue")))

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
        self.mascot.setVisible(self.settings.get("cat", False))

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

    def show_wall(self):
        self.tabs.setCurrentWidget(self.wall)

    def sync_display(self, *_):
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
        return view

    def browsers(self):
        return [view for index in range(self.tabs.count())
                if isinstance(view := self.tabs.widget(index), BrowserView)]

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
        self.update_tab(view)
        if view is self.dashboard and view.ready:
            self.page_ready(view)

    def page_ready(self, view):
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
            self.last_message = "Open one course from My Learning, then click Check now."
            self.next_check = time.monotonic() + 3600
            return
        updated = {}
        for course in courses:
            if not isinstance(course, dict):
                continue
            identifier = course.get("id")
            if isinstance(identifier, str) and IDENTIFIER.fullmatch(identifier):
                updated[f"/course-player/{tenant}/{identifier}"] = str(course.get("title") or "Orbit course")[:300]
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
            return
        occupied = {view.course or view.expected for view in self.browsers()}
        room = self.settings.get("tab_limit", 2) - len(occupied.intersection(self.queue))
        for path, title in self.queue.items():
            if room <= 0:
                break
            if path in occupied:
                continue
            view = self.new_browser(title, managed=True)
            view.expected = path
            view.setUrl(QUrl(ORIGIN + path))
            room -= 1

    def open_qa(self):
        if (view := self.current_browser()) and view.course:
            view.command("open()")
        else:
            self.statusBar().showMessage("Select a course tab to open Course QA.", 3500)

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
            layout.setContentsMargins(5, 5, 5, 5)
            controls = QHBoxLayout()
            self.camera_mute = QPushButton("Mute")
            self.camera_mute.setCheckable(True)
            self.camera_mute.setChecked(True)
            self.camera_mute.toggled.connect(self.set_camera_muted)
            controls.addWidget(self.camera_mute)
            popout = QPushButton("Pop out / dock")
            popout.clicked.connect(lambda: self.cat_dock.setFloating(not self.cat_dock.isFloating()))
            controls.addWidget(popout)
            source_button = QPushButton("Source")
            source_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(CAMERA_PLAYERS[self.cat_source][2])))
            controls.addWidget(source_button)
            layout.addLayout(controls)
            self.cat_dock.setWidget(content)
            self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.cat_dock)
            self.splitDockWidget(self.timer_dock, self.cat_dock, Qt.Orientation.Vertical)
            self.cat_dock.visibilityChanged.connect(self.sync_camera)
            self.cat_dock.installEventFilter(self)
        if source != self.cat_source:
            self.stop_camera()
            self.cat_source = source
        self.cat_dock.setWindowTitle(CAMERA_PLAYERS[source][0])
        self.cat_dock.show()
        self.resizeDocks([self.cat_dock], [250], Qt.Orientation.Vertical)
        self.sync_camera()

    def set_camera_muted(self, muted):
        if self.cat_view:
            self.cat_view.page().setAudioMuted(muted)

    def eventFilter(self, watched, event):
        if watched is self.cat_dock and event.type() == QEvent.Type.WindowStateChange:
            QTimer.singleShot(0, self.sync_camera)
        return super().eventFilter(watched, event)

    def stop_camera(self):
        if self.cat_view:
            self.cat_view.stop()
            self.cat_view.hide()
            self.cat_view.deleteLater()
            self.cat_view = None

    def sync_camera(self, *_):
        if (not self.cat_dock or not self.cat_dock.isVisible() or self.cat_dock.isMinimized()
                or not self.isVisible() or self.isMinimized() or self.quitting):
            self.stop_camera()
        elif self.cat_source and not self.cat_view:
            if not self.cat_profile:
                self.cat_profile = QWebEngineProfile(self)
            self.cat_view = QWebEngineView(self.cat_dock.widget())
            self.cat_view.setMinimumSize(200, 200)
            self.cat_view.setPage(QWebEnginePage(self.cat_profile, self.cat_view))
            self.set_camera_muted(self.camera_mute.isChecked())
            self.cat_dock.widget().layout().addWidget(self.cat_view, 1)
            url = QUrl(CAMERA_PLAYERS[self.cat_source][1])
            if url.host() == "www.youtube.com":
                # Give the provider a document origin so Chromium sends the embed referrer.
                self.cat_view.setHtml(
                    '<body style="margin:0;background:#101827"><iframe '
                    'title="Kitten Rescue video player" '
                    'style="display:block;width:100vw;height:100vh;border:0" '
                    'referrerpolicy="strict-origin-when-cross-origin" '
                    f'src="{escape(url.toString(), quote=True)}"></iframe></body>',
                    QUrl("https://" + APP_ID + "/"),
                )
            else:
                self.cat_view.setUrl(url)

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
        if not self.isVisible() or self.isMinimized():
            return
        if self.scan_status.text() != self.last_message:
            self.scan_status.setText(self.last_message)
        rows = []
        paths = set()
        for view in self.browsers():
            path = view.course or view.expected
            if not path:
                continue
            paths.add(path)
            state = "Loading" if not view.course else "Visible" if view is self.current_browser() else "Background"
            if view.activity != "idle":
                state = view.activity.capitalize()
            rows.append((path, self.queue.get(path, view.title() or view.label), state, clock_text(now - view.opened)))
        rows.extend((path, title, "Queued", "—") for path, title in self.queue.items() if path not in paths)
        for index, (path, title, state, elapsed) in enumerate(rows):
            item = self.timeline.topLevelItem(index)
            if not item:
                item = QTreeWidgetItem(self.timeline)
            item.setData(0, Qt.ItemDataRole.UserRole, path)
            item.setToolTip(0, title)
            item.setTextAlignment(2, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            for column, value in enumerate((title, state, elapsed)):
                if item.text(column) != value:
                    item.setText(column, value)
        while self.timeline.topLevelItemCount() > len(rows):
            self.timeline.takeTopLevelItem(self.timeline.topLevelItemCount() - 1)

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
    if "--review-license" in sys.argv:
        try:
            review_license(preview=True)
        except (OSError, UnicodeError) as error:
            QMessageBox.critical(None, "Student License", str(error))
            return 1
        return 0
    directory = data_path()
    directory.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(directory / "embedded.lock"))
    if not lock.tryLock(0):
        QMessageBox.information(None, "Orbit Tabs", "Orbit Tabs is already running.")
        return 0
    settings_path = directory / "embedded-settings.json"
    try:
        if not review_license(settings_path):
            return 0
    except (OSError, UnicodeError) as error:
        QMessageBox.critical(None, "Student License", str(error))
        return 1
    window = OrbitWindow(settings_path)
    if not window.tray or "--startup" not in sys.argv:
        window.show()
    exit_code = app.exec()
    window.dispose()
    lock.unlock()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
