import csv
import io
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from email.message import Message
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

import geopandas as gpd
from pyproj import Transformer
from shapely import union_all
from shapely.geometry import Point, box

from src.acquire_data import (
    exclude_foreign_land_from_extent,
    download_wfs_source,
    extend_extent_to_offshore_storage,
    kml_polygon_geometries,
    osm_tag_value,
    prepare_coast_and_extent,
    sanitize_wfs_page,
    voltage_in_volts,
    wind_farm_category,
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

    def test_north_sea_extent_connects_nini_bifrost_and_inez_corridors(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            hotspots_path = Path(temporary) / "hotspots.csv"
            transformer = Transformer.from_crs(
                "EPSG:25832", "EPSG:4326", always_xy=True
            )
            nini = transformer.transform(520_000, 6_200_000)
            bifrost = transformer.transform(530_000, 6_200_000)
            with hotspots_path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.writer(stream)
                writer.writerow(["id", "role", "lon", "lat"])
                writer.writerow(["greensand_nini_west", "storage", *nini])
                writer.writerow(["bifrost_harald", "storage", *bifrost])
                writer.writerow(
                    [
                        "inez",
                        "storage",
                        *transformer.transform(540_000, 6_200_000),
                    ]
                )

            land = box(499_000, 6_199_000, 501_000, 6_201_000)
            expanded = extend_extent_to_offshore_storage(
                land.buffer(1_000), land, hotspots_path, 1_000
            )

            self.assertTrue(expanded.covers(Point(525_000, 6_200_000)))
            self.assertTrue(expanded.covers(Point(535_000, 6_200_000)))

    def test_reads_storage_polygon_from_dea_kmz(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            kmz_path = Path(temporary) / "thorning.kmz"
            kml = (
                b'<?xml version="1.0" encoding="UTF-8"?>'
                b'<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
                b"<Placemark><Polygon><outerBoundaryIs><LinearRing>"
                b"<coordinates>9,56 9.1,56 9.1,56.1 9,56.1 9,56</coordinates>"
                b"</LinearRing></outerBoundaryIs></Polygon></Placemark>"
                b"</Document></kml>"
            )
            with zipfile.ZipFile(kmz_path, "w") as archive:
                archive.writestr("doc.kml", kml)

            polygons = kml_polygon_geometries(kmz_path)

            self.assertEqual(len(polygons), 1)
            self.assertTrue(polygons[0].is_valid)
            self.assertAlmostEqual(polygons[0].area, 0.01)

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


class OsmInfrastructureParsingTests(unittest.TestCase):
    def test_reads_selected_hstore_tag(self) -> None:
        self.assertEqual(
            osm_tag_value(
                '"power"=>"line","voltage"=>"400000","name"=>"A"',
                "voltage",
            ),
            "400000",
        )

    def test_voltage_parser_filters_bad_low_voltage_tag(self) -> None:
        self.assertEqual(voltage_in_volts("132000;400000"), 400000)
        self.assertEqual(voltage_in_volts("132 kV"), 132000)
        self.assertEqual(voltage_in_volts("400"), 400)
        self.assertIsNone(voltage_in_volts("unknown"))
        self.assertIsNone(voltage_in_volts(None))

    def test_sanitizes_datafordeler_pagination_credentials(self) -> None:
        body = (
            b'<wfs:FeatureCollection xmlns:wfs="http://www.opengis.net/wfs/2.0" '
            b'numberReturned="0" '
            b'next="https://example.invalid/wfs?apikey=private-value" />'
        )

        sanitized, count = sanitize_wfs_page(body, "private-value")

        self.assertEqual(count, 0)
        self.assertNotIn(b"private-value", sanitized)
        self.assertNotIn(b"apikey", sanitized)

    def test_sanitizes_credentials_and_next_links_in_json_wfs_pages(self) -> None:
        api_key = "test-only-private-value"
        body = json.dumps(
            {
                "type": "FeatureCollection",
                "features": [],
                "next": f"https://example.invalid/wfs?apikey={api_key}",
                "links": [
                    {"rel": "next", "href": f"?apikey={api_key}"},
                    {"rel": "self", "href": "?page=1"},
                ],
            }
        ).encode("utf-8")

        sanitized, count = sanitize_wfs_page(body, api_key)
        payload = json.loads(sanitized)

        self.assertEqual(count, 0)
        self.assertNotIn(api_key.encode("utf-8"), sanitized)
        self.assertNotIn("next", payload)
        self.assertEqual(payload["links"], [{"rel": "self", "href": "?page=1"}])

    def test_classifies_known_wind_farm_statuses(self) -> None:
        self.assertEqual(wind_farm_category("Production"), "barrier")
        self.assertEqual(wind_farm_category("Approved"), "barrier")
        self.assertEqual(wind_farm_category("Planned"), "planned")
        with self.assertRaisesRegex(ValueError, "Unclassified"):
            wind_farm_category("Unmapped status")


class WfsDownloadTests(unittest.TestCase):
    @staticmethod
    def geojson_page(identifiers: list[int]) -> bytes:
        return json.dumps(
            {
                "type": "FeatureCollection",
                "crs": {
                    "type": "name",
                    "properties": {"name": "EPSG:25832"},
                },
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "Point",
                            "coordinates": [500_000 + index, 6_200_000],
                        },
                        "properties": {"id": identifier},
                    }
                    for index, identifier in enumerate(identifiers)
                ],
            }
        ).encode("utf-8")

    @staticmethod
    def gml_page(identifiers: list[int], matched: int) -> bytes:
        members = "".join(
            "<wfs:member><t:feature gml:id=\"feature.{identifier}\">"
            "<t:geom><gml:Point srsName=\"urn:ogc:def:crs:EPSG::25832\">"
            "<gml:pos>500000 6200000</gml:pos></gml:Point></t:geom>"
            "</t:feature></wfs:member>".format(identifier=identifier)
            for identifier in identifiers
        )
        body = (
            '<wfs:FeatureCollection xmlns:wfs="http://www.opengis.net/wfs/2.0" '
            'xmlns:gml="http://www.opengis.net/gml/3.2" xmlns:t="urn:test" '
            f'numberMatched="{matched}" '
            f'numberReturned="{len(identifiers)}">{members}'
            "</wfs:FeatureCollection>"
        )
        return body.encode("utf-8")

    def test_downloads_all_pages_using_start_index(self) -> None:
        pages = [
            self.geojson_page([1, 2]),
            self.geojson_page([3]),
        ]
        requests: list[str] = []

        def open_page(request, timeout):
            requests.append(request.full_url)
            return io.BytesIO(pages.pop(0))

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with (
                patch("src.acquire_data.ROOT", root),
                patch("src.acquire_data.RAW", root / "data" / "raw"),
                patch("src.acquire_data.WFS_PAGE_SIZE", 2),
                patch("src.acquire_data.urllib.request.urlopen", open_page),
            ):
                record = download_wfs_source(
                    "sample",
                    {
                        "endpoint": "https://example.invalid/wfs",
                        "typename": "sample:layer",
                        "crs": "EPSG:25832",
                        "title": "Sample layer",
                    },
                    False,
                )

            offsets = [
                parse_qs(urlsplit(url).query)["startIndex"][0]
                for url in requests
            ]
            self.assertEqual(offsets, ["0", "2"])
            self.assertIsNotNone(record)
            if record is None:
                self.fail("WFS download returned no manifest record")
            self.assertEqual(record["feature_count"], 3)
            self.assertEqual(record["page_count"], 2)
            self.assertTrue(
                (root / "data" / "raw" / "phase-b" / "sample" / "complete.json")
                .is_file()
            )

    def test_retries_auth_failure_and_saves_sanitized_gml(self) -> None:
        api_key = "test-only-private-value"
        response_body = (
            b'<wfs:FeatureCollection xmlns:wfs="http://www.opengis.net/wfs/2.0" '
            b'xmlns:gml="http://www.opengis.net/gml/3.2" '
            b'xmlns:t="urn:test" numberReturned="1" '
            b'next="https://example.invalid/wfs?apikey=test-only-private-value">'
            b'<wfs:member><t:feature gml:id="f.1"><t:geom>'
            b'<gml:Point srsName="urn:ogc:def:crs:EPSG::25832">'
            b'<gml:pos>500000 6200000</gml:pos></gml:Point>'
            b'</t:geom></t:feature></wfs:member></wfs:FeatureCollection>'
        )
        attempts = 0

        def open_page(request, timeout):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise HTTPError(
                    request.full_url, 401, "Unauthorized", Message(), None
                )
            return io.BytesIO(response_body)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with (
                patch("src.acquire_data.ROOT", root),
                patch("src.acquire_data.RAW", root / "data" / "raw"),
                patch("src.acquire_data.time.sleep"),
                patch("src.acquire_data.urllib.request.urlopen", open_page),
            ):
                record = download_wfs_source(
                    "authenticated_sample",
                    {
                        "endpoint": "https://example.invalid/wfs",
                        "typename": "sample:layer",
                        "crs": "EPSG:25832",
                        "title": "Sample authenticated layer",
                        "authenticated": True,
                    },
                    False,
                    api_key,
                )

            source_dir = root / "data" / "raw" / "phase-b" / "authenticated_sample"
            saved_page = (source_dir / "page_00000.gml").read_bytes()
            marker = (source_dir / "complete.json").read_text(encoding="utf-8")
            self.assertEqual(attempts, 2)
            self.assertIsNotNone(record)
            if record is None:
                self.fail("WFS download returned no manifest record")
            self.assertEqual(record["feature_count"], 1)
            self.assertNotIn(api_key.encode("utf-8"), saved_page)
            self.assertNotIn(b"next=", saved_page)
            self.assertNotIn(api_key, marker)

    def test_retries_transient_authenticated_http_400(self) -> None:
        response_body = self.gml_page([1], matched=1)
        attempts = 0
        sleeps: list[int] = []

        def open_page(request, timeout):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise HTTPError(
                    request.full_url, 400, "Bad Request", Message(), None
                )
            return io.BytesIO(response_body)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with (
                patch("src.acquire_data.ROOT", root),
                patch("src.acquire_data.RAW", root / "data" / "raw"),
                patch("src.acquire_data.WFS_PAGE_SIZE", 2),
                patch(
                    "src.acquire_data.time.sleep",
                    side_effect=lambda delay: sleeps.append(delay),
                ),
                patch("src.acquire_data.urllib.request.urlopen", open_page),
            ):
                record = download_wfs_source(
                    "authenticated_sample",
                    {
                        "endpoint": "https://example.invalid/wfs",
                        "typename": "sample:layer",
                        "crs": "EPSG:25832",
                        "title": "Sample authenticated layer",
                        "authenticated": True,
                    },
                    False,
                    "private-value",
                )

        self.assertIsNotNone(record)
        self.assertEqual(attempts, 2)
        self.assertEqual(sleeps, [2])
        if record is None:
            self.fail("WFS download returned no manifest record")
        self.assertEqual(record["feature_count"], 1)

    def test_splits_persistently_failing_authenticated_page(self) -> None:
        pages = {
            ("0", "1"): self.gml_page([1], matched=2),
            ("1", "1"): self.gml_page([2], matched=2),
            ("2", "2"): self.gml_page([], matched=2),
        }
        attempts: list[tuple[str, str]] = []
        sleep_calls: list[int] = []

        def open_page(request, timeout):
            query = parse_qs(urlsplit(request.full_url).query)
            key = (query["startIndex"][0], query["count"][0])
            attempts.append(key)
            if key == ("0", "2"):
                raise HTTPError(
                    request.full_url, 400, "Bad Request", Message(), None
                )
            return io.BytesIO(pages[key])

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with (
                patch("src.acquire_data.ROOT", root),
                patch("src.acquire_data.RAW", root / "data" / "raw"),
                patch("src.acquire_data.WFS_PAGE_SIZE", 2),
                patch(
                    "src.acquire_data.time.sleep",
                    side_effect=lambda delay: sleep_calls.append(delay),
                ),
                patch("src.acquire_data.urllib.request.urlopen", open_page),
            ):
                record = download_wfs_source(
                    "authenticated_sample",
                    {
                        "endpoint": "https://example.invalid/wfs",
                        "typename": "sample:layer",
                        "crs": "EPSG:25832",
                        "title": "Sample authenticated layer",
                        "authenticated": True,
                    },
                    False,
                    "private-value",
                )

        self.assertIsNotNone(record)
        self.assertEqual(attempts[:4], [("0", "2")] * 4)
        self.assertEqual(attempts[4:], [("0", "1"), ("1", "1"), ("2", "2")])
        self.assertEqual(sleep_calls, [2, 5, 10])
        if record is None:
            self.fail("WFS download returned no manifest record")
        self.assertEqual(record["feature_count"], 2)
        self.assertEqual(record["page_count"], 2)

    def test_deduplicates_gml_ids_and_checks_number_matched(self) -> None:
        pages = [
            self.gml_page([1, 2], matched=3),
            self.gml_page([2, 3], matched=3),
            self.gml_page([], matched=3),
        ]

        def open_page(request, timeout):
            return io.BytesIO(pages.pop(0))

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with (
                patch("src.acquire_data.ROOT", root),
                patch("src.acquire_data.RAW", root / "data" / "raw"),
                patch("src.acquire_data.WFS_PAGE_SIZE", 2),
                patch("src.acquire_data.urllib.request.urlopen", open_page),
            ):
                record = download_wfs_source(
                    "authenticated_sample",
                    {
                        "endpoint": "https://example.invalid/wfs",
                        "typename": "sample:layer",
                        "crs": "EPSG:25832",
                        "title": "Sample authenticated layer",
                        "authenticated": True,
                    },
                    False,
                    "private-value",
                )

            source_dir = (
                root / "data" / "raw" / "phase-b" / "authenticated_sample"
            )
            saved_pages = sorted(source_dir.glob("page_*.gml"))
            saved_ids = []
            for path in saved_pages:
                page_root = ET.parse(path).getroot()
                saved_ids.extend(
                    feature.attrib["{http://www.opengis.net/gml/3.2}id"]
                    for member in page_root
                    if member.tag.rsplit("}", 1)[-1] == "member"
                    for feature in member
                )

        self.assertIsNotNone(record)
        if record is None:
            self.fail("WFS download returned no manifest record")
        self.assertEqual(record["feature_count"], 3)
        self.assertEqual(len(saved_ids), 3)
        self.assertEqual(len(set(saved_ids)), 3)

    def test_rejects_gml_count_below_number_matched(self) -> None:
        pages = [self.gml_page([1, 2], matched=3), self.gml_page([], matched=3)]

        def open_page(request, timeout):
            return io.BytesIO(pages.pop(0))

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with (
                patch("src.acquire_data.ROOT", root),
                patch("src.acquire_data.RAW", root / "data" / "raw"),
                patch("src.acquire_data.WFS_PAGE_SIZE", 2),
                patch("src.acquire_data.urllib.request.urlopen", open_page),
            ):
                with self.assertRaisesRegex(
                    ValueError, "expected 3 unique features from numberMatched"
                ):
                    download_wfs_source(
                        "authenticated_sample",
                        {
                            "endpoint": "https://example.invalid/wfs",
                            "typename": "sample:layer",
                            "crs": "EPSG:25832",
                            "title": "Sample authenticated layer",
                            "authenticated": True,
                        },
                        False,
                        "private-value",
                    )

    def test_surfaces_non_retryable_http_errors_without_saving_partial_pages(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            def forbidden(request, timeout):
                raise HTTPError(
                    request.full_url, 403, "Forbidden", Message(), None
                )

            with (
                patch("src.acquire_data.ROOT", root),
                patch("src.acquire_data.RAW", root / "data" / "raw"),
                patch("src.acquire_data.urllib.request.urlopen", forbidden),
            ):
                with self.assertRaisesRegex(RuntimeError, "HTTP 403"):
                    download_wfs_source(
                        "forbidden",
                        {
                            "endpoint": "https://example.invalid/wfs",
                            "typename": "sample:layer",
                            "crs": "EPSG:25832",
                            "title": "Forbidden layer",
                        },
                        False,
                    )

            source_dir = root / "data" / "raw" / "phase-b" / "forbidden"
            self.assertFalse((source_dir / "complete.json").exists())
            self.assertEqual(list(source_dir.glob("page_*")), [])


if __name__ == "__main__":
    unittest.main()
