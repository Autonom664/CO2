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
from pyproj import Transformer
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
        "dwelling_proximity": {"enabled": True, "max_distance_m": 200, "max_score": 6},
    },
    "layers": {
        "natura2000_birds": {"cost": "natura2000", "class_bit": "natura2000_birds"},
        "protected_reserves": {
            "cost": "protected_nature",
            "class_bit": "protected_reserves",
        },
    },
    "parallel_corridor": {"factor": 0.8},
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
    classes = np.full((10, 20), CLASS_BITS["open_land"], dtype=np.uint32)
    classes[:, 10:] = CLASS_BITS["open_sea"]
    with rasterio.open(
        processed / "cost_class_mask_100m.tif",
        "w",
        **(profile | {"dtype": "uint32", "nodata": 0}),
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
        {
            "id": ["src", "sink"],
            "role": ["source", "storage"],
            "ets_verified_2024_t": [1_436_067, None],
            "planned_capture_tpa": [1_250_000, None],
            "capture_basis": ["DEA CCS contract", ""],
        },
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
        self.assertEqual(
            build_web.class_score_label(CONFIG, "dwelling_proximity"), "0–6"
        )
        self.assertEqual(
            build_web.class_score_label(CONFIG, "parallel_corridor"), "×0.8"
        )
        multi = {
            "costs": {"osd": 4, "od": 2, "cable": 1},
            "layers": {
                "a": {"class_bit": "drinking_water", "cost": "osd"},
                "b": {"class_bit": "drinking_water", "cost": "od"},
                "c": {"class_bit": "marine_cable_corridor", "cost": "cable"},
            },
            "discount_classes": ["marine_cable_corridor"],
        }
        self.assertEqual(build_web.class_score_label(multi, "drinking_water"), "2–4")
        self.assertEqual(build_web.class_score_label(multi, "marine_cable_corridor"), "−1")


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
        hotspots = json.loads(
            (self.output / "data" / "hotspots.geojson").read_text(encoding="utf-8")
        )
        source = hotspots["features"][0]["properties"]
        self.assertEqual(source["ets_verified_2024_t"], 1_436_067)
        self.assertEqual(source["planned_capture_tpa"], 1_250_000)
        self.assertEqual(source["capture_basis"], "DEA CCS contract")
        scores = {layer["id"]: layer["score"] for layer in manifest["layers"]}
        self.assertEqual(scores["open_land"], "1")
        self.assertEqual(scores["building_barrier"], "barrier")

    def test_fifteen_hotspots_with_blank_optional_fields_are_preserved(self) -> None:
        self.add_hotspots_and_routes()
        roles = ["source"] * 8 + ["storage"] * 7
        frame = gpd.GeoDataFrame(
            {
                "id": [f"h{index}" for index in range(15)],
                "role": roles,
                "ets_installation_id": ["342"] + [""] * 14,
                "ets_verified_2024_t": [1_436_067] + [None] * 14,
                "planned_capture_tpa": [1_250_000] + [None] * 14,
                "capture_basis": ["DEA CCS contract"] + [""] * 14,
                "capture_source_url": ["https://ens.dk/"] + [""] * 14,
            },
            geometry=[Point(9.0 + index / 10, 55.9) for index in range(15)],
            crs="EPSG:4326",
        )
        (self.processed / "hotspots.geojson").unlink()
        frame.to_file(self.processed / "hotspots.geojson", driver="GeoJSON")
        source = json.loads(
            (self.processed / "hotspots.geojson").read_text(encoding="utf-8")
        )
        manifest = self.build()
        self.assertTrue(manifest["routes_available"])
        published = json.loads(
            (self.output / "data" / "hotspots.geojson").read_text(encoding="utf-8")
        )
        self.assertEqual(len(published["features"]), 15)
        self.assertEqual(
            [feature["properties"] for feature in published["features"]],
            [feature["properties"] for feature in source["features"]],
        )
        self.assertEqual(
            sum(f["properties"]["role"] == "storage" for f in published["features"]),
            7,
        )
        blank = published["features"][1]["properties"]
        self.assertIsNone(blank["ets_verified_2024_t"])
        self.assertEqual(blank["capture_basis"], "")

    def test_corridors_are_listed_only_when_current(self) -> None:
        self.add_hotspots_and_routes()
        corridors = self.output / "data" / "corridors.geojson"
        corridors.parent.mkdir(parents=True)
        corridors.write_text('{"type": "FeatureCollection", "features": []}')
        past = time.time() - 30
        os.utime(corridors, (past, past))
        stale = self.build()
        self.assertNotIn("corridors", [l["id"] for l in stale["route_layers"]])
        os.utime(corridors, None)
        current = self.build()
        self.assertIn("corridors", [l["id"] for l in current["route_layers"]])

    def test_every_overlay_shares_the_display_grid(self) -> None:
        manifest = self.build()
        sizes = set()
        tiles = manifest["cost_tiles"] + [
            tile for layer in manifest["layers"] for tile in layer["tiles"]
        ]
        for tile in tiles:
            self.assertEqual(tile["bounds"], manifest["bounds"])
            with Image.open(self.output / tile["url"]) as image:
                sizes.add(image.size)
        self.assertEqual(len(sizes), 1)
        sea = next(layer for layer in manifest["layers"] if layer["id"] == "open_sea")
        with Image.open(self.output / sea["tiles"][0]["url"]) as image:
            alpha = np.asarray(image)[..., 3]
        # Sea occupies the eastern half of the synthetic grid.
        columns = np.nonzero(alpha.any(axis=0))[0]
        self.assertGreater(columns.min(), 0)
        self.assertEqual(columns.max(), alpha.shape[1] - 1)
        # Empty layers publish no tiles at all.
        empty = next(layer for layer in manifest["layers"] if layer["id"] == "lake")
        self.assertEqual(empty["tiles"], [])


class TileTests(unittest.TestCase):
    def test_large_image_is_split_within_limit_and_tiles_abut(self) -> None:
        pixels = np.zeros((600, 1000, 4), dtype=np.uint8)
        pixels[..., 3] = 200
        pixels[:300, :500, 3] = 0  # top-left quarter empty
        transform = from_origin(1_000_000, 7_500_000, 250, 250)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "layer.png").write_bytes(b"stale")
            tiles = build_web.write_tiles(
                pixels, transform, "EPSG:3857", "layer", directory, 256
            )
            self.assertFalse((directory / "layer.png").exists())
            files = sorted(directory.glob("layer_t*.png"))
            self.assertEqual(len(files), len(tiles))
            for path in files:
                with Image.open(path) as image:
                    self.assertLessEqual(max(image.size), 256)
        # 3 rows of 200 px × 4 columns of 250 px. The empty block (rows
        # 0–300, columns 0–500) fully covers only the first two tiles of row 0.
        self.assertEqual(len(tiles), 12 - 2)
        to_mercator = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
        by_name = {t["url"].rsplit("/", 1)[-1]: t["bounds"] for t in tiles}
        left = [to_mercator.transform(*c) for c in by_name["layer_t2_0.png"]]
        right = [to_mercator.transform(*c) for c in by_name["layer_t2_1.png"]]
        self.assertAlmostEqual(left[1][0], right[0][0], places=3)
        self.assertAlmostEqual(left[1][0], 1_000_000 + 250 * 250, places=3)

if __name__ == "__main__":
    unittest.main()
