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
            <button onclick="setTimeout(() => window.open('/course-player/mock/beta'), 300)">Continue learning</button></article>
            </section></main>"""
        elif self.path.startswith("/course-player/"):
            course = self.path.rsplit("/", 1)[-1]
            body = f'<title>{course}</title><iframe src="/quiz/{course}" width="480" height="200"></iframe>'
        elif self.path in ("/quiz/alpha", "/quiz/beta"):
            course = self.path.rsplit("/", 1)[-1]
            unlock_ms = 600 if course == "alpha" else 3100
            extra_fields = """
            <label><input id="include" name="include" type="checkbox" value="yes">Include notes</label>
            <label><input id="exclude" name="exclude" type="checkbox" checked>Skip review</label>
            <label>Short response <input id="short" name="short" type="text"></label>
            <label>Explanation <textarea id="explanation" name="explanation"></textarea></label>
            <label>Difficulty <select id="difficulty" name="difficulty">
            <option value="">Choose</option><option value="basic">Basic</option></select></label>
            """ if course == "alpha" else ""
            second_question = """<fieldset><legend>What is 3 + 3?</legend>
            <label><input id="six" type="radio" name="second" value="6">Six</label>
            <label><input id="seven" type="radio" name="second" value="7">Seven</label>
            </fieldset>""" if course == "beta" else ""
            body = f"""<form style="background:#cf7642">
            <fieldset><legend>What is 2 + 2?</legend>
            <label><input id="four" type="radio" name="answer" value="4">Four</label>
            <label><input id="five" type="radio" name="answer" value="5">Five</label>
            </fieldset>{second_question}{extra_fields}<button id="submit" disabled>Submit</button><output id="result"></output></form>
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

    def click_plan_button(self, view, name):
        target = view.focusProxy() or view
        view.setFocus()
        QTest.qWait(150)
        self.js(view, f"document.querySelector('[data-qa={name}]').focus()")
        QTest.keyClick(target, Qt.Key.Key_Space)

    def start_plan(self, view):
        self.click_plan_button(view, "run")
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
            allow_finish = False
            prompts = []

            def javaScriptConfirm(self, _origin, prompt):
                self.prompts.append(prompt)
                return (prompt.startswith(("Run this plan?", "Send the visible questions")) or
                        self.allow_finish and prompt.startswith("Dangerous permission"))

        class DemoBridge(orbit.PageBridge):
            @Slot(int, str, str, str)
            def request(self, serial, method, address, data):
                if os.environ.get("ORBIT_TEST_HOSTED") == "1":
                    super().request(serial, method, address, data)
                else:
                    questions = json.loads(json.loads(data)["messages"][-1]["content"])
                    response = json.dumps({"choices": [{"message": {"content": json.dumps([1] * len(questions))}}]})
                    orbit.QTimer.singleShot(500, lambda: self.answer.emit(serial, 200, response))

        self.app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as temp, ThreadingHTTPServer(("127.0.0.1", 0), QuizFixture) as server:
            server.submissions = []
            threading.Thread(target=server.serve_forever, daemon=True).start()
            saved = orbit.ORIGIN, orbit.QWebEnginePage, orbit.PageBridge
            orbit.ORIGIN = f"http://127.0.0.1:{server.server_port}"
            orbit.QWebEnginePage = ConfirmedPage
            orbit.PageBridge = DemoBridge
            settings_path = Path(temp) / "settings.json"
            settings_path.write_text('{}')
            window = orbit.OrbitWindow(settings_path)
            window.show()
            try:
                self.assertTrue(window.ai_enabled())
                self.assertTrue(window.suggest_action.isEnabled())
                guide = next(action for menu in window.menuBar().actions() if menu.menu()
                             for action in menu.menu().actions() if action.text() == "Quick Start")
                guide.trigger()
                tour = self.until(lambda: window.guide if window.guide and window.guide.isVisible() else None)
                self.assertEqual(tour.objectName(), "quickStart")
                tour.go(5)
                privacy = " ".join(label.text() for label in tour.pages.currentWidget().findChildren(orbit.QLabel))
                self.assertIn("Pollinations", privacy)
                QTest.keyClick(tour, Qt.Key.Key_Escape)
                self.until(lambda: not tour.isVisible())
                saved_settings = json.loads(settings_path.read_text())
                self.assertTrue(saved_settings["quick_start_seen"])
                self.assertFalse(saved_settings["quick_start"]["completed"])
                views = self.until(lambda: {view.course.rsplit("/", 1)[-1]: view
                                           for view in window.browsers() if view.ready and view.course}
                                   if sum(bool(view.ready and view.course) for view in window.browsers()) == 2 else None)
                self.assertIs(window.tabs.currentWidget(), window.wall)
                self.assertEqual(window.wall.timer.interval(), 1000)
                self.assertFalse(window.mascot_art.pixmap(22, 22).isNull())
                title = window.header_title
                resting_title = title.grab().toImage()
                window.mascot.click()
                self.assertEqual(window.mascot_motion.state().name, "Running")
                self.assertIn("Flight check complete", window.statusBar().currentMessage())
                self.until(lambda: title.orbit_angle and title.orbit_angle > 30)
                self.assertNotEqual(title.grab().toImage(), resting_title)
                self.until(lambda: title.orbit_angle is None)
                self.assertEqual(title.grab().toImage(), resting_title)
                self.assertEqual(window.wall.columns, 2)
                window.resize(1370, 780)
                self.until(lambda: window.wall.columns == 3)
                window.resize(900, 670)
                self.until(lambda: window.wall.columns == 2)
                appearance = next(action for menu in window.menuBar().actions() if menu.menu()
                                  for action in menu.menu().actions() if action.text() == "Dark appearance")
                self.assertFalse(window.theme["dark"])
                appearance.setChecked(True)
                self.assertTrue(window.theme["dark"])
                appearance.setChecked(False)
                self.assertFalse(json.loads(window.settings_path.read_text())["dark_theme"])
                window.set_theme("Catppuccin Mocha")
                self.assertTrue(window.theme["dark"])
                window.set_theme("Catppuccin Latte")
                self.assertFalse(window.theme["dark"])
                self.assertEqual(window.theme["bg"], "#eff1f5")
                window.resize(1200, 780)
                self.until(lambda: window.wall.columns == 2)
                window.sidebar_action.setChecked(False)
                self.assertTrue(window.sidebar_panel.isHidden())
                window.find_open_page()
                self.assertFalse(window.sidebar_panel.isHidden())
                window.sidebar_search.setText("quiz b")
                window.open_first_search_result()
                self.assertIs(window.tabs.currentWidget(), views["beta"])
                window.sidebar_search.clear()
                window.show_wall()
                window.settings["reduce_motion"] = True
                window.apply_theme()
                self.assertIsNone(window.wall.tiles[0].graphicsEffect())
                window.mascot.click()
                self.assertEqual(window.mascot_motion.state().name, "Stopped")
                self.assertIsNone(title.orbit_angle)
                first = views["alpha"]
                tile = self.until(lambda: next((tile for tile in window.wall.tiles if tile.view is first), None))

                self.until(lambda: tile.question.title.text() == "What is 2 + 2?")
                self.assertEqual([item.text().split("   ")[-1] for item in tile.question.choices[:2]], ["Four", "Five"])
                self.assertIs(tile.surface.currentWidget(), tile.question)
                self.until(lambda: not tile.mini.icon().isNull())
                tile.mini.click()
                self.assertIs(window.tabs.currentWidget(), first)
                reveal = next(action for menu in window.menuBar().actions() if menu.menu()
                              for action in menu.menu().actions() if action.text() == "Reveal lesson text")
                self.js(first, """(() => {
                    const doc = document.querySelector('iframe').contentDocument;
                    const controls = doc.createElement('section');
                    controls.innerHTML = '<button>Show all text</button><button>Next slide</button>' +
                        '<p id="reveal-fixture">Text for the current slide</p>';
                    doc.body.append(controls);
                    const [reveal, next] = controls.querySelectorAll('button');
                    reveal.onclick = () => { controls.dataset.revealed = 'yes'; reveal.remove(); };
                    next.onclick = () => { controls.dataset.advanced = 'yes'; };
                    const text = doc.querySelector('#reveal-fixture');
                    text.animate([{ opacity: 0 }, { opacity: 1 }],
                        { id: 'text-reveal', duration: 60000, fill: 'both' });
                })()""")
                reveal.trigger()
                self.until(lambda: "text reveal control" in window.statusBar().currentMessage())
                self.assertEqual(self.js(first, "document.querySelector('iframe').contentDocument.querySelector('section').dataset.revealed"), "yes")
                reveal.trigger()
                self.until(lambda: "Revealed the animated" in window.statusBar().currentMessage())
                reveal.trigger()
                self.until(lambda: "No supported text reveal" in window.statusBar().currentMessage())
                self.assertFalse(self.js(first, "document.querySelector('iframe').contentDocument.querySelector('section').hasAttribute('data-advanced')"))
                self.js(first, "document.querySelector('iframe').contentDocument.querySelector('#five').click()")
                window.show_wall()
                self.until(lambda: tile.question.choices[1].text().startswith("✓"))
                self.js(first, "document.querySelector('iframe').contentDocument.querySelector('#five').checked = false")
                self.until(lambda: not tile.question.choices[1].text().startswith("✓"))
                self.assertRegex(tile.elapsed.text(), r"^\d{2}:\d{2}:\d{2}$")
                self.js(first, "document.querySelector('iframe').contentDocument.querySelector('legend').textContent = 'Next question'")
                self.until(lambda: tile.question.title.text() == "Next question")
                self.assertEqual(tile.question.body_layout.contentsMargins().top(), 0)
                self.js(first, "document.querySelector('iframe').contentDocument.querySelector('legend').textContent = 'What is 2 + 2?'")
                self.until(lambda: tile.question.title.text() == "What is 2 + 2?")
                window.wall.raw_mode.setChecked(True)
                self.until(lambda: any(card.view is first and not card.preview.pixmap().isNull() for card in window.wall.tiles))
                window.wall.raw_mode.setChecked(False)
                tile = self.until(lambda: next((card for card in window.wall.tiles if card.view is first), None))
                first.activity = "answering"
                self.until(lambda: "ANSWERING" in tile.badge.text())
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
                        mixed_steps = [
                            {"action": "check", "selector": "#include", "value": True},
                            {"action": "check", "selector": "#exclude", "value": False},
                            {"action": "fill", "selector": "#short", "value": "Four"},
                            {"action": "fill", "selector": "#explanation", "value": "Two pairs make four."},
                            {"action": "select", "selector": "#difficulty", "value": "basic"},
                        ]
                        mixed_plan = {**answers, "steps": [
                            *({**step, "frames": [0]} for step in mixed_steps), *answers["steps"],
                        ]}
                        self.js(view, "document.querySelector('#orbit-qa-panel textarea').value = " +
                                json.dumps(json.dumps(mixed_plan)))
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
                    if course == "alpha":
                        self.assertEqual(submission["include"], ["yes"])
                        self.assertNotIn("exclude", submission)
                        self.assertEqual(submission["short"], ["Four"])
                        self.assertEqual(submission["explanation"], ["Two pairs make four."])
                        self.assertEqual(submission["difficulty"], ["basic"])
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

                beta = views["beta"]
                window.tabs.setCurrentWidget(beta)
                beta.ready = False
                beta.reload()
                self.until(lambda: beta.ready)
                window.settings["hosted_ai"] = True
                window.update_ai_setting()
                beta.command("open()")
                self.until(lambda: self.js(beta, "document.querySelector('[data-qa=apply]')?.hidden === false"))
                self.click_plan_button(beta, "apply")
                self.until(lambda: "Asking Pollinations" in beta.activity_reason)
                self.assertEqual(self.js(beta, "document.querySelector('iframe').contentDocument.querySelectorAll(':checked').length"), 0)
                window.show_wall()
                self.until(lambda: self.js(beta, "document.querySelector('#orbit-qa-panel pre').textContent.includes('Applied 2 of 2')"))
                self.assertEqual(len(server.submissions), 2)
                self.assertEqual(self.js(beta, "document.querySelector('iframe').contentDocument.querySelectorAll(':checked').length"), 2)
                draft = self.js(beta, "document.querySelector('#orbit-qa-panel textarea').value")
                window.tabs.setCurrentWidget(beta)
                beta.ready = False
                beta.reload()
                self.until(lambda: beta.ready)
                beta.command("open()")
                self.until(lambda: self.js(beta, "Boolean(document.querySelector('iframe')?.contentDocument?.querySelector('#submit'))"))
                self.js(beta, "document.querySelector('#orbit-qa-panel textarea').value = " + json.dumps(draft))
                self.js(beta, """(() => {
                    const panel = document.querySelector('#orbit-qa-panel');
                    panel.querySelector('[data-qa=submit]').click();
                    panel.querySelector('input[type=number]').value = 30;
                    panel.querySelector('[data-qa=delay]').click();
                })()""")
                self.click_plan_button(beta, "finish")
                self.until(lambda: any(prompt.startswith("Dangerous permission") for prompt in ConfirmedPage.prompts))
                self.assertEqual(len(server.submissions), 2)
                skip_delay = next(action for menu in window.menuBar().actions() if menu.menu()
                                  for action in menu.menu().actions() if action.text() == "Skip Orbit Tabs submit delay")
                self.assertFalse(skip_delay.isChecked())
                skip_delay.setChecked(True)
                self.until(lambda: self.js(beta, "globalThis.orbitEmbedded.skipSubmitDelay()"))
                original_draft = self.js(beta, "document.querySelector('#orbit-qa-panel textarea').value")
                self.assertEqual(json.loads(original_draft)["steps"][-1]["delaySeconds"], 30)
                beta.page().allow_finish = True
                self.click_plan_button(beta, "run")
                self.until(lambda: "course to enable Submit" in beta.activity_reason)
                self.assertEqual(len(server.submissions), 2)
                self.until(lambda: len(server.submissions) == 3)
                self.assertEqual(server.submissions[-1]["second"], ["6"])
                self.assertLess(int(server.submissions[-1]["elapsed"][0]), 10000)
                self.until(lambda: beta.activity == "idle")
                self.assertEqual(self.js(beta, "document.querySelector('#orbit-qa-panel textarea').value"), original_draft)

                beta.ready = False
                beta.reload()
                self.until(lambda: beta.ready)
                self.until(lambda: self.js(beta, "Boolean(document.querySelector('iframe')?.contentDocument?.querySelector('form'))"))
                self.js(beta, """(() => {
                    const doc = document.querySelector('iframe').contentDocument;
                    const form = doc.querySelector('form');
                    form.hidden = true;
                    const dialog = doc.createElement('section');
                    dialog.setAttribute('role', 'dialog');
                    dialog.innerHTML = '<button>Start course</button>';
                    doc.body.append(dialog);
                    dialog.firstChild.onclick = () => {
                        dialog.innerHTML = 'Would you like to resume where you left off?<button>Yes</button>';
                        dialog.querySelector('button').onclick = () => { dialog.remove(); form.hidden = false; };
                    };
                })()""")
                window.settings["auto_run_courses"] = True
                for view in window.browsers():
                    view.bridge.autoRunChanged.emit()
                self.until(lambda: len(server.submissions) == 4, timeout=20)
                self.assertEqual(server.submissions[-1]["answer"], ["4"])
                self.assertEqual(server.submissions[-1]["second"], ["6"])
                self.until(lambda: beta.activity == "idle")
                beta.command("autoStep()")
                QTest.qWait(500)
                self.assertEqual(len(server.submissions), 4)
                window.settings["auto_run_courses"] = False
                for view in window.browsers():
                    view.bridge.autoRunChanged.emit()
                window.show_wall()
                orbit.CAMERA_PLAYERS["fixture"] = ("Demo camera", "", "about:blank")
                window.show_camera("fixture")
                self.assertIs(window.tabs.currentWidget(), window.wall)
                self.assertIsNotNone(window.cat_view)
                self.assertIsInstance(window.cat_view, orbit.QVideoWidget)
                self.assertTrue(window.cat_audio.isMuted())
                window.camera_mute.setChecked(False)
                self.assertFalse(window.cat_audio.isMuted())
                window.cat_dock.close()
                self.until(lambda: window.cat_view is None)
                self.assertIsNone(window.cat_player)
                window.show_camera("fixture")
                self.assertIsNotNone(window.cat_view)
                window.hide()
                self.assertIsNone(window.cat_view)
                self.assertFalse(window.wall.timer.isActive())

                limit = next(widget for widget in window.findChildren(orbit.QSpinBox)
                             if widget.accessibleName() == "Managed tab limit")
                self.assertEqual(limit.text(), "All")
                extra = {f"/course-player/mock/extra-{index}": f"Extra {index}" for index in range(3)}
                window.queue.update(extra)
                limit.setValue(2)
                self.assertEqual(len(window.browsers()), 3)  # My Learning and two courses
                limit.setValue(0)
                self.assertEqual(len(window.browsers()), 4)
                window.fill_queue()
                self.assertEqual(len(window.browsers()), 4)
                window.settings["auto_open"] = False
                window.fill_queue()
                self.assertFalse(window.queue_open_timer.isActive())
                window.settings["auto_open"] = True
                window.fill_queue()
                self.until(lambda: set(extra).issubset({view.course for view in window.browsers()}))
            finally:
                window.quit()
                window.dispose()
                orbit.ORIGIN, orbit.QWebEnginePage, orbit.PageBridge = saved
                orbit.CAMERA_PLAYERS.pop("fixture", None)
                server.shutdown()


if __name__ == "__main__":
    unittest.main()
