import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from src import cost_surface

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("node"), "Node.js is needed to run the browser modules")
class ScenarioModuleTests(unittest.TestCase):
    def test_scenario_module_against_the_active_config(self):
        hotspots = ROOT / "data" / "processed" / "hotspots.geojson"
        if not hotspots.exists():
            self.skipTest("hotspots.geojson not built")
        config = cost_surface.load_config(cost_surface.CONFIG)
        with tempfile.TemporaryDirectory() as folder:
            config_path = Path(folder) / "config.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            result = subprocess.run(
                ["node", str(ROOT / "tests" / "js" / "scenario_test.mjs"), str(config_path), str(hotspots)],
                capture_output=True, text=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
