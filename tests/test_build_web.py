import json
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch

import numpy as np
import rasterio
import yaml
from PIL import Image
from pyproj import Transformer
from rasterio.transform import from_origin

from src import build_web


class BuildWebTests(unittest.TestCase):
    def test_builds_static_assets_from_aligned_small_rasters(self) -> None:
        class_bits = {
            name: 1 << index
            for index, name in enumerate(build_web.LAYER_PRESENTATION)
        }
        # P12 adds classes above bit 31, so the mask is uint64.
        class_bits["road_major"] = 1 << 40
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            processed = root / "processed"
            output = root / "web"
            processed.mkdir()
            transform = from_origin(500_000, 6_200_000, 100, 100)
            profile = {
                "driver": "GTiff",
                "width": 10,
                "height": 10,
                "count": 1,
                "crs": "EPSG:25832",
                "transform": transform,
                "tiled": True,
            }
            cost = np.ones((10, 10), dtype=np.float32)
            cost[0, 0] = -9999
            with rasterio.open(
                processed / "cost_surface_100m.tif",
                "w",
                **(profile | {"dtype": "float32", "nodata": -9999}),
            ) as dataset:
                dataset.write(cost, 1)
            classes = np.full((10, 10), class_bits["open_land"], dtype=np.uint64)
            classes[4:6, 4:6] |= class_bits["road_major"]
            with rasterio.open(
                processed / "cost_class_mask_100m.tif",
                "w",
                **(profile | {"dtype": "uint64", "nodata": 0}),
            ) as dataset:
                dataset.write(classes, 1)
                dataset.update_tags(class_bits=json.dumps(class_bits))
            config = root / "costs.yaml"
            config.write_text(
                yaml.safe_dump(
                    {
                        "grid": {"resolution_m": 100},
                        "web": {"display_resolution_m": 250},
                        "class_bits": class_bits,
                    }
                ),
                encoding="utf-8",
            )
            sources = root / "SOURCES.md"
            sources.write_text("# Test source register\n", encoding="utf-8")
            with (
                patch.object(build_web, "PROCESSED", processed),
                patch.object(build_web, "ROOT", root),
                patch.object(build_web, "CONFIG", config),
            ):
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always")
                    result = build_web.build_web(
                        processed / "cost_surface_100m.tif",
                        output,
                        config,
                    )
                self.assertFalse(
                    any(
                        "invalid value encountered in cast" in str(w.message)
                        for w in caught
                    )
                )

            manifest = json.loads(
                (result / "data" / "map.json").read_text(encoding="utf-8")
            )
            self.assertFalse(manifest["routes_available"])
            self.assertEqual(manifest["display_resolution_m"], 250)
            self.assertTrue((result / "data" / "layers" / "cost_surface_t0_0.png").exists())
            self.assertTrue((result / "data" / "layers" / "road_major_t0_0.png").exists())
            self.assertEqual(manifest["display_crs"], "EPSG:3857")
            image_paths = list((result / "data" / "layers").glob("*.png"))
            with Image.open(image_paths[0]) as reference:
                display_size = reference.size
            for image_path in image_paths:
                with Image.open(image_path) as image:
                    self.assertEqual(image.size, display_size)

            to_mercator = Transformer.from_crs(
                "EPSG:4326", "EPSG:3857", always_xy=True
            )
            projected_corners = [
                to_mercator.transform(*corner) for corner in manifest["bounds"]
            ]
            self.assertAlmostEqual(projected_corners[0][0], projected_corners[3][0])
            self.assertAlmostEqual(projected_corners[1][0], projected_corners[2][0])
            self.assertAlmostEqual(projected_corners[0][1], projected_corners[1][1])
            self.assertAlmostEqual(projected_corners[2][1], projected_corners[3][1])


if __name__ == "__main__":
    unittest.main()
