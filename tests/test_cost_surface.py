import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

import geopandas as gpd
import numpy as np
import rasterio
import yaml
from rasterio.transform import from_origin, rowcol
from shapely.geometry import LineString, box

from src.cost_surface import (
    build_cost_surface,
    dwelling_proximity_costs,
    max_group_contribution,
    parallel_corridor_mask,
    population_costs,
    rasterize_layer,
    validate_class_bits,
    validate_cost_scores,
)
import src.cost_surface as cost_surface


class CostScoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.costs = {
            "open_land": 1,
            "open_sea": 2,
            "road_crossing": 3,
            "building_barrier": 10,
            "population": {"minimum": 1, "maximum": 10},
        }
        self.layers = {"roads": {"cost": "road_crossing"}}
        self.barriers = ["building_barrier"]

    def test_accepts_scores_within_one_to_ten(self) -> None:
        validate_cost_scores(self.costs, self.layers, self.barriers)

    def test_rejects_area_score_outside_one_to_ten(self) -> None:
        self.costs["road_crossing"] = 11
        with self.assertRaisesRegex(ValueError, "between 1 and 10"):
            validate_cost_scores(self.costs, self.layers, self.barriers)

    def test_rejects_population_score_outside_one_to_ten(self) -> None:
        self.costs["population"]["minimum"] = 0
        with self.assertRaisesRegex(ValueError, "between 1 and 10"):
            validate_cost_scores(self.costs, self.layers, self.barriers)

    def test_requires_buildings_to_remain_barriers(self) -> None:
        self.barriers = []
        with self.assertRaisesRegex(ValueError, "impassable barriers"):
            validate_cost_scores(self.costs, self.layers, self.barriers)


