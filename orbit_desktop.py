"""Orbit tab manager. Run with Python 3.10 or later."""
from __future__ import annotations

import json
import os
import queue
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import webbrowser
from dataclasses import dataclass
from hmac import compare_digest
from importlib.util import find_spec
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tkinter import messagebox, ttk
from urllib.parse import urlsplit

from orbit_common import (
    CAMERAS, IDENTIFIER, ORIGIN, PLAYER, SCRIPT, WEEK, clock_text, data_path, login_entry, read_config, save_config,
)

PORT = 18187
HEARTBEAT_EXPIRY = 180

def launch_browser(url: str) -> None:
    if sys.platform == "win32":
        locations = [Path(os.environ.get(var, "")) / folder / "firefox.exe"
                     for folder in ("Firefox Nightly", "Mozilla Firefox")
                     for var in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA")]
        executable = next((str(path) for path in locations if path.is_absolute() and path.is_file()), None)
    elif sys.platform == "darwin":
        candidates = [Path("/Applications") / name for name in ("Firefox Nightly.app", "Firefox.app")]
        application = next((path for path in candidates if path.is_dir()), None)
        if application:
            subprocess.Popen(["open", "-a", str(application), url])
            return
        executable = None
    else:
        executable = shutil.which("firefox-nightly") or shutil.which("firefox")
    if executable:
        subprocess.Popen([executable, "-new-tab", url])
    else:
        webbrowser.open_new_tab(url)


@dataclass
class Tab:
    path: str
    title: str
    opened: float
    last_seen: float
    visible: bool


class Hub:
    """Coordinates browser tabs without storing cookies or quiz contents."""

    def __init__(self, config: dict):
        self.lock = threading.RLock()
        self.config = config
        token = config.get("token")
        self.token = token if isinstance(token, str) and re.fullmatch(r"[a-f0-9]{64}", token) else secrets.token_hex(32)
        config["token"] = self.token
        self.tabs: dict[str, Tab] = {}
        self.courses: dict[str, str] = {}
        self.managed: set[str] = set()
        self.issued: dict[str, float] = {}
        self.suggestions: dict[str, float] = {}
        self.tenant = config.get("tenant", "")
        self.dashboard_id = ""
        self.dashboard_seen = 0.0
        self.scan_id = ""
        self.scan_requested = 0.0
        self.last_check = float(config.get("last_check", 0))
        self.unresolved = 0
        self.catalog_valid = False
        self.status = "Connect Firefox to get started."
        self.settings_dirty = False

    def request_scan(self) -> None:
        with self.lock:
            self.scan_id = secrets.token_hex(12)
            self.scan_requested = time.time()
            self.status = "Checking My Learning in Firefox…"

    def report(self, payload: dict, now: float) -> dict:
        role, tab_id = payload.get("role"), payload.get("tab")
        if not isinstance(tab_id, str) or not IDENTIFIER.fullmatch(tab_id):
            raise ValueError("Invalid tab ID")
        with self.lock:
            if role == "pair":
                return {"paired": True}
            if role == "player":
                return self.report_player(tab_id, payload, now)
            if role == "dashboard":
                return self.report_dashboard(tab_id, payload, now)
            raise ValueError("Invalid browser page role")

    def report_player(self, tab_id: str, payload: dict, now: float) -> dict:
        path = payload.get("path")
        match = PLAYER.fullmatch(path) if isinstance(path, str) else None
        if not match:
            raise ValueError("Invalid course path")
        title = self.courses.get(path) or str(payload.get("title") or "Orbit course")[:300]
        previous = self.tabs.get(tab_id)
        observed = payload.get("opened")
        started = float(observed) / 1000 if isinstance(observed, (float, int)) and 0 < observed < now * 1000 else now
        opened = previous.opened if previous and previous.path == path else started
        self.tabs[tab_id] = Tab(path, title, opened, now, bool(payload.get("visible")))
        if not self.tenant:
            self.tenant = match[1]
            self.config["tenant"] = self.tenant
            self.settings_dirty = True
        if path in self.issued:
            self.managed.add(path)
            self.issued.pop(path)
        expiry = self.suggestions.pop(tab_id, 0)
        return {"suggest": expiry >= now}

    def report_dashboard(self, tab_id: str, payload: dict, now: float) -> dict:
        if self.dashboard_id and self.dashboard_id != tab_id and now - self.dashboard_seen < 75:
            return {}
        self.dashboard_id = tab_id
        self.dashboard_seen = now
        if not self.config.get("paired"):
            self.config["paired"] = True
            self.settings_dirty = True
        owned = payload.get("owned", [])
        if isinstance(owned, list):
            self.managed.update(path for path in owned[:300] if isinstance(path, str) and PLAYER.fullmatch(path))
        for path in list(self.issued):
            if now - self.issued[path] > HEARTBEAT_EXPIRY:
                # A suspended or slow tab can still be open. Leave it alone.
                self.managed.add(path)
                self.issued.pop(path)
        closed = payload.get("closed", [])
        if isinstance(closed, list):
            for path in closed[:300]:
                if not isinstance(path, str) or not PLAYER.fullmatch(path):
                    continue
                self.managed.discard(path)
                self.issued.pop(path, None)
                self.tabs = {key: tab for key, tab in self.tabs.items() if tab.path != path}
        scan = payload.get("scan")
        if isinstance(scan, dict) and self.scan_id and scan.get("id") == self.scan_id:
            self.accept_scan(scan, now)
        if self.scan_id and now - self.scan_requested > 300:
            self.scan_id = ""
            self.status = "My Learning did not finish loading. Check your Firefox session."
        active = {tab.path for tab in self.tabs.values()}
        opens = []
        if not self.scan_id and self.tenant and self.catalog_valid:
            limit = int(self.config.get("tab_limit", 4))
            room = max(0, limit - len(self.managed | set(self.issued) | (active & self.courses.keys())))
            if self.config.get("auto_open", True):
                for path, title in self.courses.items():
                    if room <= 0 or len(opens) >= 2:
                        break
                    if path in active or path in self.managed or path in self.issued:
                        continue
                    self.issued[path] = now
                    opens.append({"path": path, "title": title})
                    room -= 1
        closes = (list(self.managed - self.courses.keys())
                  if self.catalog_valid and not self.scan_id and self.config.get("auto_close", True) else [])
        return {"scan": self.scan_id, "open": opens, "close": closes}

    def accept_scan(self, scan: dict, now: float) -> None:
        self.scan_id = ""
        if scan.get("error"):
            self.status = str(scan["error"])[:300]
            return
        courses = scan.get("courses")
        if not isinstance(courses, list) or len(courses) > 300:
            self.status = "My Learning returned an incomplete list or more than 300 courses."
            return
        tenant = scan.get("tenant")
        if isinstance(tenant, str) and IDENTIFIER.fullmatch(tenant):
            self.tenant = tenant
            self.config["tenant"] = tenant
        result = {}
        for course in courses[:300]:
            if not isinstance(course, dict):
                continue
            course_id = course.get("id")
            if isinstance(course_id, str) and IDENTIFIER.fullmatch(course_id) and self.tenant:
                path = f"/course-player/{self.tenant}/{course_id}"
                result[path] = str(course.get("title") or "Orbit course")[:300]
        unresolved = scan.get("unresolved", 0)
        self.unresolved = max(0, unresolved) if isinstance(unresolved, int) else 0
        if courses and not self.tenant:
            self.status = "Open one course in Firefox to link your Orbit workspace, then check again."
            return
        if self.unresolved:
            result.update({path: title for path, title in self.courses.items() if path not in result})
        self.courses = result
        self.catalog_valid = True
        self.last_check = now
        self.config["last_check"] = now
        self.settings_dirty = True
        self.status = (f"{len(result)} unfinished course(s)."
                       if result else "No unfinished courses. Weekly checking is active.")
        if self.unresolved:
            self.status += f" {self.unresolved} card(s) need a manual open."


def handler_for(hub: Hub):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(8)

        def log_message(self, *args):
            pass

        def send(self, status, body, content_type):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def valid_host(self):
            return self.headers.get("Host") in {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}

        def do_GET(self):
            if not self.valid_host():
                self.send_error(403)
            elif self.path == "/orbit-qa/orbit-course-qa.user.js":
                self.send(200, SCRIPT.read_bytes(), "application/javascript; charset=utf-8")
            elif self.path == "/orbit-qa/pair":
                page = (b"<!doctype html><meta charset=utf-8><title>Connect Orbit Tabs</title>"
                        b"<h1>Connect Orbit Tabs</h1><p id=pair-status>Waiting for the Orbit Course QA "
                        b"userscript. Install or update it in Violentmonkey, then retry from Orbit Tabs.</p>")
                self.send(200, page, "text/html; charset=utf-8")
            else:
                self.send_error(404)

        def do_POST(self):
            supplied = self.headers.get("Authorization", "").encode()
            expected = ("Bearer " + hub.token).encode()
            if (not self.valid_host() or self.path != "/bridge" or not compare_digest(supplied, expected)
                    or self.headers.get_content_type() != "application/json"):
                self.send_error(403)
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 128000:
                    raise ValueError("Invalid payload size")
                payload = json.loads(self.rfile.read(size))
                if not isinstance(payload, dict):
                    raise ValueError("Expected an object")
                reply = hub.report(payload, time.time())
            except (ValueError, RecursionError, TimeoutError):
                self.send_error(400)
                return
            self.send(200, json.dumps(reply).encode(), "application/json; charset=utf-8")

    return Handler


class Desktop:
    def __init__(self, root: tk.Tk, hub: Hub, config_path: Path):
        self.root, self.hub, self.config_path = root, hub, config_path
        self.events = queue.SimpleQueue()
        self.tray = None
        self.last_browser_launch = 0.0
        self.next_weekly_retry = 0.0
        self.handled_check = hub.last_check
        self.rendered = {}
        self.quitting = False
        self.camera = None
        self.camera_choice = tk.StringVar(value="")
        self.camera_source = ""
        self.camera_stopping = False
        self.status = tk.StringVar()
        self.cat = tk.BooleanVar(value=hub.config.get("cat", False))
        self.auto_open = tk.BooleanVar(value=hub.config.get("auto_open", True))
        self.auto_close = tk.BooleanVar(value=hub.config.get("auto_close", True))
        self.auto_hide = tk.BooleanVar(value=hub.config.get("auto_hide", True))
        self.autostart = tk.BooleanVar(value=hub.config.get("autostart", False))
        self.limit = tk.IntVar(value=hub.config.get("tab_limit", 4))
        self.build()
        self.start_tray()

    def build(self):
        root = self.root
        root.title("Orbit Tabs")
        root.geometry("830x440")
        root.minsize(660, 350)
        root.protocol("WM_DELETE_WINDOW", self.hide)
        menu = tk.Menu(root)
        orbit = tk.Menu(menu, tearoff=False)
        orbit.add_command(label="Check now", command=self.check)
        orbit.add_command(label="Install or update userscript", command=self.install)
        orbit.add_command(label="Connect Firefox", command=self.pair)
        orbit.add_separator()
        orbit.add_command(label="Quit", command=self.quit)
        menu.add_cascade(label="Orbit", menu=orbit)
        settings = tk.Menu(menu, tearoff=False)
        settings.add_checkbutton(label="Open queued courses automatically", variable=self.auto_open,
                                 command=self.save_settings)
        settings.add_checkbutton(label="Close managed tabs after completion", variable=self.auto_close,
                                 command=self.save_settings)
        settings.add_checkbutton(label="Hide to tray when queue is empty", variable=self.auto_hide,
                                 command=self.save_settings)
        settings.add_checkbutton(label="Start at sign-in", variable=self.autostart, command=self.set_autostart)
        menu.add_cascade(label="Settings", menu=settings)
        cats = tk.Menu(menu, tearoff=False)
        cats.add_checkbutton(label="Add a cat", variable=self.cat, command=self.save_settings)
        cats.add_separator()
        for key, (name, _) in CAMERAS.items():
            cats.add_radiobutton(label=name, value=key, variable=self.camera_choice, command=self.select_camera)
        cats.add_radiobutton(label="Turn camera off", value="", variable=self.camera_choice,
                             command=self.select_camera)
        menu.add_cascade(label="Cats", menu=cats)
        for event in ("<Map>", "<Unmap>"):
            root.bind(event, self.camera_visibility, add=True)
        root.configure(menu=menu)

        frame = ttk.Frame(root, padding=16)
        frame.pack(fill="both", expand=True)
        header = ttk.Frame(frame)
        header.pack(fill="x", pady=(0, 10))
        ttk.Label(header, text="Orbit Tabs", font=("TkDefaultFont", 16, "bold")).pack(side="left")
        self.mascot = ttk.Label(header, text="   /\\_/\\    Cat on duty\n  ( o.o )\n   > ^ <", font="TkFixedFont")
        ttk.Button(header, text="Check now", command=self.check).pack(side="right")
        ttk.Label(frame, textvariable=self.status, wraplength=720).pack(anchor="w", pady=(0, 10))

        table = ttk.Frame(frame)
        table.pack(fill="both", expand=True)
        columns = ("state", "elapsed")
        self.tree = ttk.Treeview(table, columns=columns, selectmode="browse")
        self.tree.heading("#0", text="Course")
        self.tree.heading("state", text="Tab state")
        self.tree.heading("elapsed", text="Observed open time")
        self.tree.column("#0", width=390, minwidth=190)
        self.tree.column("state", width=130, minwidth=105, stretch=False)
        self.tree.column("elapsed", width=150, minwidth=125, stretch=False, anchor="center")
        scrollbar = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        footer = ttk.Frame(frame)
        footer.pack(fill="x", pady=(12, 0))
        ttk.Button(footer, text="AI suggestions", command=self.suggest).pack(side="left")
        ttk.Button(footer, text="Connect Firefox", command=self.pair).pack(side="left", padx=8)
        ttk.Label(footer, text="Managed tab limit").pack(side="right", padx=6)
        limit = ttk.Spinbox(footer, from_=1, to=300, width=4, textvariable=self.limit, command=self.save_settings)
        limit.pack(side="right")
        limit.bind("<FocusOut>", lambda event: self.save_settings())
        limit.bind("<Return>", lambda event: self.save_settings())

    def start_tray(self):
        try:
            if sys.platform.startswith("linux"):
                # Avoid the Xorg backend's menu-less icon on desktops with no tray.
                os.environ.setdefault("PYSTRAY_BACKEND", "appindicator")
                try:
                    import gi
                    gi.require_version("Gtk", "3.0")
                    from gi.repository import Gio, GLib, Gtk
                    bus = Gio.bus_get_sync(Gio.BusType.SESSION)
                    owner = bus.call_sync(
                        "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                        "NameHasOwner", GLib.Variant("(s)", ("org.kde.StatusNotifierWatcher",)), None,
                        Gio.DBusCallFlags.NONE, 1000, None,
                    )
                    if not owner.unpack()[0] or not Gtk.init_check()[0]:
                        return
                except (ImportError, ValueError):
                    return
            import pystray
            from PIL import Image, ImageDraw

            image = Image.new("RGBA", (64, 64), "#21304e")
            draw = ImageDraw.Draw(image)
            draw.ellipse((13, 13, 51, 51), outline="#e7f1ff", width=4)
            draw.ellipse((28, 28, 36, 36), fill="#83c8ff")
            draw.ellipse((45, 13, 53, 21), fill="#83c8ff")
            self.tray = pystray.Icon("orbit-tabs", image, "Orbit Tabs", menu=pystray.Menu(
                pystray.MenuItem("Show Orbit Tabs", lambda *_: self.events.put(self.show), default=True),
                pystray.MenuItem("Check now", lambda *_: self.events.put(self.check)),
                pystray.MenuItem("Add or remove cat", lambda *_: self.events.put(self.toggle_cat)),
                pystray.MenuItem("Quit", lambda *_: self.events.put(self.quit)),
            ))
            if sys.platform == "darwin":
                self.tray.run_detached(setup=self.tray_ready)
            else:
                threading.Thread(target=self.tray.run, kwargs={"setup": self.tray_ready}, daemon=True).start()
        except Exception:
            self.tray = None

    def tray_ready(self, icon):
        try:
            icon.visible = True
            self.events.put(self.hide)
        except Exception:
            self.events.put(self.show)

    def hide(self):
        self.stop_camera()
        if self.tray and self.tray.visible:
            self.root.withdraw()
        else:
            self.root.iconify()

    def show(self):
        self.root.deiconify()
        self.root.lift()

    def quit(self):
        self.quitting = True
        self.stop_camera()
        if self.tray:
            self.tray.stop()
        self.root.destroy()

    def camera_visibility(self, event):
        if event.widget is self.root and not self.quitting:
            self.root.after_idle(self.sync_camera)

    def select_camera(self):
        if self.camera_choice.get() and not gtk_camera_available() and find_spec("webview") is None:
            package = "pywebview[qt]" if sys.platform.startswith("linux") else "pywebview"
            messagebox.showinfo("Cat cameras", f"Install the optional camera viewer with:\n\n"
                                f'{Path(sys.executable).name} -m pip install "{package}"')
            self.camera_choice.set("")
        self.sync_camera()

    def stop_camera(self):
        if self.camera and self.camera.poll() is None and not self.camera_stopping:
            self.camera_stopping = True
            try:
                self.camera.terminate()
            except ProcessLookupError:
                pass

    def sync_camera(self):
        if self.quitting:
            return
        choice = self.camera_choice.get()
        if self.camera and self.camera.poll() is not None:
            if self.camera.stdin:
                self.camera.stdin.close()
            if not self.camera_stopping:
                if self.camera.returncode:
                    self.hub.status = "The camera viewer could not start. Check your system webview installation."
                self.camera_choice.set("")
                choice = ""
            self.camera = None
            self.camera_stopping = False
        visible = self.window_visible()
        if not visible or not choice or (self.camera and choice != self.camera_source):
            self.stop_camera()
            return
        if not self.camera:
            try:
                self.camera = subprocess.Popen(
                    [sys.executable, str(Path(__file__).resolve()), "--cat-camera", choice],
                    stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                self.camera_source = choice
            except OSError as error:
                self.camera_choice.set("")
                self.hub.status = f"Could not start the camera viewer: {error}"

    def window_visible(self):
        return self.root.state() in {"normal", "zoomed"} and self.root.winfo_viewable()

    def toggle_cat(self):
        self.cat.set(not self.cat.get())
        self.save_settings()

    def save_settings(self):
        try:
            limit = min(300, max(1, self.limit.get()))
        except tk.TclError:
            limit = self.hub.config.get("tab_limit", 4)
        self.limit.set(limit)
        with self.hub.lock:
            self.hub.config.update(cat=self.cat.get(), auto_open=self.auto_open.get(),
                                   auto_close=self.auto_close.get(), auto_hide=self.auto_hide.get(), tab_limit=limit,
                                   autostart=self.autostart.get())
            self.hub.settings_dirty = True

    def set_autostart(self):
        try:
            login_entry(self.autostart.get(), Path(__file__))
        except OSError as error:
            self.autostart.set(not self.autostart.get())
            messagebox.showerror("Start at sign-in", str(error))
            return
        self.save_settings()

    def open_browser(self, url):
        try:
            launch_browser(url)
        except OSError as error:
            with self.hub.lock:
                self.hub.status = f"Could not open Firefox: {error}"

    def install(self):
        self.open_browser(f"http://localhost:{PORT}/orbit-qa/orbit-course-qa.user.js")

    def pair(self):
        self.open_browser(f"http://localhost:{PORT}/orbit-qa/pair#{self.hub.token}")
        self.check(open_dashboard=False)

    def check(self, open_dashboard=True):
        now = time.time()
        self.hub.request_scan()
        if (open_dashboard and now - self.hub.dashboard_seen > 75
                and now - self.last_browser_launch > 45):
            self.last_browser_launch = now
            self.open_browser(ORIGIN + "/my-learning")
        self.next_weekly_retry = now + (600 if self.hub.courses else 3600)

    def suggest(self):
        selection = self.tree.selection()
        if not selection or not selection[0].startswith("tab:"):
            messagebox.showinfo("AI suggestions", "Select an open course tab first.")
            return
        if not messagebox.askyesno("AI suggestions", "Send visible quiz questions to Pollinations AI? "
                                   "Questions it is unsure about may be searched on Wikipedia."):
            return
        with self.hub.lock:
            self.hub.suggestions[selection[0][4:]] = time.time() + HEARTBEAT_EXPIRY
            self.hub.status = "AI suggestions requested. Open the course tab to review them."

    def tick(self):
        while not self.events.empty():
            action = self.events.get()
            action()
            if self.quitting:
                return
        now = time.time()
        visible = self.window_visible()
        with self.hub.lock:
            if self.hub.settings_dirty:
                try:
                    save_config(self.config_path, self.hub.config)
                    self.hub.settings_dirty = False
                except OSError as error:
                    self.hub.status = f"Could not save settings: {error}"
            if self.hub.scan_id and now - self.hub.scan_requested > 300:
                self.hub.scan_id = ""
                self.hub.status = "Check timed out. Install or pair the userscript and sign in to Orbit."
            rows = {}
            if visible:
                for key, tab in self.hub.tabs.items():
                    recent = now - tab.last_seen <= HEARTBEAT_EXPIRY
                    state = ("Visible" if tab.visible else "Background") if recent else "Unconfirmed"
                    rows["tab:" + key] = (tab.title, state, clock_text(min(now, tab.last_seen + 35) - tab.opened))
                active = {tab.path for tab in self.hub.tabs.values()}
                for path, title in self.hub.courses.items():
                    if path in active:
                        continue
                    state = "Opening…" if path in self.hub.issued else "Queued"
                    if path in self.hub.managed:
                        state = "Unconfirmed"
                    rows[path] = (title, state, "—")
            self.status.set(self.hub.status)
            checked = self.hub.last_check
            hide_empty = (checked != self.handled_check and not self.hub.courses and not self.hub.unresolved
                          and self.auto_hide.get() and self.tray and self.tray.visible)
            self.handled_check = checked
            interval = 600 if self.hub.courses else WEEK
            due = (self.hub.config.get("paired") and not self.hub.scan_id and now >= self.next_weekly_retry
                   and now - self.hub.last_check >= interval)
        if due:
            self.check()
        if hide_empty:
            self.hide()
            visible = False
        self.sync_camera()
        if visible:
            self.render(rows)
        self.root.after(1000 if visible else 5000, self.tick)

    def render(self, rows):
        if self.cat.get() and not self.mascot.winfo_manager():
            self.mascot.pack(side="left", padx=10)
        elif not self.cat.get() and self.mascot.winfo_manager():
            self.mascot.pack_forget()
        for key in self.rendered.keys() - rows.keys():
            self.tree.delete(key)
        for key, values in rows.items():
            if key not in self.rendered:
                self.tree.insert("", "end", iid=key, text=values[0], values=values[1:])
            elif values != self.rendered[key]:
                self.tree.item(key, text=values[0], values=values[1:])
        self.rendered = rows


def gtk_camera_available():
    if not sys.platform.startswith("linux"):
        return False
    try:
        import gi

        gi.require_version("Gtk", "3.0")
        gi.require_version("Gdk", "3.0")
        gi.require_version("WebKit2", "4.1")
    except (ImportError, ValueError):
        return False
    return True


def watch_camera_parent(close):
    if sys.stdin is not None:
        sys.stdin.buffer.read()
        close()


def cat_camera(choice: str):
    name, url = CAMERAS[choice]
    title = f"Orbit Tabs · {name}"
    if gtk_camera_available():
        from gi.repository import Gdk, GLib, Gtk, WebKit2

        window = Gtk.Window(title=title, default_width=760, default_height=540)
        view = WebKit2.WebView.new_with_context(WebKit2.WebContext.new_ephemeral())
        window.add(view)
        window.connect("destroy", Gtk.main_quit)

        def close_on_minimize(_, event):
            if event.new_window_state & Gdk.WindowState.ICONIFIED:
                window.destroy()
            return False

        window.connect("window-state-event", close_on_minimize)
        window.show_all()
        view.load_uri(url)
        threading.Thread(target=watch_camera_parent, args=(lambda: GLib.idle_add(window.destroy),),
                         daemon=True).start()
        Gtk.main()
        return

    import webview

    webview.settings["ALLOW_FILE_URLS"] = False
    window = webview.create_window(title, url, width=760, height=540)
    window.events.minimized += window.destroy
    webview.start(watch_camera_parent, (window.destroy,), private_mode=True)


def main():
    root = tk.Tk()
    config_path = data_path() / "settings.json"
    config = read_config(config_path)
    hub = Hub(config)
    try:
        server = ThreadingHTTPServer(("127.0.0.1", PORT), handler_for(hub))
        save_config(config_path, config)
    except OSError as error:
        messagebox.showerror("Orbit Tabs", f"Could not start Orbit Tabs. It may already be open.\n\n{error}")
        root.destroy()
        return
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        desktop = Desktop(root, hub, config_path)
        if config.get("paired") or "--startup" in sys.argv:
            desktop.check()
        else:
            desktop.next_weekly_retry = time.time() + 3600
        root.after(200, desktop.tick)
        root.mainloop()
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--cat-camera" and sys.argv[2] in CAMERAS:
        cat_camera(sys.argv[2])
    else:
        main()
