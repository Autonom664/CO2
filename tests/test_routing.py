import unittest
import csv
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import geopandas as gpd
import numpy as np
import rasterio
import yaml
from pyproj import Transformer
from rasterio.transform import from_origin

from src.routing import (
    build_route_feature,
    make_route_pairs,
    minimum_spanning_tree,
    nearest_valid_cell,
    route_hotspots,
)


class RoutingTests(unittest.TestCase):
    def test_nearest_traversable_cell_obeys_snap_limit(self) -> None:
        valid = np.zeros((5, 5), dtype=bool)
        valid[2, 3] = True
        self.assertEqual(
            nearest_valid_cell(valid, 2, 2, 100, 150, "h1"),
            (2, 3, 100.0),
        )
        with self.assertRaisesRegex(ValueError, "maximum allowed"):
            nearest_valid_cell(valid, 2, 2, 100, 50, "h1")

    def test_route_includes_diagonal_distance_and_class_lengths(self) -> None:
        classes = np.array(
            [
                [1, 1],
                [1, 2],
            ],
            dtype=np.uint16,
        )
        route = build_route_feature(
            {"id": "A", "name": "Alpha", "snap_distance_m": 0},
            {"id": "B", "name": "Beta", "snap_distance_m": 0},
            [(0, 0), (1, 1)],
            2.0,
            classes,
            from_origin(0, 200, 100, 100),
            100,
            {
                "open_land": 1,
                "open_sea": 2,
                "road_crossing": 4,
                "railway_crossing": 8,
                "watercourse_crossing": 16,
                "urban_area": 32,
                "lake": 64,
                "wetland": 128,
                "natura2000_habitats": 256,
                "natura2000_birds": 512,
                "protected_nature_s3": 1024,
                "protected_reserves": 2048,
                "population": 4096,
                "building_barrier": 8192,
            },
            {
                "natura2000": ["natura2000_habitats", "natura2000_birds"],
                "protected_nature": [
                    "protected_nature_s3",
                    "protected_reserves",
                ],
            },
        )
        self.assertAlmostEqual(route["properties"]["length_km"], 0.141, places=3)
        self.assertAlmostEqual(route["properties"]["km_open_land"], 0.0, places=3)
        self.assertAlmostEqual(route["properties"]["km_open_sea"], 0.141, places=3)
        self.assertEqual(route["properties"]["accumulated_cost"], 2.0)

    def test_mst_selects_lowest_cost_edges(self) -> None:
        routes = [
            {"properties": {"from_id": "A", "to_id": "B", "accumulated_cost": 1}},
            {"properties": {"from_id": "A", "to_id": "C", "accumulated_cost": 4}},
            {"properties": {"from_id": "B", "to_id": "C", "accumulated_cost": 2}},
        ]
        tree = minimum_spanning_tree(routes, 3)
        self.assertEqual(
            {(route["properties"]["from_id"], route["properties"]["to_id"]) for route in tree},
            {("A", "B"), ("B", "C")},
        )

    def test_untyped_hotspots_keep_all_pairs_behavior(self) -> None:
        hotspots = [
            {"id": f"H{index}", "role": "node"} for index in range(12)
        ]
        self.assertEqual(len(make_route_pairs(hotspots)), 66)

    def test_route_hotspots_writes_source_storage_pairs_and_tree(self) -> None:
        class_bits = {
            "open_land": 1,
            "open_sea": 2,
            "road_crossing": 4,
            "railway_crossing": 8,
            "watercourse_crossing": 16,
            "urban_area": 32,
            "lake": 64,
            "wetland": 128,
            "natura2000_habitats": 256,
            "natura2000_birds": 512,
            "protected_nature_s3": 1024,
            "protected_reserves": 2048,
            "population": 4096,
            "building_barrier": 8192,
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            processed = root / "processed"
            processed.mkdir()
            transform = from_origin(500_000, 6_200_000, 100, 100)
            profile = {
                "driver": "GTiff",
                "width": 30,
                "height": 30,
                "count": 1,
                "crs": "EPSG:25832",
                "transform": transform,
                "tiled": True,
            }
            with rasterio.open(
                processed / "cost_surface_100m.tif",
                "w",
                **(profile | {"dtype": "float32", "nodata": -9999}),
            ) as dataset:
                dataset.write(np.ones((30, 30), dtype=np.float32), 1)
            with rasterio.open(
                processed / "cost_class_mask_100m.tif",
                "w",
                **(profile | {"dtype": "uint16", "nodata": 0}),
            ) as dataset:
                dataset.write(
                    np.full((30, 30), class_bits["open_land"], dtype=np.uint16),
                    1,
                )
                dataset.update_tags(class_bits=json.dumps(class_bits))
            transformer = Transformer.from_crs(
                "EPSG:25832", "EPSG:4326", always_xy=True
            )
            hotspots_path = root / "hotspots.csv"
            with hotspots_path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.writer(stream)
                writer.writerow(
                    [
                        "id",
                        "name",
                        "lon",
                        "lat",
                        "role",
                        "site_type",
                        "project_status",
                        "location_basis",
                        "source_url",
                    ]
                )
                for index in range(12):
                    row = 2 + (index // 4) * 8
                    col = 2 + (index % 4) * 6
                    x, y = rasterio.transform.xy(
                        transform, row, col, offset="center"
                    )
                    lon, lat = transformer.transform(x, y)
                    writer.writerow(
                        [
                            f"H{index + 1}",
                            f"Site {index + 1}",
                            lon,
                            lat,
                            "source" if index < 8 else "storage",
                            "demo",
                            "test",
                            "test point",
                            "https://example.com",
                        ]
                    )
            config_path = root / "costs.yaml"
            config_path.write_text(
                yaml.safe_dump(
                    {
                        "grid": {"resolution_m": 100},
                        "routing": {"max_snap_distance_m": 0},
                        "class_bits": class_bits,
                        "route_classes": {
                            "natura2000": [
                                "natura2000_habitats",
                                "natura2000_birds",
                            ],
                            "protected_nature": [
                                "protected_nature_s3",
                                "protected_reserves",
                            ],
                        },
                    }
                ),
                encoding="utf-8",
            )
            with patch("src.routing.PROCESSED", processed):
                routes_path, network_path, pairwise_path = route_hotspots(
                    hotspots_path,
                    processed / "cost_surface_100m.tif",
                    config_path,
                )
            with pairwise_path.open(encoding="utf-8", newline="") as stream:
                pairs = list(csv.DictReader(stream))
            self.assertEqual(len(pairs), 32)
            self.assertTrue(all(pair["from_id"].startswith("H") for pair in pairs))
            routes = gpd.read_file(routes_path)
            self.assertEqual(len(routes), 32)
            self.assertEqual(set(routes["from_role"]), {"source"})
            self.assertEqual(set(routes["to_role"]), {"storage"})
            self.assertEqual(len(gpd.read_file(network_path)), 11)


if __name__ == "__main__":
    unittest.main()
