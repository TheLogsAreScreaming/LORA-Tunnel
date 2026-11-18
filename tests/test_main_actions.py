"""Main action routing/feedback tests; host-only and no device access."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


class MainActionTests(unittest.TestCase):
    def test_real_bounded_queue_and_messaging_feedback(self):
        sys.path.insert(0, str(ROOT / "tools"))
        try:
            from check_main_actions import check
            self.assertIn("checks passed", check())
        finally:
            sys.path.pop(0)


if __name__ == "__main__":
    unittest.main()
