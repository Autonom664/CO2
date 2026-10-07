import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import geopandas as gpd
import numpy as np
import rasterio
import yaml
from PIL import Image
from rasterio.transform import from_origin
from shapely.geometry import LineString, Point

from src import build_web


CLASS_BITS = {
    name: 1 << index
    for index, name in enumerate(build_web.LAYER_PRESENTATION)
}
CONFIG = {
    "grid": {"resolution_m": 100},
    "web": {"display_resolution_m": 250, "route_simplify_m": 25},
    "barriers": ["building_barrier"],
    "costs": {
        "open_land": 1,
        "natura2000": 9,
        "protected_nature": 8,
        "population": {"minimum": 1, "maximum": 10},
    },
    "layers": {
        "natura2000_birds": {"cost": "natura2000", "class_bit": "natura2000_birds"},
        "protected_reserves": {
            "cost": "protected_nature",
            "class_bit": "protected_reserves",
        },
    },
    "class_bits": CLASS_BITS,
}


def write_rasters(processed: Path) -> None:
    profile = {
        "driver": "GTiff",
        "width": 20,
        "height": 10,
        "count": 1,
        "crs": "EPSG:25832",
        "transform": from_origin(500_000, 6_200_000, 100, 100),
    }
    with rasterio.open(
        processed / "cost_surface_100m.tif",
        "w",
        **(profile | {"dtype": "float32", "nodata": -9999}),
    ) as dataset:
        dataset.write(np.ones((10, 20), dtype=np.float32), 1)
    classes = np.full((10, 20), CLASS_BITS["open_land"], dtype=np.uint16)
    classes[:, 10:] = CLASS_BITS["open_sea"]
    with rasterio.open(
        processed / "cost_class_mask_100m.tif",
        "w",
        **(profile | {"dtype": "uint16", "nodata": 0}),
    ) as dataset:
        dataset.write(classes, 1)
        dataset.update_tags(class_bits=json.dumps(CLASS_BITS))


def write_route_outputs(processed: Path) -> None:
    zigzag = LineString(
        [(500_050 + i * 100, 6_199_050 + (i % 2) * 5) for i in range(19)]
    )
    properties = {
        "from_id": "src",
        "from_name": "Source",
        "to_id": "sink",
        "to_name": "Sink",
        "length_km": 1.8,
        "accumulated_cost": 7.2,
        "km_open_sea": 0.9,
    }
    for name in ("routes.geojson", "minimum_spanning_network.geojson"):
        gpd.GeoDataFrame(
            [properties], geometry=[zigzag], crs="EPSG:25832"
        ).to_crs("EPSG:4326").to_file(processed / name, driver="GeoJSON")
    gpd.GeoDataFrame(
        {"id": ["src", "sink"], "role": ["source", "storage"]},
        geometry=[Point(9.0, 55.9), Point(9.1, 55.9)],
        crs="EPSG:4326",
    ).to_file(processed / "hotspots.geojson", driver="GeoJSON")


class WebFixture(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)
        self.processed = self.root / "data" / "processed"
        self.processed.mkdir(parents=True)
        (self.root / "data" / "input").mkdir()
        (self.root / "src").mkdir()
        (self.root / "src" / "routing.py").write_text("", encoding="utf-8")
        self.config = self.root / "costs.yaml"
        self.config.write_text(yaml.safe_dump(CONFIG), encoding="utf-8")
        write_rasters(self.processed)
        self.output = self.root / "web"
        self._patches = [
            patch.object(build_web, "PROCESSED", self.processed),
            patch.object(build_web, "ROOT", self.root),
            patch.object(build_web, "CONFIG", self.config),
        ]
        for active in self._patches:
            active.start()

    def tearDown(self) -> None:
        for active in self._patches:
            active.stop()
        self._temporary.cleanup()

    def add_hotspots_and_routes(self) -> None:
        (self.root / "data" / "input" / "hotspots.csv").write_text(
            "id,name,lon,lat,role\n", encoding="utf-8"
        )
        # Route outputs must be newer than every routing input.
        past = time.time() - 60
        for path in (
            self.root / "data" / "input" / "hotspots.csv",
            self.processed / "cost_surface_100m.tif",
            self.processed / "cost_class_mask_100m.tif",
            self.config,
            self.root / "src" / "routing.py",
        ):
            os.utime(path, (past, past))
        write_route_outputs(self.processed)

    def build(self) -> dict:
        build_web.build_web(
            self.processed / "cost_surface_100m.tif", self.output, self.config
        )
        return json.loads(
            (self.output / "data" / "map.json").read_text(encoding="utf-8")
        )


