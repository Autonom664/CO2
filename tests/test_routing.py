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
from shapely.geometry import LineString
from skimage.graph import MCP_Geometric

from src.routing import (
    build_route_feature,
    make_mcp_cost_array,
    make_route_pairs,
    make_unordered_pairs,
    minimum_spanning_tree,
    nearest_valid_cell,
    route_hotspots,
    save_geojson,
)


class RoutingTests(unittest.TestCase):
    def test_mcp_cost_array_uses_infinite_barriers(self) -> None:
        cost = np.ones((3, 5), dtype=np.float32)
        valid = np.ones(cost.shape, dtype=bool)
        cost[:, 2] = 0
        valid[:, 2] = False
        cost[0, 1] = np.nan

        mcp_cost = make_mcp_cost_array(cost, valid)

        self.assertEqual(mcp_cost.dtype, np.float64)
        self.assertFalse(np.ma.isMaskedArray(mcp_cost))
        self.assertTrue(np.all(np.isinf(mcp_cost[:, 2])))
        self.assertTrue(np.isinf(mcp_cost[0, 1]))
        cumulative, _ = MCP_Geometric(
            mcp_cost, fully_connected=True
        ).find_costs([(1, 0)])
        self.assertFalse(np.isfinite(cumulative[1, 4]))

    def test_nearest_traversable_cell_obeys_snap_limit(self) -> None:
        valid = np.zeros((5, 5), dtype=bool)
        valid[2, 3] = True
        transform = from_origin(0, 500, 100, 100)
        self.assertEqual(
            nearest_valid_cell(
                valid, 2, 2, 220, 250, transform, 100, 150, "h1"
            ),
            (2, 3, 130.0),
        )
        with self.assertRaisesRegex(ValueError, "maximum allowed"):
            nearest_valid_cell(
                valid, 2, 2, 220, 250, transform, 100, 50, "h1"
            )

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

    def test_geojson_omits_internal_mst_sort_key(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "routes.geojson"
            feature = {
                "geometry": LineString([(0, 0), (1, 1)]),
                "properties": {
                    "from_id": "A",
                    "to_id": "B",
                    "accumulated_cost": 2.35,
                    "_accumulated_cost": 2.345678,
                },
            }

            save_geojson([feature], path, "EPSG:25832")

            with path.open(encoding="utf-8") as stream:
                output = json.load(stream)
        properties = output["features"][0]["properties"]
        self.assertNotIn("_accumulated_cost", properties)
        self.assertEqual(properties["accumulated_cost"], 2.35)

    def test_untyped_hotspots_keep_all_pairs_behavior(self) -> None:
        hotspots = [
            {"id": f"H{index}", "role": "node"} for index in range(15)
        ]
        self.assertEqual(len(make_route_pairs(hotspots)), 105)
        self.assertEqual(len(make_unordered_pairs(hotspots)), 105)

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
                        "ets_installation_id",
                        "ets_verified_2024_t",
                        "planned_capture_tpa",
                        "capture_basis",
                        "capture_source_url",
                    ]
                )
                for index in range(15):
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
                            "342" if index == 0 else "",
                            "12345" if index == 0 else "",
                            "1000" if index == 0 else "",
                            "Test capture source" if index == 0 else "",
                            "https://example.com/capture" if index == 0 else "",
                        ]
                    )
            config_path = root / "costs.yaml"
            config_path.write_text(
                yaml.safe_dump(
                    {
                        "grid": {"resolution_m": 100},
                        "routing": {"max_snap_distance_m": 1},
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
            self.assertEqual(len(pairs), 105)
            self.assertTrue(all(pair["from_id"].startswith("H") for pair in pairs))
            routes = gpd.read_file(routes_path)
            self.assertEqual(len(routes), 56)
            self.assertEqual(set(routes["from_role"]), {"source"})
            self.assertEqual(set(routes["to_role"]), {"storage"})
            self.assertEqual(len(gpd.read_file(network_path)), 14)
            hotspots = gpd.read_file(processed / "hotspots.geojson").set_index("id")
            self.assertEqual(hotspots.loc["H1", "ets_installation_id"], "342")
            self.assertEqual(hotspots.loc["H1", "ets_verified_2024_t"], 12345)
            self.assertEqual(hotspots.loc["H1", "planned_capture_tpa"], 1000)


if __name__ == "__main__":
    unittest.main()
