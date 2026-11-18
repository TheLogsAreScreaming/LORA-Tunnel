import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class HeltecMeshUiTests(unittest.TestCase):
    def test_real_touch_button_navigation_and_bounds(self):
        sys.path.insert(0, str(ROOT / "tools"))
        try:
            spec = importlib.util.spec_from_file_location("check_heltec_mesh_ui", ROOT / "tools/check_heltec_mesh_ui.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            with tempfile.TemporaryDirectory(prefix="heltec-mesh-ui-check-") as directory:
                self.assertIn("checks passed", module.check(Path(directory)))
                self.assertTrue((Path(directory) / "mesh-long-turbo.json").is_file())
        finally:
            sys.path.pop(0)


if __name__ == "__main__":
    unittest.main()
