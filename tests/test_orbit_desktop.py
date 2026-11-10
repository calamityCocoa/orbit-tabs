import json
import tempfile
import time
import unittest
from pathlib import Path

from orbit_desktop import HEARTBEAT_EXPIRY, Hub, save_config


class HubTests(unittest.TestCase):
    now = time.time()
    alpha = "/course-player/workspace/alpha"
    beta = "/course-player/workspace/beta"

    def setUp(self):
        self.hub = Hub({"tab_limit": 1})

    def dashboard(self, **payload):
        return self.hub.report({"role": "dashboard", "tab": "dashboard", **payload}, self.now)

    def scan(self, *course_ids):
        self.hub.request_scan()
        scan = {
            "id": self.hub.scan_id,
            "tenant": "workspace",
            "courses": [{"id": course_id, "title": course_id.title()} for course_id in course_ids],
        }
        return self.dashboard(scan=scan)

    def player(self, path, **payload):
        return self.hub.report({
            "role": "player", "tab": "player", "path": path, "visible": False, **payload,
        }, self.now)

    def test_catalog_cap_reopen_and_completion(self):
        result = self.scan("alpha", "beta")
        self.assertEqual([row["path"] for row in result["open"]], [self.alpha])
        self.player(self.alpha)
        self.assertEqual(self.dashboard()["open"], [])
        self.assertEqual([row["path"] for row in self.dashboard(closed=[self.alpha])["open"]], [self.alpha])
        self.player(self.alpha)
        self.assertEqual(self.scan("beta")["close"], [self.alpha])
        result = self.dashboard(closed=[self.alpha])
        self.assertEqual([row["path"] for row in result["open"]], [self.beta])
        self.player(self.beta)
        self.assertEqual(self.scan()["close"], [self.beta])
        self.assertIn("No unfinished courses", self.hub.status)

    def test_missing_heartbeat_does_not_reopen(self):
        self.scan("alpha")
        self.now += HEARTBEAT_EXPIRY + 1
        self.assertEqual(self.dashboard()["open"], [])
        self.assertIn(self.alpha, self.hub.managed)

    def test_existing_manual_tab_does_not_get_closed(self):
        self.player(self.alpha)
        self.assertEqual(self.scan("alpha")["open"], [])
        self.assertEqual(self.scan()["close"], [])

    def test_timer_and_suggestion_delivery(self):
        started = self.now - 25200
        self.hub.suggestions["player"] = self.now + 60
        self.assertTrue(self.player(self.alpha, opened=started * 1000)["suggest"])
        self.assertFalse(self.player(self.alpha)["suggest"])
        self.assertAlmostEqual(self.hub.tabs["player"].opened, started, places=3)

    def test_failed_scan_preserves_catalog(self):
        self.scan("alpha")
        self.player(self.alpha)
        self.hub.request_scan()
        result = self.dashboard(scan={"id": self.hub.scan_id, "error": "Sign in again"})
        self.assertEqual(result["close"], [])
        self.assertIn(self.alpha, self.hub.courses)

    def test_settings_round_trip(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "settings.json"
            save_config(path, self.hub.config)
            self.assertEqual(json.loads(path.read_text()), self.hub.config)


if __name__ == "__main__":
    unittest.main()