class ScoreLabelTests(unittest.TestCase):
    def test_direct_mapped_barrier_and_range_scores(self) -> None:
        self.assertEqual(build_web.class_score_label(CONFIG, "open_land"), "1")
        self.assertEqual(
            build_web.class_score_label(CONFIG, "natura2000_birds"), "9"
        )
        self.assertEqual(
            build_web.class_score_label(CONFIG, "protected_reserves"), "8"
        )
        self.assertEqual(
            build_web.class_score_label(CONFIG, "building_barrier"), "barrier"
        )
        self.assertEqual(build_web.class_score_label(CONFIG, "population"), "1–10")
        self.assertEqual(build_web.class_score_label(CONFIG, "lake"), "")


class DisplayGridTests(unittest.TestCase):
    def test_grid_is_snapped_and_covers_source_bounds(self) -> None:
        bounds = (500_000, 6_199_000, 502_000, 6_200_000)
        transform, width, height = build_web.make_display_grid(
            bounds, "EPSG:25832", 250
        )
        self.assertEqual(transform.a, 250)
        self.assertEqual(transform.e, -250)
        self.assertEqual(transform.c % 250, 0)
        self.assertEqual(transform.f % 250, 0)
        left, bottom, right, top = rasterio.warp.transform_bounds(
            "EPSG:25832", "EPSG:3857", *bounds
        )
        self.assertLessEqual(transform.c, left)
        self.assertGreaterEqual(transform.f, top)
        self.assertGreaterEqual(transform.c + width * 250, right)
        self.assertGreaterEqual(-(transform.f - height * 250), -bottom)


class PublishLinesTests(unittest.TestCase):
    def test_simplifies_geometry_and_keeps_attributes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            write_route_outputs(directory)
            output = directory / "published.geojson"
            build_web.publish_lines(directory / "routes.geojson", output, 25)
            published = json.loads(output.read_text(encoding="utf-8"))
            feature = published["features"][0]
            coordinates = feature["geometry"]["coordinates"]
            self.assertLess(len(coordinates), 19)
            self.assertEqual(feature["properties"]["km_open_sea"], 0.9)
            self.assertEqual(feature["properties"]["from_id"], "src")
            for lon, lat in coordinates:
                self.assertLessEqual(len(repr(lon).split(".")[-1]), 6)
                self.assertLessEqual(len(repr(lat).split(".")[-1]), 6)

    def test_zero_tolerance_keeps_every_vertex(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            write_route_outputs(directory)
            output = directory / "published.geojson"
            build_web.publish_lines(directory / "routes.geojson", output, 0)
            published = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(
                len(published["features"][0]["geometry"]["coordinates"]), 19
            )


class RouteManifestTests(WebFixture):
    def test_routes_absent_without_hotspot_input(self) -> None:
        manifest = self.build()
        self.assertFalse(manifest["routes_available"])
        self.assertEqual(manifest["route_layers"], [])
        self.assertIn("hotspots.csv", manifest["route_status"])
        self.assertFalse((self.output / "data" / "routes.geojson").exists())

    def test_routes_absent_when_outputs_missing(self) -> None:
        (self.root / "data" / "input" / "hotspots.csv").write_text(
            "id,name,lon,lat,role\n", encoding="utf-8"
        )
        manifest = self.build()
        self.assertFalse(manifest["routes_available"])
        self.assertIn("routes.geojson", manifest["route_status"])

    def test_stale_routes_are_not_published(self) -> None:
        self.add_hotspots_and_routes()
        future = time.time() + 60
        os.utime(self.config, (future, future))
        manifest = self.build()
        self.assertFalse(manifest["routes_available"])
        self.assertIn("older", manifest["route_status"])

    def test_current_routes_are_published_with_scores(self) -> None:
        self.add_hotspots_and_routes()
        manifest = self.build()
        self.assertTrue(manifest["routes_available"])
        self.assertEqual(
            [layer["id"] for layer in manifest["route_layers"]],
            ["hotspots", "routes", "minimum_spanning_network"],
        )
        for layer in manifest["route_layers"]:
            self.assertTrue((self.output / layer["url"]).exists())
        routes = json.loads(
            (self.output / "data" / "routes.geojson").read_text(encoding="utf-8")
        )
        self.assertLess(len(routes["features"][0]["geometry"]["coordinates"]), 19)
        scores = {layer["id"]: layer["score"] for layer in manifest["layers"]}
        self.assertEqual(scores["open_land"], "1")
        self.assertEqual(scores["building_barrier"], "barrier")

    def test_every_overlay_shares_the_display_grid(self) -> None:
        manifest = self.build()
        sizes = set()
        for path in [manifest["cost_image"]] + [
            layer["url"] for layer in manifest["layers"]
        ]:
            with Image.open(self.output / path) as image:
                sizes.add(image.size)
        self.assertEqual(len(sizes), 1)
        with Image.open(self.output / "data/layers/open_sea.png") as image:
            alpha = np.asarray(image)[..., 3]
        # Sea occupies the eastern half of the synthetic grid.
        columns = np.nonzero(alpha.any(axis=0))[0]
        self.assertGreater(columns.min(), 0)
        self.assertEqual(columns.max(), alpha.shape[1] - 1)


if __name__ == "__main__":
    unittest.main()
