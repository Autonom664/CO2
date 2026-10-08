import json
import shutil
import subprocess
import unittest
from pathlib import Path

import numpy as np
from skimage.graph import MCP_Geometric

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "web" / "engine" / "paths.js"
HARNESS = ROOT / "tests" / "js" / "paths_harness.mjs"


@unittest.skipUnless(shutil.which("node"), "Node.js is needed to run the browser engine")
class BrowserPathEngineParityTests(unittest.TestCase):
    """The browser engine must reproduce MCP_Geometric(fully_connected=True)."""

    def run_engine(self, cases):
        result = subprocess.run(
            ["node", str(HARNESS), str(ENGINE)],
            input=json.dumps({"cases": cases}), capture_output=True, text=True, check=True,
        )
        return json.loads(result.stdout)

    def test_accumulated_costs_and_paths_match_mcp_geometric(self):
        rng = np.random.default_rng(7)
        cases, expected = [], []
        for _ in range(6):
            height, width = rng.integers(8, 30, size=2)
            cost = rng.uniform(0.4, 12, size=(height, width))
            cost[rng.random((height, width)) < 0.2] = np.inf  # barriers
            start = (0, 0)
            end = (height - 1, width - 1)
            cost[start] = cost[end] = 1.0
            mcp = MCP_Geometric(np.where(np.isfinite(cost), cost, np.inf), fully_connected=True)
            acc, _ = mcp.find_costs([start])
            cases.append({
                "width": int(width), "height": int(height),
                "cost": [None if not np.isfinite(v) else float(v) for v in cost.ravel()],
                "start": 0, "end": int(end[0] * width + end[1]),
            })
            expected.append((cost, acc))
        for case, (cost, acc), out in zip(cases, expected, self.run_engine(cases)):
            js = np.array([np.inf if v is None else v for v in out["acc"]]).reshape(acc.shape)
            np.testing.assert_allclose(js, acc, rtol=1e-9, atol=1e-9)
            if np.isfinite(acc[-1, -1]):
                # Ties may pick a different path, but its cost must be optimal.
                width = case["width"]
                cells = [divmod(i, width) for i in out["path"]]
                total = 0.0
                for (r0, c0), (r1, c1) in zip(cells, cells[1:]):
                    self.assertLessEqual(max(abs(r1 - r0), abs(c1 - c0)), 1)
                    step = np.sqrt(2) if r0 != r1 and c0 != c1 else 1.0
                    total += (cost[r0, c0] + cost[r1, c1]) / 2 * step
                self.assertAlmostEqual(total, acc[-1, -1], places=9)
                self.assertEqual(cells[0], (0, 0))

    def test_snaps_to_nearest_passable_cell(self):
        cost = [None] * 25
        cost[3 * 5 + 4] = 1.0   # (3, 4): distance sqrt(1 + 4) from (2, 2)
        cost[0 * 5 + 2] = 1.0   # (0, 2): distance 2 from (2, 2), nearer
        out = self.run_engine([{
            "width": 5, "height": 5, "cost": cost, "start": 2, "end": 2, "snap": [2, 2],
        }])
        self.assertEqual(out[0]["snapped"], 2)


if __name__ == "__main__":
    unittest.main()
