import gzip
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from rasterio.transform import from_origin

from src.cost_surface import landfall_cells
from src.export_model import (
    _aggregate_layer_mask,
    _aligned_window_grid,
    _resample_any,
    _resample_average,
    _set_presence_bit,
    _write_gzip_array,
    _write_json,
)
from validation.model_parity import (
    build_cost_surface,
    compare_cost_arrays,
    compare_route_references,
    load_model_pack,
)


class ModelPackEncodingTests(unittest.TestCase):
    def test_bbox_grid_window_expands_and_snaps_to_resolution(self):
        transform, width, height, bounds = _aligned_window_grid(
            (0, 0, 1000, 1000),
            250,
            (120, 100, 610, 700),
        )

        self.assertEqual((width, height), (3, 3))
        self.assertEqual(bounds, (0, 0, 750, 750))
        self.assertEqual(transform.to_gdal(), (0, 250, 0, 750, 0, -250))
        with self.assertRaisesRegex(ValueError, "does not overlap"):
            _aligned_window_grid((0, 0, 1000, 1000), 250, (1200, 0, 1400, 200))

    def test_mask_resampling_preserves_zero_cells(self):
        transform = from_origin(0, 200, 100, 100)
        source = np.array([[True, False], [False, False]])

        np.testing.assert_array_equal(
            _resample_any(source, transform, (2, 2), transform, "EPSG:25832"),
            source,
        )
        np.testing.assert_array_equal(
            _resample_average(
                source, transform, (2, 2), transform, "EPSG:25832"
            ),
            source.astype(np.float32),
        )
        zeros = np.zeros((2, 2), dtype=bool)
        np.testing.assert_array_equal(
            _resample_any(zeros, transform, (2, 2), transform, "EPSG:25832"),
            zeros,
        )
        np.testing.assert_array_equal(
            _resample_average(zeros, transform, (2, 2), transform, "EPSG:25832"),
            zeros.astype(np.float32),
        )

    def test_landfall_connectivity_is_explicit(self):
        land = np.array([[False, False], [True, False]])
        sea = np.array([[False, True], [False, False]])
        extent = np.ones((2, 2), dtype=bool)

        self.assertTrue(landfall_cells(land, sea, extent, 8)[1, 0])
        self.assertFalse(landfall_cells(land, sea, extent, 4)[1, 0])

    def test_bitplanes_encode_low_and_high_layer_indices(self):
        presence = np.zeros((2, 1, 3), dtype="<u4")
        mask = np.array([[True, False, True]])

        _set_presence_bit(presence, mask, 0)
        _set_presence_bit(presence, mask, 31)
        _set_presence_bit(presence, mask, 32)
        _set_presence_bit(presence, mask, 39)

        self.assertEqual(int(presence[0, 0, 0]), (1 << 0) | (1 << 31))
        self.assertEqual(int(presence[1, 0, 0]), (1 << 0) | (1 << 7))
        self.assertEqual(int(presence[0, 0, 1]), 0)
        self.assertEqual(int(presence[1, 0, 1]), 0)

    def test_area_uses_half_coverage_threshold_and_linear_uses_any_hit(self):
        source_transform = from_origin(0, 200, 100, 100)
        target_transform = from_origin(0, 200, 200, 200)
        source = np.array([[1, 1], [0, 0]], dtype=bool)

        area = _aggregate_layer_mask(
            source,
            "polygon",
            source_transform,
            (1, 1),
            target_transform,
            "EPSG:25832",
            0.5,
        )
        linear = _aggregate_layer_mask(
            source,
            "linear",
            source_transform,
            (1, 1),
            target_transform,
            "EPSG:25832",
            0.5,
        )

        np.testing.assert_array_equal(area, [[True]])
        np.testing.assert_array_equal(linear, [[True]])
        source[0, 1] = False
        area_below_threshold = _aggregate_layer_mask(
            source,
            "polygon",
            source_transform,
            (1, 1),
            target_transform,
            "EPSG:25832",
            0.5,
        )
        linear_any_hit = _aggregate_layer_mask(
            source,
            "linear",
            source_transform,
            (1, 1),
            target_transform,
            "EPSG:25832",
            0.5,
        )
        np.testing.assert_array_equal(area_below_threshold, [[False]])
        np.testing.assert_array_equal(linear_any_hit, [[True]])

    def test_gzip_array_is_little_endian_row_major_with_integrity_metadata(self):
        array = np.array([[1, 256], [65535, 42]], dtype=np.uint16)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "values.bin.gz"
            metadata = _write_gzip_array(output, array)
            payload = gzip.decompress(output.read_bytes())

        self.assertEqual(metadata["dtype"], "uint16")
        self.assertEqual(metadata["shape"], [2, 2])
        self.assertEqual(metadata["byte_order"], "little")
        self.assertEqual(metadata["order"], "C-row-major")
        self.assertEqual(metadata["compression"], "gzip")
        self.assertEqual(metadata["sha256"], hashlib.sha256(payload).hexdigest())
        np.testing.assert_array_equal(
            np.frombuffer(payload, dtype="<u2").reshape((2, 2)), array
        )

    def test_loader_checks_manifest_hashes_and_unpacks_both_planes(self):
        with tempfile.TemporaryDirectory() as directory:
            model_dir = Path(directory)
            presence_lo = np.zeros((2, 3), dtype="<u4")
            presence_hi = np.zeros((2, 3), dtype="<u4")
            presence_lo[0, 0] = 1
            presence_lo[0, 1] = 2
            presence_hi[1, 2] = 8
            files = [
                _write_gzip_array(model_dir / "presence_lo.bin.gz", presence_lo),
                _write_gzip_array(model_dir / "presence_hi.bin.gz", presence_hi),
            ]
            descriptors = {}
            for name, array in {
                "buildings_share": np.zeros((2, 3), dtype=np.uint8),
                "building_distance": np.full((2, 3), 65535, dtype=np.uint16),
                "population": np.zeros((2, 3), dtype=np.float32),
                "population_1km": np.zeros((2, 3), dtype=np.float32),
                "parallel": np.zeros((2, 3), dtype=np.uint8),
                "landfall": np.zeros((2, 3), dtype=np.uint8),
            }.items():
                filename = f"{name}.bin.gz"
                files.append(_write_gzip_array(model_dir / filename, array))
                descriptors[name] = {"file": filename}
            grid = {
                "width": 3,
                "height": 2,
                "resolution_m": 250,
                "cost_reference_resolution_m": 250,
                "crs": "EPSG:25832",
                "transform_gdal": [0, 250, 0, 500, 0, -250],
            }
            layers = {
                "layers": [
                    {"name": "roads", "bit": 0, "available": True, "cost": "road"}
                ],
                "derived": [
                    {"name": "land", "bit": 1},
                    {"name": "sea", "bit": 2},
                    {"name": "buildings", "bit": 3},
                    {"name": "landfall", "bit": 4},
                    {"name": "parallel_band", "bit": 35},
                ],
                "continuous": descriptors,
            }
            json_files = [
                _write_json(model_dir / "grid.json", grid),
                _write_json(model_dir / "layers.json", layers),
                _write_json(model_dir / "config.json", {}),
            ]
            (model_dir / "manifest.json").write_text(
                json.dumps({"files": files + json_files}), encoding="utf-8"
            )

            model = load_model_pack(model_dir)
            self.assertTrue(model["layer_masks"]["roads"][0, 0])
            self.assertTrue(model["derived_masks"]["land"][0, 1])
            self.assertTrue(model["derived_masks"]["parallel_band"][1, 2])

            with (model_dir / "presence_lo.bin.gz").open("ab") as stream:
                stream.write(b"corrupt")
            with self.assertRaisesRegex(ValueError, "Compressed SHA-256"):
                load_model_pack(model_dir)

    def test_reference_formula_applies_barriers_and_max_groups(self):
        shape = (3, 3)
        forest = np.zeros(shape, dtype=bool)
        forest[1, 0] = True
        forest[1, 1] = True
        nature = np.zeros(shape, dtype=bool)
        nature[1, 1] = True
        nature[1, 2] = True
        protected_barrier = np.zeros(shape, dtype=bool)
        protected_barrier[0, 1] = True
        landfall = np.zeros(shape, dtype=bool)
        landfall[2, 2] = True
        landfall[2, 0] = True
        land = np.ones(shape, dtype=bool)
        sea = np.zeros(shape, dtype=bool)
        sea[2, 0] = True
        land[2, 0] = False

        model = {
            "grid": {
                "resolution_m": 250,
                "cost_reference_resolution_m": 250,
                "building_barrier_share_threshold": 128,
                "distance_nodata": 65535,
            },
            "config": {
                "costs": {
                    "open_land": 1,
                    "open_sea": 2,
                    "building_barrier": 10,
                    "forest": 4,
                    "protected_nature": 6,
                    "protected_barrier": 10,
                    "landfall": 3,
                    "dwelling_proximity": {"enabled": False},
                    "population": {
                        "enabled": False,
                        "enabled": False,
                        "minimum": 0,
                        "maximum": 1,
                    },
                    "population_risk": {"enabled": False},
                },
                "score_minimum": 0,
                "barriers": ["building_barrier", "protected_barrier"],
                "layers": {
                    "forest": {"cost": "forest"},
                    "protected_nature": {"cost": "protected_nature"},
                    "protected_barrier": {"cost": "protected_barrier"},
                },
                "combine_groups": {
                    "nature_group": {
                        "members": ["forest", "protected_nature"],
                        "rule": "max",
                    },
                    "empty_dynamic_group": {
                        "members": ["population", "dwelling_proximity"],
                        "rule": "max",
                    },
                },
                "discount_classes": [],
                "landfall": {"enabled": True, "cost": "landfall"},
                "parallel_corridor": {"enabled": False},
            },
            "layers": {
                "layers": [
                    {
                        "name": "forest",
                        "cost": "forest",
                        "available": True,
                    },
                    {
                        "name": "protected_nature",
                        "cost": "protected_nature",
                        "available": True,
                    },
                    {
                        "name": "protected_barrier",
                        "cost": "protected_barrier",
                        "available": True,
                    },
                ]
            },
            "layer_masks": {
                "forest": forest,
                "protected_nature": nature,
                "protected_barrier": protected_barrier,
            },
            "derived_masks": {
                "land": land,
                "sea": sea,
                "landfall": landfall,
                "parallel_band": np.zeros(shape, dtype=bool),
            },
            "arrays": {
                "buildings_share": np.zeros(shape, dtype=np.uint8),
                "building_distance": np.full(shape, 65535, dtype=np.uint16),
                "population": np.zeros(shape, dtype=np.float32),
                "population_1km": np.zeros(shape, dtype=np.float32),
            },
        }

        surface = build_cost_surface(model)

        self.assertTrue(np.isnan(surface[0, 1]))
        self.assertAlmostEqual(surface[1, 0], 5.0)
        self.assertAlmostEqual(surface[1, 1], 7.0)
        self.assertAlmostEqual(surface[1, 2], 7.0)
        self.assertAlmostEqual(surface[2, 2], 4.0)
        self.assertAlmostEqual(surface[2, 0], 2.0)

    def test_cost_grid_comparator_enforces_cellwise_relative_tolerance(self):
        expected = np.array([[1.0, 2.0], [np.nan, 4.0]], dtype=np.float32)
        within_tolerance = np.array(
            [[1.001, 2.0], [np.nan, 4.0]], dtype=np.float32
        )
        outside_tolerance = np.array(
            [[1.01, 2.0], [np.nan, 4.0]], dtype=np.float32
        )

        self.assertTrue(compare_cost_arrays(expected, within_tolerance)["passed"])
        self.assertFalse(compare_cost_arrays(expected, outside_tolerance)["passed"])
        mismatch = compare_cost_arrays(
            expected, np.array([[1.0, 2.0], [0.5, 4.0]], dtype=np.float32)
        )
        self.assertEqual(mismatch["validity_mismatch_cells"], 1)
        self.assertFalse(mismatch["passed"])

    def test_route_comparator_enforces_tolerance_and_pair_identity(self):
        expected = [{"from": "S1", "to": "T1", "accumulated_cost": 100.0}]
        within_tolerance = [
            {"from": "S1", "to": "T1", "accumulated_cost": 100.4}
        ]
        outside_tolerance = [
            {"from": "S1", "to": "T1", "accumulated_cost": 100.6}
        ]

        self.assertTrue(
            compare_route_references(expected, within_tolerance)["passed"]
        )
        self.assertFalse(
            compare_route_references(expected, outside_tolerance)["passed"]
        )
        missing = compare_route_references(expected, [])
        self.assertFalse(missing["passed"])
        self.assertEqual(missing["missing_routes"], [["S1", "T1"]])


if __name__ == "__main__":
    unittest.main()
