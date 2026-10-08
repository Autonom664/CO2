import unittest
import json
import tempfile
from contextlib import chdir
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
    load_excluded_osm_ids,
    landfall_cells,
    load_config,
    max_group_contribution,
    parallel_corridor_mask,
    population_costs,
    population_risk_costs,
    rasterize_layer,
    validate_class_bits,
    validate_cost_scores,
)
import src.cost_surface as cost_surface
from src.freshness import config_fingerprint


class CostScoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.costs = {
            "open_land": 1,
            "open_sea": 2,
            "road_major": 3,
            "building_barrier": 10,
            "population": {"minimum": 1, "maximum": 10},
        }
        self.layers = {"roads": {"cost": "road_major"}}
        self.barriers = ["building_barrier"]

    def test_accepts_scores_within_one_to_ten(self) -> None:
        validate_cost_scores(self.costs, self.layers, self.barriers)

    def test_rejects_area_score_outside_one_to_ten(self) -> None:
        self.costs["road_major"] = 11
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

    def test_p12_accepts_half_and_zero_scores(self) -> None:
        self.costs["road_major"] = 0.5
        self.costs["population"] = {"minimum": 0, "maximum": 1}
        validate_cost_scores(
            self.costs, self.layers, self.barriers, minimum_score=0
        )


