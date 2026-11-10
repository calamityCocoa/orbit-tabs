"""Exercise the embedded quiz UI against a local HTTP fixture."""
import json
import os
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

try:
    from PySide6.QtCore import Qt, Slot
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    import orbit_embedded as orbit
except ImportError:
    orbit = None


class QuizFixture(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        if self.path == "/my-learning":
            body = """<main><section id="not-started">
            <article data-slot="card"><h3 data-slot="card-title">Quiz A</h3>
            <a href="/course-player/mock/alpha">Open</a></article>
            <article data-slot="card"><h3 data-slot="card-title">Quiz B</h3>
            <a href="/course-player/mock/beta">Open</a></article>
            </section></main>"""
        elif self.path.startswith("/course-player/"):
            course = self.path.rsplit("/", 1)[-1]
            body = f'<title>{course}</title><iframe src="/quiz/{course}" width="480" height="200"></iframe>'
        elif self.path in ("/quiz/alpha", "/quiz/beta"):
            course = self.path.rsplit("/", 1)[-1]
            unlock_ms = 600 if course == "alpha" else 3100
            body = f"""<form style="background:#cf7642">
            <fieldset><legend>What is 2 + 2?</legend>
            <label><input id="four" type="radio" name="answer" value="4">Four</label>
            <label><input id="five" type="radio" name="answer" value="5">Five</label>
            </fieldset><button id="submit" disabled>Submit</button><output id="result"></output></form>
            <script>
            const form = document.querySelector('form');
            const submit = document.querySelector('#submit');
            let started = 0;
            form.addEventListener('change', () => {{
              started = performance.now();
              setTimeout(() => {{ submit.disabled = false; }}, {unlock_ms});
            }});
            form.addEventListener('submit', async (event) => {{
              event.preventDefault();
              const data = new URLSearchParams(new FormData(form));
              data.set('course', '{course}');
              data.set('elapsed', String(Math.round(performance.now() - started)));
              const response = await fetch('/quiz-submit', {{method: 'POST', body: data}});
              document.querySelector('#result').value = await response.text();
            }});
            </script>"""
        else:
            body = ""
        self.reply(200, '<!doctype html><meta charset="utf-8">' + body, "text/html")

    def do_POST(self):
        if self.path != "/quiz-submit":
            self.reply(404, "", "text/plain")
            return
        data = parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode())
        self.server.submissions.append(data)
        self.reply(200, "PASSED" if data.get("answer") == ["4"] else "FAILED", "text/plain")

    def reply(self, status, text, content_type):
        content = text.encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        try:
            self.wfile.write(content)
        except (BrokenPipeError, ConnectionResetError):
            pass


@unittest.skipUnless(orbit and (os.name == "nt" or os.environ.get("DISPLAY") or
                              os.environ.get("WAYLAND_DISPLAY") or os.sys.platform == "darwin"),
                     "Requires Qt WebEngine and a graphical session")
