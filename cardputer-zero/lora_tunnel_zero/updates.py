"""Check whether a newer LORA Tunnel is in the CardputerZero App Store or on GitHub.

The Store installs and upgrades apps itself (it marks an installed app that has
an update, and key 7 upgrades it), so this only tells the user that a version
exists and where to get it. Nothing is downloaded or installed here.
"""

import json
import re
import threading
import time
import urllib.request

from . import __version__

PACKAGE = "lora-tunnel"
SHARE_CODE = "LORA"
TAG_PREFIX = "cardputer-zero-v"
REGISTRIES = (
    "https://cardputerzero.github.io/generated/registry.json",
    "https://cardputer-zero-repo.oss-cn-shenzhen.aliyuncs.com/packages/cn/registry.json",
)
RELEASES = "https://api.github.com/repos/valleytechsolutions/LORA-Tunnel/releases?per_page=30"
INSTALL_PAGE = "github.com/valleytechsolutions/LORA-Tunnel"
MAX_BYTES = 8 * 1024 * 1024


def parse_version(text):
    """"1.2.3" or "1.2.3-1" as a tuple of ints, ignoring the Debian revision; None if unreadable."""
    text = str(text or "").strip().lstrip("vV")
    text = text.split("-", 1)[0].split("+", 1)[0].split("~", 1)[0]
    if not re.fullmatch(r"\d+(\.\d+)*", text):
        return None
    parts = [int(p) for p in text.split(".")]
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def is_newer(candidate, current=__version__):
    a, b = parse_version(candidate), parse_version(current)
    return a is not None and b is not None and a > b


def store_version(registry):
    """This app's version in a Store registry document, or None if it isn't listed."""
    apps = registry.get("apps") if isinstance(registry, dict) else None
    best = None
    for app in apps if isinstance(apps, list) else []:
        if not isinstance(app, dict):
            continue
        download = app.get("download") if isinstance(app.get("download"), dict) else {}
        if download.get("package") != PACKAGE and str(app.get("share_code", "")).upper() != SHARE_CODE:
            continue
        review = app.get("review") if isinstance(app.get("review"), dict) else {}
        if review.get("status", "approved") != "approved":
            continue
        version = str(app.get("version") or "")
        if parse_version(version) and (best is None or parse_version(version) > parse_version(best)):
            best = version
    return best


def github_version(releases):
    """Newest published CardputerZero release tag on GitHub, or None."""
    best = None
    for release in releases if isinstance(releases, list) else []:
        if not isinstance(release, dict) or release.get("draft") or release.get("prerelease"):
            continue
        tag = str(release.get("tag_name") or "")
        if not tag.startswith(TAG_PREFIX):
            continue
        version = tag[len(TAG_PREFIX):]
        if parse_version(version) and (best is None or parse_version(version) > parse_version(best)):
            best = version
    return best


def fetch_json(url, timeout=8.0, no_cache=False):
    if no_cache:
        url += ("&" if "?" in url else "?") + "t=%d" % int(time.time())
    request = urllib.request.Request(url, headers={
        "User-Agent": "LORA-Tunnel-Zero/" + __version__,
        "Accept": "application/json",
        "Cache-Control": "no-cache",
    })
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("reply too large")
    return json.loads(data.decode("utf-8"))


def check(fetch=fetch_json):
    """One check of the Store and GitHub. Never raises."""
    result = {"store": None, "store_ok": False, "github": None, "github_ok": False, "checked_at": time.time()}
    for url in REGISTRIES:
        try:
            result["store"] = store_version(fetch(url, no_cache=True))
            result["store_ok"] = True
            break
        except Exception:  # noqa: BLE001 - offline, blocked or malformed: try the mirror
            continue
    try:
        result["github"] = github_version(fetch(RELEASES))
        result["github_ok"] = True
    except Exception:  # noqa: BLE001
        pass
    return result


def summary(result, current=__version__):
    """(status, headline, detail lines) for a check result."""
    if result is None:
        return "idle", "Not checked yet", ["Press Enter to check for a newer version."]
    store, github = result.get("store"), result.get("github")
    if not result.get("store_ok") and not result.get("github_ok"):
        return "error", "Couldn't check", ["No connection to the Store or GitHub.",
                                           "Connect to Wi-Fi and press Enter to try again."]
    if is_newer(store, current):
        return "store", "Version %s is in the Store" % store, [
            "Open Store from the Home screen, find LORA Tunnel",
            "(share code %s) and press 7 to update." % SHARE_CODE,
            "Your sessions and settings are kept."]
    if is_newer(github, current):
        return "github", "Version %s is on GitHub" % github, [
            "It reaches the Store once M5Stack has reviewed it.",
            "To install it now, use the one-line install from",
            INSTALL_PAGE + "."]
    lines = ["You have the newest version, v%s." % current]
    if result.get("store_ok") and store is None:
        lines.append("LORA Tunnel isn't listed in the Store yet.")
    return "current", "Up to date", lines


class UpdateChecker:
    """Runs one check at a time in the background so the UI never waits on the network."""

    def __init__(self, fetch=fetch_json):
        self._fetch = fetch
        self._lock = threading.Lock()
        self._thread = None
        self.result = None
        self.announced = False

    @property
    def checking(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        with self._lock:
            if self.checking:
                return False
            self._thread = threading.Thread(target=self._run, name="update-check", daemon=True)
            self._thread.start()
            return True

    def _run(self):
        result = check(self._fetch)
        with self._lock:
            self.result = result
            self.announced = False

    def wait(self, timeout=None):
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    def take_announcement(self, current=__version__):
        """The newer version, once, after a check that found one; else None."""
        with self._lock:
            if self.announced or self.result is None:
                return None
            self.announced = True
            result = self.result
        status = summary(result, current)[0]
        if status == "store":
            return result["store"]
        if status == "github":
            return result["github"]
        return None
