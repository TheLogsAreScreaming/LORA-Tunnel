"""Board touch report parsing tests; host-only and no device access."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


class HeltecTouchTests(unittest.TestCase):
    def test_actual_board_readers_distinguish_failure_from_release(self):
        sys.path.insert(0, str(ROOT / "tools"))
        try:
            from check_heltec_touch import check
            result = check()
            self.assertIn("Heltec: 24 actual touch-driver checks passed", result)
            self.assertIn("Cardputer: 3 actual touch-driver checks passed", result)
        finally:
            sys.path.pop(0)


if __name__ == "__main__":
    unittest.main()