class PhaseACostModelTests(unittest.TestCase):
    def test_class_bits_widen_to_uint32_for_phase_a(self) -> None:
        self.assertEqual(
            validate_class_bits({"existing": 1, "new": 262_144}),
            np.dtype("uint32"),
        )

    def test_class_bits_must_be_unique_powers_of_two(self) -> None:
        with self.assertRaisesRegex(ValueError, "unique power of two"):
            validate_class_bits({"first": 2, "duplicate": 2})
        with self.assertRaisesRegex(ValueError, "unique power of two"):
            validate_class_bits({"invalid": 3})

    def test_protected_classes_use_the_highest_overlapping_score(self) -> None:
        natura = np.array([[True, True, False]])
        protected = np.array([[True, False, True]])
        contribution = max_group_contribution(
            [(natura, 9.0), (protected, 8.0)], (1, 3)
        )
        np.testing.assert_array_equal(contribution, [[9.0, 9.0, 8.0]])

    def test_dwelling_proximity_is_distance_scaled_and_land_only(self) -> None:
        buildings = np.zeros((1, 5), dtype=bool)
        buildings[0, 0] = True
        land = np.array([[False, True, True, True, True]])
        scores, mask = dwelling_proximity_costs(
            buildings, land, 100, 300, 6
        )
        self.assertFalse(mask[0, 0])
        self.assertTrue(mask[0, 1])
        self.assertAlmostEqual(float(scores[0, 1]), 4.0)
        self.assertTrue(mask[0, 2])
        self.assertAlmostEqual(float(scores[0, 2]), 2.0)
        self.assertFalse(mask[0, 3])
        self.assertFalse(mask[0, 4])

    def test_parallel_band_excludes_assets_and_honours_distance_bounds(self) -> None:
        assets = np.zeros((1, 6), dtype=bool)
        assets[0, 2] = True
        mask = parallel_corridor_mask(
            assets,
            np.ones_like(assets),
            100,
            50,
            200,
        )
        np.testing.assert_array_equal(mask, [[True, True, False, True, True, False]])

    def test_build_cost_surface_writes_uint32_phase_a_classes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            processed = root / "processed"
            processed.mkdir()

            def write_layers(
                filename: str,
                layers: dict[str, gpd.GeoDataFrame],
            ) -> None:
                path = processed / filename
                for index, (name, frame) in enumerate(layers.items()):
                    frame.to_file(
                        path,
                        layer=name,
                        driver="GPKG",
                        index=False,
                        mode="w" if index == 0 else "a",
                    )

            extent_geometry = box(500_000, 6_200_000, 500_800, 6_200_800)
            write_layers(
                "coast_land_water.gpkg",
                {
                    "analysis_extent": gpd.GeoDataFrame(
                        geometry=[extent_geometry], crs="EPSG:25832"
                    ),
                    "land": gpd.GeoDataFrame(
                        geometry=[extent_geometry], crs="EPSG:25832"
                    ),
                },
            )
            building = box(500_400, 6_200_200, 500_500, 6_200_300)
            write_layers(
                "water_and_urban.gpkg",
                {
                    "buildings": gpd.GeoDataFrame(
                        geometry=[building], crs="EPSG:25832"
                    )
                },
            )
            def line(x: int) -> LineString:
                return LineString([(x, 6_200_050), (x, 6_200_750)])

            phase_layers = {
                "roads_major": gpd.GeoDataFrame(
                    geometry=[line(500_150)], crs="EPSG:25832"
                ),
                "roads_minor": gpd.GeoDataFrame(
                    geometry=[line(500_650)], crs="EPSG:25832"
                ),
                "forest": gpd.GeoDataFrame(
                    geometry=[box(500_300, 6_200_500, 500_500, 6_200_700)],
                    crs="EPSG:25832",
                ),
                "power_lines": gpd.GeoDataFrame(
                    {"osm_id": [1]},
                    geometry=[line(500_350)],
                    crs="EPSG:25832",
                ),
                "pipelines": gpd.GeoDataFrame(
                    {"osm_id": [2]},
                    geometry=[line(500_450)],
                    crs="EPSG:25832",
                ),
            }
            write_layers("phase_a_infrastructure.gpkg", phase_layers)
            write_layers(
                "infrastructure.gpkg",
                {
                    "railways": gpd.GeoDataFrame(
                        geometry=[
                                LineString(
                                    [(500_050, 6_200_450), (500_750, 6_200_450)]
                                )
                        ],
                        crs="EPSG:25832",
                    )
                },
            )
            write_layers(
                "natura2000.gpkg",
                {
                    "habitats": gpd.GeoDataFrame(
                        geometry=[
                            box(500_500, 6_200_500, 500_600, 6_200_600)
                        ],
                        crs="EPSG:25832",
                    )
                },
            )
            write_layers(
                "protected_areas.gpkg",
                {
                    "protected_nature_s3": gpd.GeoDataFrame(
                        geometry=[
                            box(500_500, 6_200_500, 500_600, 6_200_600)
                        ],
                        crs="EPSG:25832",
                    )
                },
            )
            bits = {
                "open_land": 1,
                "open_sea": 2,
                "building_barrier": 4,
                "road_major": 8,
                "road_minor": 16,
                "railway_crossing": 32,
                "forest": 64,
                "natura2000_habitats": 128,
                "protected_nature_s3": 256,
                "dwelling_proximity": 65536,
                "parallel_corridor": 131072,
            }
            config = {
                "grid": {
                    "crs": "EPSG:25832",
                    "resolution_m": 100,
                    "cost_reference_resolution_m": 250,
                    "combine_rule": "additive",
                    "nodata": -9999,
                },
                "costs": {
                    "open_land": 1,
                    "open_sea": 2,
                    "building_barrier": 10,
                    "road_major": 4,
                    "road_minor": 2,
                    "railway_crossing": 5,
                    "forest": 6,
                    "natura2000": 9,
                    "protected_nature": 8,
                    "population": {
                        "enabled": False,
                        "minimum": 1,
                        "maximum": 10,
                    },
                    "dwelling_proximity": {
                        "enabled": True,
                        "max_distance_m": 200,
                        "max_score": 6,
                    },
                },
                "barriers": ["building_barrier"],
                "rasterization": {
                    "linear_all_touched": True,
                    "polygon_all_touched": False,
                },
                "layers": {
                    "roads_major": {
                        "file": "phase_a_infrastructure.gpkg",
                        "layer": "roads_major",
                        "cost": "road_major",
                        "class_bit": "road_major",
                        "geometry": "linear",
                        "parallel_asset": True,
                    },
                    "roads_minor": {
                        "file": "phase_a_infrastructure.gpkg",
                        "layer": "roads_minor",
                        "cost": "road_minor",
                        "class_bit": "road_minor",
                        "geometry": "linear",
                    },
                    "railways": {
                        "file": "infrastructure.gpkg",
                        "layer": "railways",
                        "cost": "railway_crossing",
                        "geometry": "linear",
                        "parallel_asset": True,
                    },
                    "forest": {
                        "file": "phase_a_infrastructure.gpkg",
                        "layer": "forest",
                        "cost": "forest",
                        "geometry": "polygon",
                        "surface": "land",
                    },
                    "natura2000_habitats": {
                        "file": "natura2000.gpkg",
                        "layer": "habitats",
                        "cost": "natura2000",
                        "class_bit": "natura2000_habitats",
                        "geometry": "polygon",
                    },
                    "protected_nature_s3": {
                        "file": "protected_areas.gpkg",
                        "layer": "protected_nature_s3",
                        "cost": "protected_nature",
                        "class_bit": "protected_nature_s3",
                        "geometry": "polygon",
                    },
                },
                "combine_groups": {
                    "protected_areas": {
                        "members": ["natura2000", "protected_nature"],
                        "rule": "max",
                    }
                },
                "parallel_corridor": {
                    "enabled": True,
                    "inner_distance_m": 50,
                    "outer_distance_m": 300,
                    "factor": 0.8,
                    "exclude_osm_ids": [],
                    "assets": [
                        {
                            "file": "phase_a_infrastructure.gpkg",
                            "layer": "power_lines",
                        },
                        {
                            "file": "phase_a_infrastructure.gpkg",
                            "layer": "pipelines",
                        },
                    ],
                },
                "class_bits": bits,
            }
            config_path = root / "costs.yaml"
            config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
            cost_path = processed / "cost_surface_100m.tif"
            with (
                patch("src.cost_surface.PROCESSED", processed),
                patch("src.cost_surface.ROOT", root),
            ):
                build_cost_surface(config_path, cost_path)

            with rasterio.open(cost_path) as cost_raster:
                costs = cost_raster.read(1)
                row, col = rowcol(
                    cost_raster.transform, 500_550, 6_200_550
                )
                self.assertAlmostEqual(float(costs[row, col]), 3.2)
                barrier_row, barrier_col = rowcol(
                    cost_raster.transform, 500_450, 6_200_250
                )
                self.assertEqual(float(costs[barrier_row, barrier_col]), -9999)
            with rasterio.open(
                processed / "cost_class_mask_100m.tif"
            ) as class_raster:
                class_mask = class_raster.read(1)
                self.assertEqual(class_raster.dtypes[0], "uint32")
                self.assertTrue(np.any(class_mask & bits["forest"]))
                self.assertTrue(np.any(class_mask & bits["dwelling_proximity"]))
                self.assertTrue(np.any(class_mask & bits["parallel_corridor"]))