class P12CostModelTests(unittest.TestCase):
    def test_overlay_keeps_baseline_and_overrides_p12_sections(self) -> None:
        root = Path(__file__).resolve().parents[1]
        baseline = load_config(root / "config" / "costs_baseline.yaml")
        p12 = load_config(root / "config" / "costs_p12.yaml")

        self.assertEqual(baseline["costs"]["road_major"], 4)
        self.assertEqual(p12["costs"]["road_major"], 5)
        self.assertEqual(p12["costs"]["road_minor"], 0.5)
        self.assertEqual(p12["parallel_corridor"]["factor"], 0.9)
        self.assertEqual(
            set(p12["combine_groups"]),
            {"wet_nature", "forest_group", "people"},
        )
        self.assertEqual(p12["layers"]["fredskov"]["class_bit"], "fredskov")
        validate_cost_scores(
            p12["costs"],
            p12["layers"],
            p12["barriers"],
            float(p12["score_minimum"]),
            {"landfall"},
        )

    def test_landfall_marks_only_land_adjacent_to_sea(self) -> None:
        land = np.array([[True, True, True, False]])
        sea = np.array([[False, False, False, True]])
        extent = np.ones_like(land)

        np.testing.assert_array_equal(
            landfall_cells(land, sea, extent),
            [[False, False, True, False]],
        )

    def test_population_risk_uses_population_within_radius(self) -> None:
        counts = np.zeros((5, 5), dtype=np.float32)
        counts[2, 2] = 60
        extent = np.ones_like(counts, dtype=bool)
        land = extent.copy()

        scores, mask, summary = population_risk_costs(
            counts,
            extent,
            land,
            100,
            {
                "radius_m": 1000,
                "threshold_people": 50,
                "maximum": 5,
                "quantiles": 5,
            },
        )

        self.assertTrue(np.all(mask))
        np.testing.assert_array_equal(scores, np.full((5, 5), 5))
        self.assertEqual(summary["cells_above_threshold"], 25)

    def test_people_group_uses_highest_dynamic_score_without_stacking(self) -> None:
        urban_mask = np.array([[True, False, False]])
        population_mask = np.array([[True, True, False]])
        risk_mask = np.array([[False, True, True]])
        contribution = max_group_contribution(
            [
                (urban_mask, 1.0),
                (population_mask, np.array([[0.5, 0.75, 0.0]])),
                (risk_mask, np.array([[0.0, 5.0, 2.0]])),
            ],
            (1, 3),
        )

        np.testing.assert_array_equal(contribution, [[1.0, 5.0, 2.0]])


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
                        geometry=[
                            box(500_000, 6_200_000, 500_700, 6_200_800)
                        ],
                        crs="EPSG:25832",
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
                    ),
                },
            )
            write_layers(
                "phase_b.gpkg",
                {
                    "bnbo": gpd.GeoDataFrame(
                        geometry=[
                                box(500_600, 6_200_600, 500_700, 6_200_700),
                                box(500_500, 6_200_200, 500_600, 6_200_300),
                        ],
                        crs="EPSG:25832",
                    ),
                    "marine_cable_corridor": gpd.GeoDataFrame(
                        geometry=[
                            box(500_700, 6_200_700, 500_800, 6_200_800)
                        ],
                        crs="EPSG:25832",
                    ),
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
                "marine_cable_corridor": 1048576,
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
                    "marine_cable_corridor": 1,
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
                "barriers": ["building_barrier", "protected_barrier"],
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
                    "bnbo": {
                        "file": "phase_b.gpkg",
                        "layer": "bnbo",
                        "cost": "protected_barrier",
                        "class_bit": "protected_barrier",
                        "geometry": "polygon",
                        "optional": True,
                    },
                    "marine_cable_corridor": {
                        "file": "phase_b.gpkg",
                        "layer": "marine_cable_corridor",
                        "cost": "marine_cable_corridor",
                        "class_bit": "marine_cable_corridor",
                        "geometry": "polygon",
                        "optional": True,
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
                "class_bits": bits
                | {
                    "protected_barrier": 524_288,
                    "marine_cable_corridor": 1048576,
                },
                "discount_classes": ["marine_cable_corridor"],
            }
            config_path = root / "costs.yaml"
            config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
            validation_dir = processed / "validation"
            validation_dir.mkdir()
            published_outputs = {
                "cost_surface_100m.tif": b"published surface",
                "cost_class_mask_100m.tif": b"published class mask",
                "cost_surface_class_statistics.csv": b"published statistics",
                "cost_surface_metadata.json": b"published metadata",
            }
            for filename, content in published_outputs.items():
                (processed / filename).write_bytes(content)
            cost_path = validation_dir / "cost_surface_100m.tif"
            with (
                chdir(root),
                patch("src.cost_surface.PROCESSED", processed),
                patch("src.cost_surface.ROOT", root),
            ):
                build_cost_surface(
                    Path("costs.yaml"),
                    Path(
                        "processed/validation/cost_surface_100m.tif"
                    ),
                    ["123"],
                )

            metadata = json.loads(
                (validation_dir / "cost_surface_metadata.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                Path(metadata["statistics_csv"]).as_posix(),
                "processed/validation/cost_surface_class_statistics.csv",
            )
            self.assertEqual(
                Path(metadata["class_mask_raster"]).as_posix(),
                "processed/validation/cost_class_mask_100m.tif",
            )
            self.assertEqual(
                metadata["effective_config_sha256"],
                config_fingerprint(load_config(config_path)),
            )

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
                protected_row, protected_col = rowcol(
                    cost_raster.transform, 500_650, 6_200_650
                )
                self.assertEqual(float(costs[protected_row, protected_col]), -9999)
                nearby_barrier_row, nearby_barrier_col = rowcol(
                    cost_raster.transform, 500_550, 6_200_250
                )
                self.assertEqual(
                    float(costs[nearby_barrier_row, nearby_barrier_col]),
                    -9999,
                )
                sea_row, sea_col = rowcol(
                    cost_raster.transform, 500_750, 6_200_750
                )
                self.assertAlmostEqual(float(costs[sea_row, sea_col]), 0.4)
            with rasterio.open(
                validation_dir / "cost_class_mask_100m.tif"
            ) as class_raster:
                class_mask = class_raster.read(1)
                self.assertEqual(class_raster.dtypes[0], "uint32")
                self.assertTrue(np.any(class_mask & bits["forest"]))
                self.assertTrue(np.any(class_mask & bits["dwelling_proximity"]))
                self.assertTrue(np.any(class_mask & bits["parallel_corridor"]))
                self.assertTrue(
                    np.any(class_mask & np.uint32(524_288))
                )
                self.assertEqual(
                    int(
                        class_mask[
                            nearby_barrier_row, nearby_barrier_col
                        ]
                        & bits["dwelling_proximity"]
                    ),
                    0,
                )
                self.assertTrue(
                    np.any(class_mask & bits["marine_cable_corridor"])
                )
            for filename, content in published_outputs.items():
                self.assertEqual((processed / filename).read_bytes(), content)
            metadata = json.loads(
                (validation_dir / "cost_surface_metadata.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(metadata["excluded_parallel_asset_osm_ids"], ["123"])
            self.assertEqual(
                metadata["discount_classes"], ["marine_cable_corridor"]
            )


class ExcludedOsmIdTests(unittest.TestCase):
    def test_loads_all_ten_baltic_pipe_validation_ids(self) -> None:
        path = (
            Path(__file__).resolve().parents[1]
            / "validation"
            / "baltic_pipe_osm.geojson"
        )
        expected = sorted(
            [
                "1055346860",
                "1362960758",
                "1392067292",
                "1204845861",
                "1095495854",
                "1392191334",
                "1392191336",
                "1392191338",
                "1055345076",
                "1192369246",
            ]
        )

        self.assertEqual(load_excluded_osm_ids(path), expected)

    def test_loads_and_normalizes_ids_from_validation_geojson(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "osm_ids.geojson"
            gpd.GeoDataFrame(
                {"osm_ids": ["way/101,way/202"]},
                geometry=[LineString([(0, 0), (1, 1)])],
                crs="EPSG:4326",
            ).to_file(path, driver="GeoJSON", index=False)

            self.assertEqual(load_excluded_osm_ids(path), ["101", "202"])

    def test_rasterization_excludes_only_matching_osm_way_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "assets.gpkg"
            gpd.GeoDataFrame(
                {"osm_id": [101, 202]},
                geometry=[
                    LineString([(0.5, 0.1), (0.5, 3.9)]),
                    LineString([(2.5, 0.1), (2.5, 3.9)]),
                ],
                crs="EPSG:25832",
            ).to_file(path, layer="pipelines", driver="GPKG", index=False)

            mask = rasterize_layer(
                path,
                "pipelines",
                from_origin(0, 4, 1, 1),
                4,
                4,
                True,
                "EPSG:25832",
                ["101"],
            )

        self.assertEqual(int(mask[:, 0].sum()), 0)
        self.assertGreater(int(mask[:, 2].sum()), 0)


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