class EmbeddedQuizTest(unittest.TestCase):
    def until(self, condition, timeout=12):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.app.processEvents()
            if value := condition():
                return value
            QTest.qWait(30)
        self.fail("Timed out waiting for quiz state")

    def js(self, view, script):
        output = []
        view.page().runJavaScript(script, orbit.WORLD, output.append)
        self.until(lambda: bool(output))
        return output[0]

    def start_plan(self, view):
        target = view.focusProxy() or view
        view.setFocus()
        QTest.qWait(150)
        self.js(view, "document.querySelector('[data-qa=run]').focus()")
        QTest.keyClick(target, Qt.Key.Key_Space)
        try:
            self.until(lambda: view.activity == "waiting", timeout=5)
        except AssertionError:
            status = self.js(view, """JSON.stringify({
              text: document.querySelector('#orbit-qa-panel pre').textContent,
              click: document.querySelector('[data-qa=run]').dataset.fixtureClick,
              focused: document.activeElement?.outerHTML,
            })""")
            self.fail(f"Run did not reach wait state: {status}")

    def test_answer_then_delayed_submit(self):
        class ConfirmedPage(orbit.QWebEnginePage):
            def javaScriptConfirm(self, _origin, prompt):
                return prompt.startswith("Run this plan?")

        class DemoBridge(orbit.PageBridge):
            @Slot(int, str, str, str)
            def request(self, serial, method, address, data):
                if os.environ.get("ORBIT_TEST_HOSTED") == "1":
                    super().request(serial, method, address, data)
                else:
                    self.answer.emit(serial, 200, '{"choices":[{"message":{"content":"[1]"}}]}')

        self.app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as temp, ThreadingHTTPServer(("127.0.0.1", 0), QuizFixture) as server:
            server.submissions = []
            threading.Thread(target=server.serve_forever, daemon=True).start()
            saved = orbit.ORIGIN, orbit.QWebEnginePage, orbit.PageBridge
            orbit.ORIGIN = f"http://127.0.0.1:{server.server_port}"
            orbit.QWebEnginePage = ConfirmedPage
            orbit.PageBridge = DemoBridge
            settings_path = Path(temp) / "settings.json"
            settings_path.write_text('{"hosted_ai": true}')
            window = orbit.OrbitWindow(settings_path)
            window.show()
            try:
                views = self.until(lambda: {view.course.rsplit("/", 1)[-1]: view
                                           for view in window.browsers() if view.ready and view.course}
                                   if sum(bool(view.ready and view.course) for view in window.browsers()) == 2 else None)
                self.assertIs(window.tabs.currentWidget(), window.wall)
                self.assertEqual(window.wall.timer.interval(), 1000)
                self.assertEqual(window.wall.columns, 3)
                window.resize(900, 670)
                self.until(lambda: window.wall.columns == 2)
                appearance = next(action for menu in window.menuBar().actions() if menu.menu()
                                  for action in menu.menu().actions() if action.text() == "Dark appearance")
                appearance.setChecked(False)
                self.assertIn("#eef2f8", window.styleSheet())
                self.assertFalse(json.loads(window.settings_path.read_text())["dark_theme"])
                appearance.setChecked(True)
                window.resize(1200, 780)
                self.until(lambda: window.wall.columns == 3)
                first = views["alpha"]
                tile = self.until(lambda: next((tile for tile in window.wall.tiles if tile.view is first), None))

                def has_course_pixels(colored):
                    pixmap = tile.preview.pixmap()
                    if pixmap.isNull():
                        return False
                    image = pixmap.toImage()
                    samples = [image.pixelColor(x, y) for x in range(0, image.width(), 12)
                               for y in range(0, image.height(), 12)]
                    if colored:
                        return any(pixel.red() > pixel.blue() + 50 for pixel in samples)
                    return any(110 < pixel.red() < 195 and pixel.red() == pixel.green() == pixel.blue()
                               for pixel in samples)

                self.until(lambda: has_course_pixels(False))
                first.activity = "answering"
                self.until(lambda: has_course_pixels(True))
                self.assertIn("ANSWERING", tile.badge.text())
                if screenshot := os.environ.get("ORBIT_TEST_WALL_SCREENSHOT"):
                    window.grab().save(screenshot)
                first.activity = "idle"
                for course, delay, minimum in (("alpha", 3, 2900), ("beta", 1, 3000)):
                    view = views[course]
                    window.tabs.setCurrentWidget(view)
                    if course == "alpha":
                        view.command("suggest()")
                        self.until(lambda: "Suggested: Four" in self.js(view, """
                            document.querySelector('#orbit-qa-panel pre')?.textContent
                        """), timeout=100)
                        answers = json.loads(self.js(view, "document.querySelector('#orbit-qa-panel textarea').value"))
                    else:
                        window.settings["hosted_ai"] = False
                        window.update_ai_setting()
                        self.assertFalse(window.suggest_action.isEnabled())
                        view.command("open()")
                        self.until(lambda: self.js(view, "document.querySelector('[data-qa=suggest]')?.hidden"))
                        self.js(view, "document.querySelector('#orbit-qa-panel textarea').value = " +
                                json.dumps(json.dumps({**answers, "path": view.course})))
                    self.js(view, f"""(() => {{
                      const panel = document.querySelector('#orbit-qa-panel');
                      panel.querySelector('[data-qa=submit]').click();
                      panel.querySelector('input[type=number]').value = {delay};
                      panel.querySelector('[data-qa=delay]').click();
                      const button = panel.querySelector('[data-qa=run]');
                      button.addEventListener('click', (event) => {{
                        button.dataset.fixtureClick = String(event.isTrusted);
                      }});
                      button.focus();
                    }})()""")
                    plan = json.loads(self.js(view, "document.querySelector('#orbit-qa-panel textarea').value"))
                    self.assertEqual(plan["steps"][-1]["delaySeconds"], delay)
                    self.start_plan(view)
                    self.assertFalse(any(item["course"] == [course] for item in server.submissions))
                    window.show_wall()
                    submission = self.until(lambda: next((item for item in server.submissions
                                                         if item["course"] == [course]), None))
                    self.assertEqual(submission["answer"], ["4"])
                    self.assertGreaterEqual(int(submission["elapsed"][0]), minimum)
                    self.until(lambda: view.activity == "idle")
                self.assertEqual(len(server.submissions), 2)

                window.tabs.setCurrentWidget(first)
                first.ready = False
                first.reload()
                self.until(lambda: first.ready)
                first.command("open()")
                stopped_plan = {**answers, "steps": [*answers["steps"], {
                    "action": "click", "selector": "#submit", "frames": [0],
                    "submit": True, "delaySeconds": 2, "waitSeconds": 5,
                }]}
                invalid_plan = {**stopped_plan, "steps": [
                    stopped_plan["steps"][-1], *stopped_plan["steps"],
                ]}
                self.js(first, "document.querySelector('#orbit-qa-panel textarea').value = " +
                        json.dumps(json.dumps(invalid_plan)))
                self.js(first, "document.querySelector('[data-qa=preview]').click()")
                self.assertIn("Submit must be the last step", self.js(
                    first, "document.querySelector('#orbit-qa-panel pre').textContent"))
                self.js(first, "document.querySelector('#orbit-qa-panel textarea').value = " +
                        json.dumps(json.dumps(stopped_plan)))
                self.start_plan(first)
                self.js(first, "document.querySelector('[data-qa=stop]').click()")
                self.until(lambda: first.activity == "idle")
                self.assertIn("Stopped.", self.js(first, "document.querySelector('#orbit-qa-panel pre').textContent"))
                QTest.qWait(2200)
                self.assertEqual(len(server.submissions), 2)
                window.show_wall()
                orbit.CAMERA_PLAYERS["fixture"] = ("Demo camera", "about:blank", "about:blank")
                window.show_camera("fixture")
                self.assertIs(window.tabs.currentWidget(), window.wall)
                self.assertIsNotNone(window.cat_view)
                self.assertTrue(window.cat_view.page().isAudioMuted())
                window.cat_dock.close()
                self.until(lambda: window.cat_view is None)
                window.show_camera("fixture")
                self.assertIsNotNone(window.cat_view)
                window.hide()
                self.assertIsNone(window.cat_view)
                self.assertFalse(window.wall.timer.isActive())
            finally:
                window.quit()
                window.dispose()
                orbit.ORIGIN, orbit.QWebEnginePage, orbit.PageBridge = saved
                orbit.CAMERA_PLAYERS.pop("fixture", None)
                server.shutdown()


if __name__ == "__main__":
    unittest.main()
