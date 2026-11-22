import tempfile
import time
import unittest
from pathlib import Path

from lora_tunnel_zero import updates
from lora_tunnel_zero.config import DEFAULTS
from lora_tunnel_zero.demo import DemoRadio
from lora_tunnel_zero.engine import Engine
from lora_tunnel_zero.gnss import GPS
from lora_tunnel_zero.ui import screens
from lora_tunnel_zero.ui.app import App
from lora_tunnel_zero.ui.display import PNGDisplay
from lora_tunnel_zero.ui.keys import Key, ScriptedInput


def registry(version, package="lora-tunnel", status="approved"):
    return {"schema_version": 2, "apps": [
        {"share_code": "MESH", "version": "9.9.9", "download": {"package": "meshzero"}},
        {"share_code": "LORA", "version": version, "review": {"status": status},
         "download": {"type": "deb", "package": package}},
    ]}


def releases(*tags, prerelease=False):
    items = [{"tag_name": "v0.9.0", "draft": False, "prerelease": False}]
    items += [{"tag_name": t, "draft": False, "prerelease": prerelease} for t in tags]
    return items


def fake_fetch(store=None, github=None, store_error=False, github_error=False):
    calls = []

    def fetch(url, timeout=8.0, no_cache=False):
        calls.append(url)
        if url in updates.REGISTRIES:
            if store_error:
                raise OSError("offline")
            return store if store is not None else {"apps": []}
        if github_error:
            raise OSError("offline")
        return github if github is not None else []
    fetch.calls = calls
    return fetch


class VersionTests(unittest.TestCase):
    def test_versions_compare_numerically(self):
        self.assertTrue(updates.is_newer("1.1.10", "1.1.9"))
        self.assertTrue(updates.is_newer("1.2", "1.1.9"))
        self.assertFalse(updates.is_newer("1.1.1", "1.1.1"))
        self.assertFalse(updates.is_newer("1.1.0", "1.1"))          # same version
        self.assertFalse(updates.is_newer("1.1.1-1", "1.1.1"))      # Debian revision ignored
        self.assertFalse(updates.is_newer("garbage", "1.0"))
        self.assertFalse(updates.is_newer(None, "1.0"))
        self.assertEqual(updates.parse_version("v2.0.1"), (2, 0, 1))

    def test_store_and_github_versions(self):
        self.assertEqual(updates.store_version(registry("1.2.0")), "1.2.0")
        self.assertIsNone(updates.store_version(registry("1.2.0", status="pending")))
        self.assertIsNone(updates.store_version({"apps": [{"version": "5", "download": {"package": "x"}}]}))
        self.assertIsNone(updates.store_version("not json"))
        self.assertEqual(updates.github_version(releases("cardputer-zero-v1.1.1", "cardputer-zero-v1.2.0")), "1.2.0")
        self.assertIsNone(updates.github_version(releases("cardputer-zero-v2.0.0", prerelease=True)))
        self.assertIsNone(updates.github_version({"message": "rate limited"}))


class CheckTests(unittest.TestCase):
    def test_store_update_wins(self):
        result = updates.check(fake_fetch(registry("9.0.0"), releases("cardputer-zero-v9.0.0")))
        status, headline, lines = updates.summary(result, "1.1.1")
        self.assertEqual(status, "store")
        self.assertIn("9.0.0", headline)
        self.assertTrue(any("press 7" in line for line in lines))

    def test_github_only_update_and_up_to_date(self):
        result = updates.check(fake_fetch(registry("1.1.1"), releases("cardputer-zero-v1.2.0")))
        self.assertEqual(updates.summary(result, "1.1.1")[0], "github")
        result = updates.check(fake_fetch(registry("1.1.1"), releases("cardputer-zero-v1.1.1")))
        self.assertEqual(updates.summary(result, "1.1.1")[0], "current")
        result = updates.check(fake_fetch({"apps": []}, releases()))
        status, _, lines = updates.summary(result, "1.1.1")
        self.assertEqual(status, "current")
        self.assertTrue(any("isn't listed" in line for line in lines))

    def test_offline_and_mirror_fallback(self):
        result = updates.check(fake_fetch(store_error=True, github_error=True))
        self.assertEqual(updates.summary(result, "1.1.1")[0], "error")
        tried = []

        def mirror(url, timeout=8.0, no_cache=False):
            tried.append(url)
            if url == updates.REGISTRIES[0]:
                raise OSError("blocked")
            if url in updates.REGISTRIES:
                return registry("3.0.0")
            raise OSError("offline")
        result = updates.check(mirror)
        self.assertEqual(result["store"], "3.0.0")
        self.assertEqual(tried[:2], list(updates.REGISTRIES))
        self.assertEqual(updates.summary(result, "1.1.1")[0], "store")

    def test_checker_runs_in_background_and_announces_once(self):
        checker = updates.UpdateChecker(fake_fetch(registry("5.0.0")))
        self.assertTrue(checker.start())
        checker.wait(5)
        self.assertEqual(checker.take_announcement("1.1.1"), "5.0.0")
        self.assertIsNone(checker.take_announcement("1.1.1"))
        quiet = updates.UpdateChecker(fake_fetch(registry("1.1.1")))
        quiet.start()
        quiet.wait(5)
        self.assertIsNone(quiet.take_announcement("1.1.1"))


class UpdateScreenTests(unittest.TestCase):
    def make_app(self, checker, start=False):
        cfg = dict(DEFAULTS, region="US", backend="demo")
        e = Engine(cfg, radio_factory=lambda c, p: DemoRadio(p, rate=25), gps=GPS(use_uart=False))
        work = Path(tempfile.mkdtemp())
        return App(PNGDisplay(work / "f.png"), ScriptedInput(), e, e.cfg, config_path=work / "c.json",
                   data_root=work, splash=False, updates=checker, check_updates_on_start=start)

    def test_settings_screen_and_startup_toast(self):
        fetch = fake_fetch(registry("7.0.0"))
        app = self.make_app(updates.UpdateChecker(fetch), start=True)
        app.step(0)
        app.updates.wait(5)
        app.step(0)
        self.assertIn("7.0.0", app.toast_text)
        settings = screens.Settings()
        app.stack = [screens.Home(), settings]
        labels = {key: value for key, _, value in settings.items(app)}
        self.assertEqual(labels["updates"], "v7.0.0 in Store")
        self.assertEqual(labels["update_check_start"], "On")
        app.pick_setting("update_check_start")
        self.assertFalse(app.cfg["update_check_start"])
        screen = screens.Updates()
        app.stack = [screens.Home(), screen]
        self.assertEqual(app.compose().size, (320, 170))
        app.updates.wait(5)
        app.compose()
        screen.handle(Key("ENTER"), app)
        app.updates.wait(5)
        self.assertEqual(app.compose().size, (320, 170))

    def test_no_network_unless_asked(self):
        fetch = fake_fetch(registry("7.0.0"))
        app = self.make_app(updates.UpdateChecker(fetch))
        app.step(0)
        time.sleep(0.1)
        self.assertEqual(fetch.calls, [])
        app.stack = [screens.Home(), screens.Settings()]
        app.compose()
        self.assertEqual(fetch.calls, [])

    def test_startup_check_respects_setting(self):
        fetch = fake_fetch(registry("7.0.0"))
        app = self.make_app(updates.UpdateChecker(fetch), start=True)
        app.cfg["update_check_start"] = False
        app.step(0)
        time.sleep(0.1)
        self.assertEqual(fetch.calls, [])
