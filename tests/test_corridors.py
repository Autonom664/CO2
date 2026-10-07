import unittest

import numpy as np
from rasterio.transform import from_origin
from shapely.geometry import Point

from src import corridors


class CorridorTests(unittest.TestCase):
    def setUp(self) -> None:
        # 21 × 41 grid of unit cost with a costly block in the middle.
        self.cost = np.ones((21, 41), dtype=np.float64)
        self.cost[5:16, 18:23] = 50
        self.transform = from_origin(500_000, 6_200_000, 100, 100)
        self.start, self.end = (10, 2), (10, 38)

    def through(self) -> tuple[np.ndarray, float]:
        from_start = corridors.accumulated_cost(self.cost, self.start)
        from_end = corridors.accumulated_cost(self.cost, self.end)
        return from_start + from_end, float(from_start[self.end])

    def test_best_path_through_any_cell_never_beats_the_optimum(self) -> None:
        through, optimum = self.through()
        self.assertAlmostEqual(float(through.min()), optimum, places=6)
        self.assertAlmostEqual(float(through[self.start]), optimum, places=6)

    def test_corridor_grows_with_tolerance_and_contains_endpoints(self) -> None:
        through, optimum = self.through()
        narrow, narrow_cells = corridors.corridor_polygon(
            through, optimum, 0.01, self.transform, 0
        )
        wide, wide_cells = corridors.corridor_polygon(
            through, optimum, 0.25, self.transform, 0
        )
        self.assertGreater(wide_cells, narrow_cells)
        self.assertTrue(wide.contains(narrow.representative_point()))
        for row, col in (self.start, self.end):
            x, y = self.transform @ (col + 0.5, row + 0.5)
            self.assertTrue(wide.buffer(1).contains(Point(x, y)))

    def test_costly_block_is_avoided_by_narrow_corridor(self) -> None:
        through, optimum = self.through()
        mask = through <= optimum * 1.01
        self.assertFalse(mask[10, 20])
        self.assertTrue(mask[self.start] and mask[self.end])


if __name__ == "__main__":
    unittest.main()
