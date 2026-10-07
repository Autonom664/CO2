import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import geopandas as gpd
from pyproj import Transformer
from shapely import union_all
from shapely.geometry import Point, box

from src.acquire_data import (
    exclude_foreign_land_from_extent,
    extend_extent_to_offshore_storage,
    prepare_coast_and_extent,
)


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

    def test_open_sea_layer_excludes_foreign_land(self) -> None:
        full_extent = box(0, 0, 4, 4)
        country_boundary = box(0, 0, 2, 4)
        foreign_geometry = box(3, 0, 4, 4)
        all_land_geometry = union_all(
            [box(0, 0, 1, 4), foreign_geometry]
        )
        extent_geometry, foreign_geometry = exclude_foreign_land_from_extent(
            full_extent, all_land_geometry, country_boundary
        )
        self.assertEqual(extent_geometry.intersection(foreign_geometry).area, 0)
        self.assertTrue(extent_geometry.covers(Point(2.5, 2)))
        extent = gpd.GeoDataFrame(
            {"buffer_m": [0]},
            geometry=[extent_geometry],
            crs="EPSG:25832",
        )
        country_land = gpd.GeoDataFrame(
            {"source": ["Denmark"]},
            geometry=[box(0, 0, 2, 4)],
            crs="EPSG:25832",
        )
        foreign_land = gpd.GeoDataFrame(
            {"source": ["foreign"]},
            geometry=[foreign_geometry],
            crs="EPSG:25832",
        )
        with tempfile.TemporaryDirectory() as temporary:
            with patch("src.acquire_data.PROCESSED", Path(temporary)):
                prepare_coast_and_extent(extent, country_land, foreign_land)
            open_sea = gpd.read_file(
                Path(temporary) / "coast_land_water.gpkg",
                layer="open_sea",
            )
            self.assertTrue(
                union_all(open_sea.geometry.array).intersection(
                    foreign_geometry
                ).area
                == 0
            )


if __name__ == "__main__":
    unittest.main()
