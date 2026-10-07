import csv
import tempfile
import unittest
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import Point, box

from src.acquire_data import extend_extent_to_offshore_storage


class OffshoreExtentTests(unittest.TestCase):
    def test_storage_point_adds_a_narrow_corridor_from_land(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            hotspots_path = Path(temporary) / "hotspots.csv"
            transformer = Transformer.from_crs(
                "EPSG:25832", "EPSG:4326", always_xy=True
            )
            lon, lat = transformer.transform(520_000, 6_200_000)
            with hotspots_path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.writer(stream)
                writer.writerow(["id", "role", "lon", "lat"])
                writer.writerow(["offshore", "storage", lon, lat])
                writer.writerow(["source", "source", 10, 57])

            land = box(499_000, 6_199_000, 501_000, 6_201_000)
            base_extent = land.buffer(1_000)
            expanded = extend_extent_to_offshore_storage(
                base_extent, land, hotspots_path, 1_000
            )

            self.assertTrue(expanded.covers(Point(520_000, 6_200_000)))
            self.assertTrue(expanded.covers(Point(510_000, 6_200_000)))
            self.assertFalse(expanded.covers(Point(510_000, 6_203_000)))


if __name__ == "__main__":
    unittest.main()
