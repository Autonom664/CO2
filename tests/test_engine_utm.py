import json
import shutil
import subprocess
import unittest
from pathlib import Path

import numpy as np
from pyproj import Transformer

ROOT = Path(__file__).resolve().parents[1]

SCRIPT = """
import { pathToFileURL } from "node:url";
const m = await import(pathToFileURL(process.argv[1]).href);
const points = JSON.parse(process.argv[2]);
console.log(JSON.stringify(points.map(([lon, lat]) => {
  const [x, y] = m.toUtm32(lon, lat);
  return [x, y, ...m.fromUtm32(x, y)];
})));
"""


@unittest.skipUnless(shutil.which("node"), "Node.js is needed to run the browser modules")
class Utm32Tests(unittest.TestCase):
    def test_matches_pyproj_across_the_analysis_area(self):
        rng = np.random.default_rng(3)
        points = np.column_stack([rng.uniform(3.5, 15.5, 200), rng.uniform(54.3, 58.2, 200)])
        result = subprocess.run(
            ["node", "--input-type=module", "-e", SCRIPT,
             str(ROOT / "web" / "engine" / "utm.js"), json.dumps(points.tolist())],
            capture_output=True, text=True, check=True,
        )
        ours = np.array(json.loads(result.stdout))
        x, y = Transformer.from_crs("EPSG:4326", "EPSG:25832", always_xy=True).transform(
            points[:, 0], points[:, 1]
        )
        self.assertLess(np.max(np.hypot(ours[:, 0] - x, ours[:, 1] - y)), 0.01)  # 1 cm
        np.testing.assert_allclose(ours[:, 2:], points, atol=1e-9)


if __name__ == "__main__":
    unittest.main()