class RasterizeLayerTests(unittest.TestCase):
    def test_empty_batch_ends_read_without_clearing_prior_burns(self) -> None:
        first_batch = gpd.GeoDataFrame(
            geometry=[box(0, 1, 1, 2)], crs="EPSG:25832"
        )
        empty_batch = gpd.GeoDataFrame(
            geometry=[], crs="EPSG:25832"
        )
        with (
            patch.object(
                cost_surface.pyogrio,
                "read_info",
                return_value={"features": 3},
            ),
            patch.object(
                cost_surface.pyogrio,
                "read_dataframe",
                side_effect=[first_batch, empty_batch],
            ) as read_dataframe,
        ):
            mask = rasterize_layer(
                gpkg=cost_surface.Path("unused.gpkg"),
                layer="synthetic",
                transform=from_origin(0, 2, 1, 1),
                width=2,
                height=2,
                all_touched=False,
                target_crs="EPSG:25832",
            )

        self.assertEqual(read_dataframe.call_count, 2)
        self.assertEqual(int(mask.sum()), 1)


class PopulationThresholdTests(unittest.TestCase):
    def test_cells_below_threshold_receive_no_population_cost(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raster_path = root / "population_2020_100m.tif"
            profile = {
                "driver": "GTiff",
                "height": 2,
                "width": 2,
                "count": 1,
                "dtype": "float32",
                "crs": "EPSG:25832",
                "transform": from_origin(500_000, 6_200_200, 100, 100),
                "nodata": -9999,
            }
            with rasterio.open(raster_path, "w", **profile) as dataset:
                dataset.write(
                    np.array([[0.5, 1], [2, 4]], dtype=np.float32), 1
                )
            with patch("src.cost_surface.PROCESSED", root):
                scores, summary = population_costs(
                    extent_mask=np.ones((2, 2), dtype=bool),
                    land_mask=np.ones((2, 2), dtype=bool),
                    transform=profile["transform"],
                    width=2,
                    height=2,
                    target_crs="EPSG:25832",
                    resolution_m=100,
                    settings={
                        "min_per_cell": 1,
                        "minimum": 1,
                        "maximum": 10,
                        "quantiles": 2,
                    },
                )

        self.assertEqual(float(scores[0, 0]), 0)
        self.assertGreater(float(scores[0, 1]), 0)
        self.assertEqual(summary["threshold_per_analysis_cell"], 1)


if __name__ == "__main__":
    unittest.main()
