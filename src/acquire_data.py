"""Download, clip, and reproject approved source data for the routing study."""

from __future__ import annotations

import argparse
import csv
import gc
import hashlib
import io
import json
import logging
import math
import os
import re
import shutil
import time
import urllib.parse
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pyogrio
import rasterio
import shapely
import yaml
from pyproj import Transformer
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.warp import reproject, transform_bounds
from shapely import make_valid, union_all
from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Point,
    Polygon,
    mapping,
)
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
SOURCES_FILE = ROOT / "data" / "SOURCES.md"
TARGET_CRS = "EPSG:25832"
LAND_BUFFER_M = 20_000
CONFIG_FILE = ROOT / "config" / "costs.yaml"
HOTSPOTS_FILE = ROOT / "data" / "input" / "hotspots.csv"
USER_AGENT = "co2-pipeline-routing/0.1 (open-data research project)"

GEOFABRIK_GPKG = (
    "https://download.geofabrik.de/europe/denmark-latest-free.gpkg.zip"
)
GEOFABRIK_PBF = "https://download.geofabrik.de/europe/denmark-latest.osm.pbf"
GEOFABRIK_POLY = "https://download.geofabrik.de/europe/denmark.poly"
LAND_POLYGONS = (
    "https://osmdata.openstreetmap.de/download/land-polygons-split-4326.zip"
)
PROTECTED_NATURE = (
    "https://arealdata-api.miljoeportal.dk/download/daie/"
    "BES_NATURTYPER_SHAPE.zip"
)
PROTECTED_RESERVES = (
    "https://arealdata-api.miljoeportal.dk/download/daie/"
    "FREDEDE_OMR_SHAPE.zip"
)
POPULATION = (
    "https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/"
    "GHS_POP_GLOBE_R2023A/"
    "GHS_POP_E2020_GLOBE_R2023A_54009_100/V1-0/"
    "GHS_POP_E2020_GLOBE_R2023A_54009_100_V1_0.zip"
)
EEA_LAYER_URL = (
    "https://bio.discomap.eea.europa.eu/arcgis/rest/services/"
    "ProtectedSites/Natura2000Sites/MapServer/{layer}/query"
)
EEA_LAYER_NAMES = {
    0: "natura2000_habitats_dk.geojson",
    1: "natura2000_birds_dk.geojson",
}
DEA_STORAGE_AREAS: tuple[dict[str, str], ...] = (
    {
        "hotspot_id": "greenstore_gassum",
        "name": "Gassum",
        "kind": "licence",
        "holder": "Harbour Energy (40%); INEOS (40%); Nordsøfonden (20%)",
        "licence": "C2024/01",
        "url": "https://services3.arcgis.com/VfNcCOxfWppwD8Xh/arcgis/rest/services/C2024_01/FeatureServer/0",
        "format": "geojson",
    },
    {
        "hotspot_id": "havnsø_exploration",
        "name": "Havnsø",
        "kind": "licence",
        "holder": "Equinor; Ørsted (20%); Nordsøfonden (20%)",
        "licence": "C2024/03",
        "url": "https://services3.arcgis.com/VfNcCOxfWppwD8Xh/arcgis/rest/services/C2024_03/FeatureServer/0",
        "format": "geojson",
    },
    {
        "hotspot_id": "roedby_exploration",
        "name": "Rødby",
        "kind": "licence",
        "holder": "CarbonCuts; Nordsøfonden (20%)",
        "licence": "C2024/02",
        "url": "https://services3.arcgis.com/VfNcCOxfWppwD8Xh/arcgis/rest/services/C2024_02/FeatureServer/0",
        "format": "geojson",
    },
    {
        "hotspot_id": "stenlille",
        "name": "Stenlille",
        "kind": "designation",
        "holder": "",
        "licence": "",
        "url": "https://services3.arcgis.com/VfNcCOxfWppwD8Xh/arcgis/rest/services/Stenlille_UU/FeatureServer/0",
        "format": "geojson",
    },
    {
        "hotspot_id": "thorning",
        "name": "Thorning",
        "kind": "designation",
        "holder": "",
        "licence": "",
        "url": "https://www.arcgis.com/sharing/rest/content/items/0590b16f4105478ab34dbd136e0b25e2/data",
        "format": "kmz",
    },
    {
        "hotspot_id": "greensand_nini_west",
        "name": "Nini West",
        "kind": "permit",
        "holder": "INEOS (40%); Harbour Energy (40%); Nordsøfonden (20%)",
        "licence": "Nini West storage permit",
        "url": "https://services3.arcgis.com/VfNcCOxfWppwD8Xh/arcgis/rest/services/Nini_West_storage_permit/FeatureServer/0",
        "format": "geojson",
    },
    {
        "hotspot_id": "bifrost_harald",
        "name": "Bifrost",
        "kind": "licence",
        "holder": "TotalEnergies (80%); Nordsøfonden (20%)",
        "licence": "C2023/02",
        "url": "https://services3.arcgis.com/VfNcCOxfWppwD8Xh/arcgis/rest/services/TotalEnergiesED50UTM32/FeatureServer/0",
        "format": "geojson",
    },
    {
        "hotspot_id": "inez",
        "name": "Inez",
        "kind": "licence",
        "holder": "TotalEnergies Carbon Neutrality DK (65%); Mitsui CCS DK (15%); Nordsøfonden (20%)",
        "licence": "C2026/01",
        "url": "https://services3.arcgis.com/VfNcCOxfWppwD8Xh/arcgis/rest/services/inez_subsurface_designation/FeatureServer/0",
        "format": "geojson",
    },
    {
        "hotspot_id": "lisa",
        "name": "Lisa",
        "kind": "designation",
        "holder": "",
        "licence": "",
        "url": "https://services3.arcgis.com/VfNcCOxfWppwD8Xh/arcgis/rest/services/Lisa_subsurface_designation/FeatureServer/0",
        "format": "geojson",
    },
    {
        "hotspot_id": "jammerbugt",
        "name": "Jammerbugt",
        "kind": "designation",
        "holder": "",
        "licence": "",
        "url": "https://services3.arcgis.com/VfNcCOxfWppwD8Xh/arcgis/rest/services/Jammerbugt_subsurface_designation/FeatureServer/0",
        "format": "geojson",
    },
)
DATAFORDELER_WFS_KEY = "DATAFORDELER_API_KEY"
WFS_PAGE_SIZE = 2_000
WFS_SOURCES: dict[str, dict[str, Any]] = {
    "drinking_water": {
        "endpoint": "https://wfs2-miljoegis.mim.dk/grukos/ows",
        "typename": "grukos:drikkevandsinteresser",
        "crs": "EPSG:25832",
        "publisher": "Danish Environmental Protection Agency",
        "license": "CC0 1.0",
        "title": "Drinking-water areas (OSD and OD)",
    },
    "bnbo": {
        "endpoint": "https://wfs2-miljoegis.mim.dk/grukos/ows",
        "typename": "grukos:bnbo",
        "crs": "EPSG:25832",
        "publisher": "Danish Environmental Protection Agency",
        "license": "CC0 1.0",
        "title": "BNBO groundwater protection areas",
    },
    "groundwater_catchments": {
        "endpoint": "https://wfs2-miljoegis.mim.dk/grukos/ows",
        "typename": "grukos:indvindingsoplande_alle",
        "crs": "EPSG:25832",
        "publisher": "Danish Environmental Protection Agency",
        "license": "CC0 1.0",
        "title": "Groundwater abstraction catchments",
    },
    "ancient_monuments_area": {
        "endpoint": "https://www.kulturarv.dk/ffgeoserver/public/wfs",
        "typename": "public:fundogfortidsminder_areal_fredet",
        "crs": "EPSG:25832",
        "publisher": "Danish Agency for Culture and Palaces",
        "license": "CC0 1.0",
        "title": "Protected ancient monuments (areas)",
    },
    "ancient_monuments_line": {
        "endpoint": "https://www.kulturarv.dk/ffgeoserver/public/wfs",
        "typename": "public:fundogfortidsminder_linje_fredet",
        "crs": "EPSG:25832",
        "publisher": "Danish Agency for Culture and Palaces",
        "license": "CC0 1.0",
        "title": "Protected ancient monuments (lines)",
    },
    "ancient_monuments_point": {
        "endpoint": "https://www.kulturarv.dk/ffgeoserver/public/wfs",
        "typename": "public:fundogfortidsminder_punkt_fredet",
        "crs": "EPSG:25832",
        "publisher": "Danish Agency for Culture and Palaces",
        "license": "CC0 1.0",
        "title": "Protected ancient monuments (points)",
    },
    "ancient_monument_protection": {
        "endpoint": "https://www.kulturarv.dk/ffgeoserver/public/wfs",
        "typename": "public:fundogfortidsminder_areal_beskyttelse",
        "crs": "EPSG:25832",
        "publisher": "Danish Agency for Culture and Palaces",
        "license": "CC0 1.0",
        "title": "Ancient-monument protection zones",
    },
    "lake_protection_lines": {
        "endpoint": "https://arealeditering-dist-geo.miljoeportal.dk/geoserver/wfs",
        "typename": "dai:soe_bes_linjer",
        "crs": "EPSG:25832",
        "publisher": "Danmarks Miljøportal",
        "license": "CC0 1.0",
        "title": "Lake protection lines",
    },
    "stream_protection_lines": {
        "endpoint": "https://arealeditering-dist-geo.miljoeportal.dk/geoserver/wfs",
        "typename": "dai:aa_bes_linjer",
        "crs": "EPSG:25832",
        "publisher": "Danmarks Miljøportal",
        "license": "CC0 1.0",
        "title": "Stream protection lines",
    },
    "contaminated_v2": {
        "endpoint": "https://jord.miljoeportal.dk/geo/wfs",
        "typename": "DKJord:View_V2Flader",
        "crs": "EPSG:25832",
        "publisher": "Danmarks Miljøportal (DKJord)",
        "license": "CC0 1.0",
        "title": "Contaminated land (V2)",
    },
    "contaminated_v1": {
        "endpoint": "https://jord.miljoeportal.dk/geo/wfs",
        "typename": "DKJord:View_V1Flader",
        "crs": "EPSG:25832",
        "publisher": "Danmarks Miljøportal (DKJord)",
        "license": "CC0 1.0",
        "title": "Contaminated land (V1)",
    },
    "marine_plan": {
        "endpoint": "https://havplan.dk/geoserver/havplan/wfs",
        "typename": "havplan:Danmarks_havplan_af_28_juni_2024",
        "crs": "EPSG:25832",
        "publisher": "Danish Maritime Authority",
        "license": "CC BY 4.0",
        "title": "Denmark's maritime spatial plan zones",
    },
    "offshore_wind": {
        "endpoint": "https://ows.emodnet-humanactivities.eu/wfs",
        "typename": "emodnet:windfarmspoly",
        "crs": "EPSG:4326",
        "publisher": "EMODnet Human Activities",
        "license": "CC BY 4.0",
        "title": "Offshore wind farms",
    },
    "munitions_polygons": {
        "endpoint": "https://ows.emodnet-humanactivities.eu/wfs",
        "typename": "emodnet:munitionspoly",
        "crs": "EPSG:4326",
        "publisher": "EMODnet Human Activities",
        "license": "CC BY 4.0",
        "title": "Dumped munitions areas",
    },
    "munitions_points": {
        "endpoint": "https://ows.emodnet-humanactivities.eu/wfs",
        "typename": "emodnet:munitions",
        "crs": "EPSG:4326",
        "publisher": "EMODnet Human Activities",
        "license": "CC BY 4.0",
        "title": "Dumped munitions points",
    },
    "subsea_pipelines": {
        "endpoint": "https://ows.emodnet-humanactivities.eu/wfs",
        "typename": "emodnet:pipelines",
        "crs": "EPSG:4326",
        "publisher": "EMODnet Human Activities",
        "license": "CC BY 4.0",
        "title": "Subsea pipelines",
    },
    "subsea_cables": {
        "endpoint": "https://ows.emodnet-humanactivities.eu/wfs",
        "typename": "emodnet:pcablesbshcontis",
        "crs": "EPSG:4326",
        "publisher": "EMODnet Human Activities",
        "license": "CC BY 4.0",
        "title": "Subsea cables",
    },
    "beach_protection": {
        "endpoint": "https://wfs.datafordeler.dk/MATRIKLEN2/MatGaeldendeOgForeloebigWFS/1.0.0/WFS",
        "typename": "mat:StrandbeskyttelseFlade_Gaeldende",
        "crs": "EPSG:25832",
        "publisher": "Klimadatastyrelsen (Datafordeler)",
        "license": "CC BY 4.0",
        "title": "Beach protection areas",
        "authenticated": True,
    },
    "fredskov": {
        "endpoint": "https://wfs.datafordeler.dk/MATRIKLEN2/MatGaeldendeOgForeloebigWFS/1.0.0/WFS",
        "typename": "mat:FredskovFlade_Gaeldende",
        "crs": "EPSG:25832",
        "publisher": "Klimadatastyrelsen (Datafordeler)",
        "license": "CC BY 4.0",
        "title": "Protected forest (fredskov)",
        "authenticated": True,
    },
}

LOG = logging.getLogger("acquire_data")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download_file(
    url: str,
    destination: Path,
    force: bool,
    previous: dict[str, Any] | None,
) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and not force:
        LOG.info("Already downloaded: %s", destination)
        if previous is not None:
            return previous
        return {
            "url": url,
            "path": str(destination.relative_to(ROOT)),
            "download_date": None,
            "bytes": destination.stat().st_size,
            "sha256": sha256_file(destination),
            "note": "Existing file predates the acquisition manifest; date unknown.",
        }

    partial = destination.with_suffix(destination.suffix + ".part")
    partial.unlink(missing_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    LOG.info("Downloading %s", url)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            expected_length = response.headers.get("Content-Length")
            with partial.open("wb") as output:
                shutil.copyfileobj(response, output, length=1024 * 1024)
        actual_length = partial.stat().st_size
        if expected_length and actual_length != int(expected_length):
            raise IOError(
                f"Incomplete download for {url}: expected "
                f"{expected_length} bytes, received {actual_length}"
            )
        partial.replace(destination)
    except Exception:
        partial.unlink(missing_ok=True)
        raise

    LOG.info("Saved %s (%s bytes)", destination, destination.stat().st_size)
    return {
        "url": url,
        "path": str(destination.relative_to(ROOT)),
        "download_date": datetime.now(UTC).date().isoformat(),
        "bytes": destination.stat().st_size,
        "sha256": sha256_file(destination),
    }


def download_eea_layer(
    layer: int,
    destination: Path,
    force: bool,
    previous: dict[str, Any] | None,
) -> dict[str, Any]:
    if destination.exists() and not force:
        LOG.info("Already downloaded: %s", destination)
        if previous is not None:
            return previous
        return {
            "url": EEA_LAYER_URL.format(layer=layer),
            "path": str(destination.relative_to(ROOT)),
            "download_date": None,
            "bytes": destination.stat().st_size,
            "sha256": sha256_file(destination),
            "note": "Existing file predates the acquisition manifest; date unknown.",
        }

    features: list[dict[str, Any]] = []
    offset = 0
    page_size = 2000
    url = EEA_LAYER_URL.format(layer=layer)
    while True:
        query = urllib.parse.urlencode(
            {
                "where": "MS='DK'",
                "outFields": "*",
                "returnGeometry": "true",
                "outSR": "25832",
                "f": "geojson",
                "resultOffset": str(offset),
                "resultRecordCount": str(page_size),
            }
        )
        request = urllib.request.Request(
            f"{url}?{query}", headers={"User-Agent": USER_AGENT}
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            page = json.load(response)
        if "error" in page:
            raise RuntimeError(f"EEA query failed: {page['error']}")
        page_features = page.get("features")
        if not isinstance(page_features, list):
            raise ValueError(f"EEA layer {layer} did not return GeoJSON features")
        features.extend(page_features)
        LOG.info("EEA layer %s: received %s features", layer, len(features))
        if len(page_features) < page_size:
            break
        offset += len(page_features)

    if not features:
        raise ValueError(f"EEA layer {layer} returned no Denmark features")
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "type": "FeatureCollection",
        "crs": {
            "type": "name",
            "properties": {"name": TARGET_CRS},
        },
        "features": features,
    }
    temporary = destination.with_suffix(destination.suffix + ".part")
    temporary.write_text(json.dumps(payload), encoding="utf-8")
    temporary.replace(destination)
    return {
        "url": f"{url}?where=MS%3D%27DK%27&outSR=25832&f=geojson",
        "path": str(destination.relative_to(ROOT)),
        "download_date": datetime.now(UTC).date().isoformat(),
        "bytes": destination.stat().st_size,
        "sha256": sha256_file(destination),
    }


def download_dea_storage_area(
    source: dict[str, str],
    destination: Path,
    force: bool,
    previous: dict[str, Any] | None,
) -> dict[str, Any]:
    if destination.exists() and not force:
        LOG.info("Already downloaded: %s", destination)
        if previous is not None:
            return previous

    features: list[dict[str, Any]] = []
    offset = 0
    page_size = 1_000
    while True:
        query = urllib.parse.urlencode(
            {
                "where": "1=1",
                "outFields": "*",
                "returnGeometry": "true",
                "outSR": "4326",
                "f": "geojson",
                "resultOffset": str(offset),
                "resultRecordCount": str(page_size),
            }
        )
        request = urllib.request.Request(
            f"{source['url']}/query?{query}", headers={"User-Agent": USER_AGENT}
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            page = json.load(response)
        if "error" in page:
            raise RuntimeError(
                f"DEA storage-area query failed for {source['hotspot_id']}: "
                f"{page['error']}"
            )
        page_features = page.get("features")
        if not isinstance(page_features, list):
            raise ValueError(
                "DEA storage-area service returned no GeoJSON features array: "
                f"{source['url']}"
            )
        features.extend(page_features)
        if not page.get("exceededTransferLimit") and len(page_features) < page_size:
            break
        if not page_features:
            raise ValueError(
                f"DEA storage-area paging made no progress: {source['url']}"
            )
        offset += len(page_features)

    if not features:
        raise ValueError(
            f"DEA storage-area service returned no features: {source['url']}"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
        "features": features,
    }
    temporary = destination.with_suffix(destination.suffix + ".part")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temporary.replace(destination)
    return {
        "url": source["url"],
        "path": str(destination.relative_to(ROOT)),
        "download_date": datetime.now(UTC).date().isoformat(),
        "feature_count": len(features),
        "bytes": destination.stat().st_size,
        "sha256": sha256_file(destination),
    }


def kml_polygon_geometries(kmz_path: Path) -> list[Polygon]:
    with zipfile.ZipFile(kmz_path) as archive:
        kml_names = [name for name in archive.namelist() if name.casefold().endswith(".kml")]
        if not kml_names:
            raise ValueError(f"DEA KMZ has no KML document: {kmz_path}")
        root = ET.fromstring(archive.read(kml_names[0]))

    def local_name(element: ET.Element) -> str:
        return element.tag.rsplit("}", 1)[-1]

    def ring_coordinates(ring: ET.Element) -> list[tuple[float, float]]:
        text = next(
            (
                child.text
                for child in ring.iter()
                if local_name(child) == "coordinates" and child.text
            ),
            "",
        )
        coordinates = [
            tuple(float(value) for value in coordinate.split(",")[:2])
            for coordinate in text.split()
        ]
        if len(coordinates) < 4:
            raise ValueError(f"Invalid polygon ring in DEA KMZ {kmz_path}")
        return coordinates

    polygons: list[Polygon] = []
    for polygon_element in root.iter():
        if local_name(polygon_element) != "Polygon":
            continue
        outer_boundary = next(
            (
                element
                for element in polygon_element
                if local_name(element) == "outerBoundaryIs"
            ),
            None,
        )
        if outer_boundary is None:
            raise ValueError(f"DEA KMZ polygon has no outer ring: {kmz_path}")
        outer_ring = next(
            (element for element in outer_boundary.iter() if local_name(element) == "LinearRing"),
            None,
        )
        if outer_ring is None:
            raise ValueError(f"DEA KMZ polygon has no linear ring: {kmz_path}")
        interiors = []
        for boundary in polygon_element:
            if local_name(boundary) != "innerBoundaryIs":
                continue
            inner_ring = next(
                (element for element in boundary.iter() if local_name(element) == "LinearRing"),
                None,
            )
            if inner_ring is None:
                raise ValueError(f"DEA KMZ polygon has invalid inner ring: {kmz_path}")
            interiors.append(ring_coordinates(inner_ring))
        polygons.append(
            make_valid(Polygon(ring_coordinates(outer_ring), interiors))
        )
    if not polygons:
        raise ValueError(f"DEA KMZ contains no polygons: {kmz_path}")
    return polygons


def prepare_storage_areas() -> Path:
    features: list[dict[str, Any]] = []
    for source in DEA_STORAGE_AREAS:
        raw_path = (
            RAW
            / "dea-storage"
            / f"{source['hotspot_id']}.{source['format']}"
        )
        if source["format"] == "kmz":
            geometries = kml_polygon_geometries(raw_path)
        else:
            frame = gpd.read_file(raw_path)
            if frame.crs is None:
                raise ValueError(
                    f"DEA storage-area GeoJSON has no CRS: {raw_path}"
                )
            if frame.crs.to_epsg() != 4326:
                frame = frame.to_crs("EPSG:4326")
            geometries = [
                make_valid(geometry)
                for geometry in frame.geometry
                if geometry is not None and not geometry.is_empty
            ]
        if not geometries:
            raise ValueError(
                f"No usable DEA storage-area geometry for {source['hotspot_id']}"
            )
        projected = gpd.GeoSeries(geometries, crs="EPSG:4326").to_crs(TARGET_CRS)
        area_km2 = union_all(projected.array).area / 1_000_000
        area_geometry = union_all(geometries)
        features.append(
            {
                "type": "Feature",
                "geometry": mapping(area_geometry),
                "properties": {
                    "hotspot_id": source["hotspot_id"],
                    "name": source["name"],
                    "kind": source["kind"],
                    "holder": source["holder"],
                    "licence": source["licence"],
                    "area_km2": round(area_km2, 3),
                    "source_url": source["url"],
                },
            }
        )

    output_path = PROCESSED / "storage_areas.geojson"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".part")
    temporary.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
                "features": features,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    temporary.replace(output_path)
    LOG.info("Prepared DEA storage areas: %s polygons", len(features))
    return output_path


def sanitize_wfs_page(
    content: bytes, api_key: str | None = None
) -> tuple[bytes, int]:
    secret_representations = (
        {
            api_key,
            urllib.parse.quote(api_key, safe=""),
            urllib.parse.quote_plus(api_key),
        }
        if api_key
        else set()
    )

    def redact(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: redact(item) for key, item in value.items()}
        if isinstance(value, list):
            return [redact(item) for item in value]
        if isinstance(value, str):
            for representation in secret_representations:
                value = value.replace(representation, "[REDACTED]")
        return value

    trimmed = content.lstrip(b"\xef\xbb\xbf \t\r\n")
    if trimmed.startswith(b"{"):
        payload = json.loads(trimmed)
        features = payload.get("features")
        if not isinstance(features, list):
            raise ValueError("WFS GeoJSON response has no features array")
        payload = redact(payload)
        if isinstance(payload, dict):
            payload.pop("next", None)
            links = payload.get("links")
            if isinstance(links, list):
                payload["links"] = [
                    link
                    for link in links
                    if not (
                        isinstance(link, dict)
                        and str(link.get("rel", "")).casefold() == "next"
                    )
                ]
        return (
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            len(features),
        )

    root = ET.fromstring(content)
    reported_count = next(
        (
            value
            for name, value in root.attrib.items()
            if name.rsplit("}", 1)[-1].lower() == "numberreturned"
        ),
        None,
    )
    count = int(reported_count) if reported_count and reported_count.isdigit() else -1
    for element in root.iter():
        for attribute in list(element.attrib):
            if attribute.rsplit("}", 1)[-1].lower() == "next":
                del element.attrib[attribute]
    sanitized = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    for representation in secret_representations:
        sanitized = sanitized.replace(representation.encode("utf-8"), b"[REDACTED]")
    return sanitized, count


def _wfs_number_matched(content: bytes) -> int | None:
    trimmed = content.lstrip(b"\xef\xbb\xbf \t\r\n")
    if trimmed.startswith(b"{"):
        payload = json.loads(trimmed)
        value = payload.get("numberMatched")
    else:
        root = ET.fromstring(content)
        value = next(
            (
                attribute
                for name, attribute in root.attrib.items()
                if name.rsplit("}", 1)[-1].casefold() == "numbermatched"
            ),
            None,
        )
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _deduplicate_gml_members(
    content: bytes, seen_ids: set[str]
) -> tuple[bytes, int, int]:
    root = ET.fromstring(content)
    members = [
        child
        for child in root
        if child.tag.rsplit("}", 1)[-1].casefold() == "member"
    ]
    unique_count = 0
    for member in members:
        feature = next(iter(member), None)
        if feature is None:
            raise ValueError("WFS GML member contains no feature")
        feature_id = next(
            (
                value
                for name, value in feature.attrib.items()
                if name.startswith("{http://www.opengis.net/gml/")
                and name.rsplit("}", 1)[-1].casefold() == "id"
            ),
            None,
        )
        if not feature_id:
            raise ValueError("WFS GML feature is missing its gml:id")
        if feature_id in seen_ids:
            root.remove(member)
            continue
        seen_ids.add(feature_id)
        unique_count += 1

    raw_count = len(members)
    for name in list(root.attrib):
        if name.rsplit("}", 1)[-1].casefold() == "numberreturned":
            root.attrib[name] = str(unique_count)
            break
    else:
        root.attrib["numberReturned"] = str(unique_count)
    return (
        ET.tostring(root, encoding="utf-8", xml_declaration=True),
        raw_count,
        unique_count,
    )


def download_wfs_source(
    source_key: str,
    source: dict[str, Any],
    force: bool,
    api_key: str | None = None,
) -> dict[str, Any] | None:
    if source.get("authenticated") and not api_key:
        LOG.warning(
            "Skipping %s because %s is not available in this shell",
            source["title"],
            DATAFORDELER_WFS_KEY,
        )
        return None

    source_dir = RAW / "phase-b" / source_key
    marker = source_dir / "complete.json"
    existing_pages = sorted(source_dir.glob("page_*.gml")) + sorted(
        source_dir.glob("page_*.geojson")
    )
    if (
        marker.exists()
        and existing_pages
        and not force
    ):
        previous = json.loads(marker.read_text(encoding="utf-8"))
        if len(existing_pages) == int(previous.get("page_count", -1)):
            return previous

    source_dir.mkdir(parents=True, exist_ok=True)
    marker.unlink(missing_ok=True)
    for page in existing_pages:
        page.unlink()

    page_count = 0
    feature_count = 0
    offset = 0
    seen_ids: set[str] = set()
    matched_count: int | None = None

    def fetch_page(page_offset: int, page_size: int) -> list[tuple[bytes, int]]:
        params = {
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetFeature",
            "typeNames": source["typename"],
            "count": str(page_size),
            "startIndex": str(page_offset),
            "srsName": source["crs"],
        }
        if not source.get("authenticated"):
            params["outputFormat"] = "application/json"
        if api_key and source.get("authenticated"):
            params["apikey"] = api_key
        request_url = source["endpoint"] + "?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(
            request_url, headers={"User-Agent": USER_AGENT}
        )

        response_content: bytes | None = None
        retry_delays = (2, 5, 10)
        for attempt in range(len(retry_delays) + 1):
            try:
                with urllib.request.urlopen(request, timeout=120) as response:
                    response_content = response.read()
                break
            except urllib.error.HTTPError as error:
                status = error.code
                retryable = (
                    status in {401, 429}
                    or 500 <= status < 600
                    or (status == 400 and source.get("authenticated"))
                )
                if not retryable:
                    raise RuntimeError(
                        f"WFS download failed for {source_key} at feature "
                        f"{page_offset}: HTTP {status}"
                    ) from None
                if attempt < len(retry_delays):
                    LOG.warning(
                        "Retrying %s WFS page at feature %s after HTTP %s",
                        source_key,
                        page_offset,
                        status,
                    )
                    time.sleep(retry_delays[attempt])
                    continue
                if status == 400 and source.get("authenticated") and page_size > 1:
                    first_size = page_size // 2
                    LOG.warning(
                        "Splitting %s WFS page at feature %s after repeated "
                        "HTTP 400 responses",
                        source_key,
                        page_offset,
                    )
                    first_pages = fetch_page(page_offset, first_size)
                    first_count = sum(returned for _, returned in first_pages)
                    if first_count < first_size:
                        return first_pages
                    return first_pages + fetch_page(
                        page_offset + first_size, page_size - first_size
                    )
                raise RuntimeError(
                    f"WFS download failed for {source_key} at feature "
                    f"{page_offset}: HTTP {status}"
                ) from None
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                raise RuntimeError(
                    f"WFS download failed for {source_key} at feature "
                    f"{page_offset}: {type(error).__name__}"
                ) from None
        if response_content is None:
            raise RuntimeError(
                f"WFS download returned no response for {source_key} at "
                f"feature {page_offset}"
            )

        sanitized, returned = sanitize_wfs_page(
            response_content,
            api_key if source.get("authenticated") else None,
        )
        if returned < 0:
            returned = len(gpd.read_file(io.BytesIO(sanitized)))
        return [(sanitized, returned)]

    while True:
        raw_page_count = 0
        for sanitized, reported_count in fetch_page(offset, WFS_PAGE_SIZE):
            number_matched = _wfs_number_matched(sanitized)
            if number_matched is not None:
                if matched_count is not None and matched_count != number_matched:
                    raise ValueError(
                        f"WFS numberMatched changed for {source_key}: "
                        f"{matched_count} to {number_matched}"
                    )
                matched_count = number_matched

            if source.get("authenticated"):
                sanitized, raw_count, unique_count = _deduplicate_gml_members(
                    sanitized, seen_ids
                )
                if reported_count >= 0 and raw_count != reported_count:
                    raise ValueError(
                        f"WFS page count mismatch for {source_key} at feature "
                        f"{offset + raw_page_count}: response reports "
                        f"{reported_count}, page contains {raw_count} features"
                    )
                returned = raw_count
            else:
                frame = gpd.read_file(io.BytesIO(sanitized))
                if reported_count >= 0 and len(frame) != reported_count:
                    raise ValueError(
                        f"WFS page count mismatch for {source_key} at feature "
                        f"{offset + raw_page_count}: response reports "
                        f"{reported_count}, parser read {len(frame)}"
                    )
                returned = len(frame)
                unique_count = returned

            raw_page_count += returned
            if unique_count:
                if source.get("authenticated"):
                    frame = gpd.read_file(io.BytesIO(sanitized))
                    if len(frame) != unique_count:
                        raise ValueError(
                            f"WFS de-duplicated page count mismatch for "
                            f"{source_key} at feature {offset + raw_page_count}: "
                            f"expected {unique_count}, parser read {len(frame)}"
                        )
                extension = "gml" if source.get("authenticated") else "geojson"
                page_path = source_dir / f"page_{page_count:05d}.{extension}"
                page_path.write_bytes(sanitized)
                page_count += 1
                feature_count += unique_count

        if raw_page_count == 0:
            break
        offset += raw_page_count
        LOG.info(
            "Downloaded %s: %s features",
            source_key,
            feature_count,
        )
        if raw_page_count < WFS_PAGE_SIZE:
            break

    if not page_count:
        raise ValueError(f"WFS source {source_key} returned no features")
    if matched_count is not None and feature_count != matched_count:
        raise ValueError(
            f"WFS feature count mismatch for {source_key}: expected "
            f"{matched_count} unique features from numberMatched, got "
            f"{feature_count}"
        )
    result = {
        "url": source["endpoint"],
        "typename": source["typename"],
        "path": str(source_dir.relative_to(ROOT)),
        "download_date": datetime.now(UTC).date().isoformat(),
        "feature_count": feature_count,
        "page_count": page_count,
        "sha256": hashlib.sha256(
            "".join(
                sha256_file(page)
                for page in sorted(source_dir.glob("page_*"))
            ).encode("ascii")
        ).hexdigest(),
    }
    marker.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def download_sources(force: bool) -> dict[str, dict[str, Any]]:
    manifest = load_manifest()

    def save_manifest() -> None:
        manifest_path = RAW / "acquisition-manifest.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    files = {
        "geofabrik_osm_denmark": (
            GEOFABRIK_PBF,
            RAW / "geofabrik" / "denmark-latest.osm.pbf",
        ),
        "geofabrik_osm_gpkg": (
            GEOFABRIK_GPKG,
            RAW / "geofabrik" / "denmark-latest-free.gpkg.zip",
        ),
        "geofabrik_denmark_boundary": (
            GEOFABRIK_POLY,
            RAW / "geofabrik" / "denmark.poly",
        ),
        "osm_land_polygons": (
            LAND_POLYGONS,
            RAW / "osm-land" / "land-polygons-split-4326.zip",
        ),
        "protected_nature": (
            PROTECTED_NATURE,
            RAW / "miljoeportal" / "protected-nature.zip",
        ),
        "protected_reserves": (
            PROTECTED_RESERVES,
            RAW / "miljoeportal" / "protected-reserves.zip",
        ),
        "ghsl_population_2020": (
            POPULATION,
            RAW / "ghsl" / "population-2020-100m.zip",
        ),
    }
    for name, (url, destination) in files.items():
        manifest[name] = download_file(url, destination, force, manifest.get(name))
        save_manifest()

    for layer, filename in EEA_LAYER_NAMES.items():
        key = f"natura2000_{layer}"
        manifest[key] = download_eea_layer(
            layer, RAW / "eea" / filename, force, manifest.get(key)
        )
        save_manifest()
    for source in DEA_STORAGE_AREAS:
        key = f"dea_storage_area_{source['hotspot_id']}"
        suffix = source["format"]
        destination = (
            RAW / "dea-storage" / f"{source['hotspot_id']}.{suffix}"
        )
        if suffix == "kmz":
            manifest[key] = download_file(
                source["url"], destination, force, manifest.get(key)
            )
        else:
            manifest[key] = download_dea_storage_area(
                source, destination, force, manifest.get(key)
            )
        save_manifest()
    api_key = os.environ.get(DATAFORDELER_WFS_KEY)
    for key, source in WFS_SOURCES.items():
        source_record = download_wfs_source(key, source, force, api_key)
        if source_record is not None:
            manifest[f"phase_b_{key}"] = source_record
            save_manifest()
    return manifest


def parse_geofabrik_poly(path: Path) -> Polygon | MultiPolygon:
    rings: list[tuple[bool, list[tuple[float, float]]]] = []
    current_points: list[tuple[float, float]] = []
    current_is_hole = False
    for raw_line in path.read_text(encoding="utf-8").splitlines()[1:]:
        line = raw_line.strip()
        if not line:
            continue
        if line.upper() == "END":
            if current_points:
                rings.append((current_is_hole, current_points))
                current_points = []
            elif rings:
                break
            continue
        fields = line.split()
        if len(fields) == 1 and not current_points:
            current_is_hole = fields[0].startswith("!")
            continue
        if len(fields) == 2:
            current_points.append((float(fields[0]), float(fields[1])))

    if current_points:
        rings.append((current_is_hole, current_points))
    outer_rings = [points for is_hole, points in rings if not is_hole]
    holes = [points for is_hole, points in rings if is_hole]
    if not outer_rings:
        raise ValueError(f"No boundary polygons found in {path}")
    polygons = [Polygon(ring) for ring in outer_rings]
    if holes and len(polygons) == 1:
        polygons[0] = Polygon(outer_rings[0], holes)
    return polygons[0] if len(polygons) == 1 else MultiPolygon(polygons)


def safe_extract(zip_path: Path, destination: Path) -> list[Path]:
    destination.mkdir(parents=True, exist_ok=True)
    extracted: list[Path] = []
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.infolist():
            if member.is_dir():
                continue
            output_path = (destination / member.filename).resolve()
            if not output_path.is_relative_to(destination.resolve()):
                raise ValueError(f"Unsafe archive member path: {member.filename}")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, output_path.open("wb") as output:
                shutil.copyfileobj(source, output)
            extracted.append(output_path)
    return extracted


def clip_vector(
    frame: gpd.GeoDataFrame, mask: Any, target_crs: str = TARGET_CRS
) -> gpd.GeoDataFrame:
    if frame.crs is None:
        raise ValueError("Vector source has no CRS metadata")
    projected = frame.to_crs(target_crs)
    geometries = projected.geometry.values
    invalid = ~shapely.is_valid(geometries) & ~shapely.is_missing(
        geometries
    )
    if invalid.any():
        projected.loc[invalid, "geometry"] = shapely.make_valid(
            geometries[invalid], method="structure", keep_collapsed=False
        )
    intersects = projected.geometry.intersects(mask)
    clipped = projected.loc[intersects].copy()
    if clipped.empty:
        return clipped
    clipped.geometry = clipped.geometry.map(
        lambda geom: make_valid(geom.intersection(mask))
        if geom is not None and not geom.is_empty
        else geom
    )
    clipped = clipped.loc[
        clipped.geometry.notna() & ~clipped.geometry.is_empty
    ].copy()
    clipped = clipped.loc[clipped.geometry.geom_type != "GeometryCollection"].copy()
    return clipped


def write_gpkg(path: Path, layers: dict[str, gpd.GeoDataFrame]) -> None:
    empty_layers = [layer for layer, frame in layers.items() if frame.empty]
    if empty_layers:
        raise ValueError(
            f"Refusing to write empty layers {empty_layers!r} to {path}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    first = True
    for layer, frame in layers.items():
        frame.to_file(
            path,
            layer=layer,
            driver="GPKG",
            index=False,
            mode="w" if first else "a",
        )
        first = False


def extend_extent_to_offshore_storage(
    extent_geometry: Any,
    land_geometry: Any,
    hotspots_path: Path,
    corridor_half_width_m: float,
) -> Any:
    if corridor_half_width_m <= 0:
        raise ValueError("Offshore corridor half-width must be positive")
    if not hotspots_path.exists():
        return extent_geometry
    transformer = Transformer.from_crs("EPSG:4326", TARGET_CRS, always_xy=True)
    with hotspots_path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or not {"role", "lon", "lat"}.issubset(
            reader.fieldnames
        ):
            raise ValueError(
                f"{hotspots_path} must include role, lon, and lat columns "
                "to build offshore corridors."
            )
        corridors = []
        offshore_sites: dict[str, Point] = {}
        for record in reader:
            if (record.get("role") or "").strip().lower() != "storage":
                continue
            try:
                lon, lat = float(record["lon"]), float(record["lat"])
            except (TypeError, ValueError) as error:
                raise ValueError(
                    f"Invalid storage coordinate in {hotspots_path}: {record}"
                ) from error
            x, y = transformer.transform(lon, lat)
            storage_point = Point(x, y)
            identifier = (record.get("id") or "").strip()
            if identifier in {
                "greensand_nini_west",
                "bifrost_harald",
                "inez",
            }:
                offshore_sites[identifier] = storage_point
            if extent_geometry.covers(storage_point):
                continue
            coastal_point = nearest_points(land_geometry, storage_point)[0]
            corridors.append(
                LineString([coastal_point, storage_point]).buffer(
                    corridor_half_width_m
                )
            )
    north_sea_sites = (
        "greensand_nini_west",
        "bifrost_harald",
        "inez",
    )
    if set(north_sea_sites) <= offshore_sites.keys():
        landfalls = [
            nearest_points(land_geometry, offshore_sites[identifier])[0]
            for identifier in north_sea_sites
        ]
        north_sea_corridor = MultiPoint(
            [
                *(offshore_sites[identifier] for identifier in north_sea_sites),
                *landfalls,
            ]
        ).convex_hull.buffer(corridor_half_width_m)
        corridors.append(north_sea_corridor)
    if corridors:
        return union_all([extent_geometry, *corridors])
    return extent_geometry


def exclude_foreign_land_from_extent(
    extent_geometry: BaseGeometry,
    all_land_geometry: BaseGeometry,
    boundary_geometry: BaseGeometry,
) -> tuple[BaseGeometry, BaseGeometry]:
    foreign_geometry = make_valid(
        all_land_geometry.intersection(extent_geometry).difference(
            boundary_geometry
        )
    )
    extent_geometry = make_valid(extent_geometry.difference(foreign_geometry))
    if extent_geometry.is_empty:
        raise ValueError("Excluding foreign land removed the entire analysis extent")
    return extent_geometry, foreign_geometry


def boundary_and_land(
    hotspots_path: Path = HOTSPOTS_FILE,
    corridor_half_width_m: float = 10_000,
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, gpd.GeoDataFrame]:
    boundary_file = RAW / "geofabrik" / "denmark.poly"
    land_zip = RAW / "osm-land" / "land-polygons-split-4326.zip"
    boundary_wgs84 = gpd.GeoDataFrame(
        {"name": ["Denmark extract boundary"]},
        geometry=[parse_geofabrik_poly(boundary_file)],
        crs="EPSG:4326",
    )

    extracted_dir = RAW / "osm-land" / "extracted"
    if not any(extracted_dir.rglob("*.shp")):
        safe_extract(land_zip, extracted_dir)
    shapefiles = list(extracted_dir.rglob("*.shp"))
    if not shapefiles:
        raise FileNotFoundError(f"No shapefile in {land_zip}")
    bbox = tuple(float(value) for value in boundary_wgs84.total_bounds)
    land = gpd.read_file(shapefiles[0], bbox=bbox)
    if land.crs is None:
        raise ValueError("OSM land polygons have no CRS metadata")
    land = gpd.clip(land, boundary_wgs84)
    if land.empty:
        raise ValueError("No OSM land polygons intersect the Denmark boundary")
    land = land.to_crs(TARGET_CRS)
    land.geometry = land.geometry.map(make_valid)
    land_geometry = union_all(land.geometry.array)
    if land_geometry.is_empty:
        raise ValueError("Could not construct Denmark land geometry")

    extent_geometry = land_geometry.buffer(LAND_BUFFER_M)
    extent_geometry = extend_extent_to_offshore_storage(
        extent_geometry,
        land_geometry,
        hotspots_path,
        corridor_half_width_m,
    )
    extent_bounds = (
        gpd.GeoSeries([extent_geometry], crs=TARGET_CRS)
        .to_crs("EPSG:4326")
        .total_bounds
    )
    left, bottom, right, top = map(float, extent_bounds)
    extent_bbox = (
        left - 0.05,
        bottom - 0.05,
        right + 0.05,
        top + 0.05,
    )
    all_land = gpd.read_file(shapefiles[0], bbox=extent_bbox)
    if all_land.crs is None:
        raise ValueError("OSM land polygons have no CRS metadata")
    if all_land.empty:
        raise ValueError("No OSM land polygons overlap the analysis extent")
    all_land = all_land.to_crs(TARGET_CRS)
    all_land.geometry = all_land.geometry.map(make_valid)
    all_land_geometry = union_all(
        [
            geometry.intersection(extent_geometry)
            for geometry in all_land.geometry.array
            if geometry is not None and not geometry.is_empty
        ]
    )
    boundary_geometry = boundary_wgs84.to_crs(TARGET_CRS).geometry.iloc[0]
    extent_geometry, foreign_geometry = exclude_foreign_land_from_extent(
        extent_geometry, all_land_geometry, boundary_geometry
    )
    extent = gpd.GeoDataFrame(
        {
            "buffer_m": [LAND_BUFFER_M],
            "offshore_corridor_half_width_m": [corridor_half_width_m],
        },
        geometry=[extent_geometry],
        crs=TARGET_CRS,
    )
    country_land = gpd.GeoDataFrame(
        {"source": ["OSM coastline polygons"]},
        geometry=[land_geometry],
        crs=TARGET_CRS,
    )
    foreign_land = gpd.GeoDataFrame(
        {"source": ["OSM land polygons outside Denmark"]},
        geometry=[foreign_geometry],
        crs=TARGET_CRS,
    )
    return extent, country_land, foreign_land


def polygon_parts(geometry: Any) -> list[Polygon]:
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, MultiPolygon):
        return list(geometry.geoms)
    if isinstance(geometry, GeometryCollection):
        return [part for geom in geometry.geoms for part in polygon_parts(geom)]
    return []


def prepare_coast_and_extent(
    extent: gpd.GeoDataFrame,
    country_land: gpd.GeoDataFrame,
    foreign_land: gpd.GeoDataFrame,
) -> None:
    mask = extent.geometry.iloc[0]
    land_geometry = country_land.geometry.iloc[0].intersection(mask)
    foreign_geometry = foreign_land.geometry.iloc[0]
    sea_geometry = mask.difference(land_geometry)
    sea_parts = polygon_parts(make_valid(sea_geometry))
    if not sea_parts:
        raise ValueError("No coastal water cells found in the buffered extent")
    land = gpd.GeoDataFrame(
        {"class": ["land"]},
        geometry=[land_geometry],
        crs=TARGET_CRS,
    )
    sea = gpd.GeoDataFrame(
        {"class": ["open_sea"] * len(sea_parts)},
        geometry=sea_parts,
        crs=TARGET_CRS,
    )
    foreign = gpd.GeoDataFrame(
        {"class": ["foreign_land"]},
        geometry=[foreign_geometry],
        crs=TARGET_CRS,
    )
    write_gpkg(
        PROCESSED / "coast_land_water.gpkg",
        {
            "analysis_extent": extent,
            "land": land,
            "foreign_land": foreign,
            "open_sea": sea,
        },
    )


def geofabrik_gpkg_path() -> Path:
    archive = RAW / "geofabrik" / "denmark-latest-free.gpkg.zip"
    extract_dir = RAW / "geofabrik" / "extracted"
    gpkg = extract_dir / "denmark.gpkg"
    with zipfile.ZipFile(archive) as source_archive:
        gpkg_member = next(
            (
                member
                for member in source_archive.infolist()
                if Path(member.filename).name == "denmark.gpkg"
            ),
            None,
        )
    if gpkg_member is None:
        raise FileNotFoundError(f"No denmark.gpkg member in {archive}")
    if (
        not gpkg.exists()
        or gpkg.stat().st_size != gpkg_member.file_size
        or gpkg.stat().st_mtime < archive.stat().st_mtime
    ):
        safe_extract(archive, extract_dir)
    if not gpkg.exists():
        raise FileNotFoundError(f"No GeoPackage in {archive}")
    return gpkg


def read_geofabrik_layer_batches(
    gpkg: Path,
    layer: str,
    where: str | None,
    bbox: tuple[float, float, float, float],
) -> Iterator[gpd.GeoDataFrame]:
    info = pyogrio.read_info(gpkg, layer=layer)
    offset = 0
    batch_size = 100_000
    while True:
        frame = pyogrio.read_dataframe(
            gpkg,
            layer=layer,
            where=where,
            bbox=bbox,
            columns=list(info["fields"]),
            skip_features=offset,
            max_features=batch_size,
            use_arrow=True,
        )
        if frame.crs is None:
            raise ValueError(f"Geofabrik {layer} layer has no CRS metadata")
        if frame.empty:
            break
        yield gpd.GeoDataFrame(frame, geometry="geometry", crs=frame.crs)
        offset += len(frame)
        if len(frame) < batch_size:
            break


def write_gpkg_layer(
    path: Path, layer: str, frame: gpd.GeoDataFrame
) -> None:
    if frame.empty:
        raise ValueError(f"Refusing to write empty layer {layer!r} to {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    prepared = frame
    used_names: set[str] = set()
    renamed_fields: dict[str, str] = {}
    for column in prepared.columns:
        field_name = str(column)
        key = field_name.casefold()
        if key in used_names:
            suffix = 2
            candidate = f"{field_name}_{suffix}"
            while candidate.casefold() in used_names:
                suffix += 1
                candidate = f"{field_name}_{suffix}"
            renamed_fields[field_name] = candidate
            key = candidate.casefold()
        used_names.add(key)
    if renamed_fields:
        prepared = prepared.rename(columns=renamed_fields)
    geometry_types = {geom_type for geom_type in prepared.geom_type.unique() if geom_type}
    if geometry_types <= {"Polygon", "MultiPolygon"}:
        prepared = prepared.copy()
        prepared.geometry = prepared.geometry.map(
            lambda geom: MultiPolygon([geom]) if isinstance(geom, Polygon) else geom
        )
    elif geometry_types <= {"LineString", "MultiLineString"}:
        prepared = prepared.copy()
        prepared.geometry = prepared.geometry.map(
            lambda geom: MultiLineString([geom]) if isinstance(geom, LineString) else geom
        )
    prepared.to_file(
        path,
        layer=layer,
        driver="GPKG",
        index=False,
        mode="a" if path.exists() else "w",
    )


def prepare_osm(extent: gpd.GeoDataFrame) -> None:
    gpkg = geofabrik_gpkg_path()
    mask = extent.geometry.iloc[0]
    bbox_wgs84 = (
        gpd.GeoSeries([mask], crs=TARGET_CRS).to_crs("EPSG:4326").total_bounds
    )
    bbox = tuple(float(value) for value in bbox_wgs84)
    infrastructure = PROCESSED / "infrastructure.gpkg"
    water_and_urban = PROCESSED / "water_and_urban.gpkg"
    infrastructure.unlink(missing_ok=True)
    water_and_urban.unlink(missing_ok=True)
    layer_specs = [
        ("roads", "gis_osm_roads_free", None, infrastructure),
        ("railways", "gis_osm_railways_free", None, infrastructure),
        ("watercourses", "gis_osm_waterways_free", None, infrastructure),
        ("buildings", "gis_osm_buildings_a_free", None, water_and_urban),
        (
            "urban_areas",
            "gis_osm_landuse_a_free",
            "fclass IN ('residential', 'industrial', 'commercial', 'retail')",
            water_and_urban,
        ),
        (
            "lakes",
            "gis_osm_water_a_free",
            "fclass IN ('water', 'reservoir', 'riverbank')",
            water_and_urban,
        ),
        (
            "wetlands",
            "gis_osm_water_a_free",
            "fclass LIKE 'wetland%'",
            water_and_urban,
        ),
    ]
    available_layers = {
        str(row[0]) for row in pyogrio.list_layers(gpkg)
    }
    for output_layer, source_layer, where, output_path in layer_specs:
        if source_layer not in available_layers:
            raise ValueError(
                f"Expected Geofabrik layer {source_layer!r}; "
                f"available layers are {sorted(available_layers)}"
            )
        feature_count = 0
        for source in read_geofabrik_layer_batches(
            gpkg, source_layer, where, bbox
        ):
            clipped = clip_vector(source, mask)
            if not clipped.empty:
                write_gpkg_layer(output_path, output_layer, clipped)
                feature_count += len(clipped)
            del source, clipped
            gc.collect()
        if feature_count == 0:
            raise ValueError(f"Prepared OSM layer {output_layer!r} is empty")
        LOG.info("Prepared OSM %s: %s features", output_layer, feature_count)


def osm_tag_value(tags: str | None, key: str) -> str | None:
    if not isinstance(tags, str) or not tags:
        return None
    escaped_key = re.escape(key)
    match = re.search(
        rf'"{escaped_key}"=>"((?:\\.|[^"])*)"', tags
    )
    return match.group(1).replace(r"\"", '"') if match else None


def voltage_in_volts(value: str | None) -> float | None:
    if not value:
        return None
    voltages: list[float] = []
    for token in re.split(r"[;,]", value):
        match = re.fullmatch(
            r"\s*(\d+(?:\.\d+)?)\s*(kv|v)?\s*",
            token,
            flags=re.IGNORECASE,
        )
        if not match:
            continue
        amount = float(match.group(1))
        unit = (match.group(2) or "v").lower()
        voltages.append(amount * (1000 if unit == "kv" else 1))
    return max(voltages) if voltages else None


def prepare_phase_a_layers(
    extent: gpd.GeoDataFrame,
    requested_layers: set[str],
) -> Path:
    valid_layers = {"forest", "power_lines", "pipelines"}
    unknown_layers = requested_layers - valid_layers
    if unknown_layers:
        raise ValueError(f"Unknown phase-A layers: {sorted(unknown_layers)}")
    if not requested_layers:
        raise ValueError("At least one phase-A layer must be requested")

    output_path = PROCESSED / "phase_a_infrastructure.gpkg"
    output_path.unlink(missing_ok=True)
    mask = extent.geometry.iloc[0]
    bbox = tuple(
        float(value)
        for value in gpd.GeoSeries([mask], crs=TARGET_CRS)
        .to_crs("EPSG:4326")
        .total_bounds
    )
    geofabrik = geofabrik_gpkg_path()

    road_classes = {
        "roads_major": (
            "motorway", "motorway_link", "trunk", "trunk_link",
            "primary", "primary_link",
        ),
        "roads_minor": (
            "secondary", "secondary_link", "tertiary", "tertiary_link",
        ),
    }
    for output_layer, classes in road_classes.items():
        where = "fclass IN (" + ", ".join(
            f"'{value}'" for value in classes
        ) + ")"
        count = 0
        for source in read_geofabrik_layer_batches(
            geofabrik, "gis_osm_roads_free", where, bbox
        ):
            clipped = clip_vector(source, mask)
            if not clipped.empty:
                write_gpkg_layer(output_path, output_layer, clipped)
                count += len(clipped)
            del source, clipped
            gc.collect()
        if count == 0:
            raise ValueError(f"Prepared OSM layer {output_layer!r} is empty")
        LOG.info("Prepared OSM %s: %s features", output_layer, count)

    if "forest" in requested_layers:
        count = 0
        for source in read_geofabrik_layer_batches(
            geofabrik,
            "gis_osm_landuse_a_free",
            "fclass = 'forest'",
            bbox,
        ):
            clipped = clip_vector(source, mask)
            if not clipped.empty:
                write_gpkg_layer(output_path, "forest", clipped)
                count += len(clipped)
            del source, clipped
            gc.collect()
        if count == 0:
            raise ValueError("Prepared OSM forest layer is empty")
        LOG.info("Prepared OSM forest: %s features", count)

    pbf_path = RAW / "geofabrik" / "denmark-latest.osm.pbf"
    if {"power_lines", "pipelines"} & requested_layers:
        if not pbf_path.exists():
            raise FileNotFoundError(
                f"Required OSM PBF for phase-A infrastructure is missing: "
                f"{pbf_path}"
            )
        for layer_name, where in (
            (
                "power_lines",
                """other_tags LIKE '%"power"=>"line"%'""",
            ),
            ("pipelines", "man_made = 'pipeline'"),
        ):
            if layer_name not in requested_layers:
                continue
            frame = pyogrio.read_dataframe(
                pbf_path,
                layer="lines",
                columns=["osm_id", "other_tags"],
                where=where,
                bbox=bbox,
                use_arrow=True,
            )
            if frame.crs is None:
                raise ValueError(f"OSM PBF lines layer has no CRS: {pbf_path}")
            if layer_name == "power_lines":
                voltages = frame["other_tags"].map(
                    lambda tags: voltage_in_volts(
                        osm_tag_value(tags, "voltage")
                    )
                )
                frame = frame.loc[
                    voltages.map(
                        lambda voltage: voltage is not None
                        and voltage >= 132_000
                    )
                ].copy()
            else:
                substances = frame["other_tags"].map(
                    lambda tags: osm_tag_value(tags, "substance") or ""
                )
                frame = frame.loc[
                    substances.map(
                        lambda value: "gas" in {
                            part.strip().lower()
                            for part in re.split(r"[;,]", value)
                        }
                    )
                ].copy()
            clipped = clip_vector(frame, mask)
            if clipped.empty:
                raise ValueError(
                    f"Prepared OSM {layer_name!r} layer is empty"
                )
            write_gpkg_layer(output_path, layer_name, clipped)
            LOG.info("Prepared OSM %s: %s features", layer_name, len(clipped))

    return output_path


def wfs_source_pages(source_key: str) -> list[Path]:
    source_dir = RAW / "phase-b" / source_key
    pages = sorted(source_dir.glob("page_*.gml")) + sorted(
        source_dir.glob("page_*.geojson")
    )
    return sorted(pages)


def write_phase_b_layer(
    output_path: Path,
    layer_name: str,
    frame: gpd.GeoDataFrame,
    mask: BaseGeometry,
) -> int:
    clipped = clip_vector(frame, mask)
    if clipped.empty:
        return 0
    write_gpkg_layer(output_path, layer_name, clipped)
    return len(clipped)


def wind_farm_category(status: Any) -> str:
    normalized = str(status).strip().casefold()
    if any(
        marker in normalized
        for marker in ("planned", "plan", "proposed", "announced", "application")
    ):
        return "planned"
    if any(
        marker in normalized
        for marker in (
            "production",
            "operational",
            "operation",
            "construction",
            "approved",
            "consented",
            "commissioning",
            "built",
        )
    ):
        return "barrier"
    raise ValueError(
        f"Unclassified EMODnet wind-farm status {status!r}; update the "
        "explicit status mapping before using this dataset."
    )


def prepare_phase_b_layers(extent: gpd.GeoDataFrame) -> Path:
    mask = extent.geometry.iloc[0]
    output_path = PROCESSED / "phase_b.gpkg"
    output_path.unlink(missing_ok=True)
    feature_counts: dict[str, int] = {}

    def append(layer_name: str, frame: gpd.GeoDataFrame) -> None:
        feature_counts[layer_name] = feature_counts.get(layer_name, 0) + (
            write_phase_b_layer(output_path, layer_name, frame, mask)
        )

    for source_key in WFS_SOURCES:
        pages = wfs_source_pages(source_key)
        if not pages:
            if source_key in {"beach_protection", "fredskov"}:
                LOG.warning(
                    "No prepared Datafordeler layer for %s; its cost layer "
                    "will be omitted",
                    source_key,
                )
                continue
            raise FileNotFoundError(
                f"Raw WFS pages for {source_key} are missing; run "
                "python -m src.acquire_data first."
            )

        for page in pages:
            frame = gpd.read_file(page)
            if frame.crs is None:
                raise ValueError(f"WFS page has no CRS metadata: {page}")

            if source_key == "drinking_water":
                if "kategori" not in frame.columns:
                    raise ValueError(
                        "Drinking-water WFS is missing its verified "
                        "'kategori' field"
                    )
                categories = frame["kategori"].astype(str).str.upper()
                for category, layer in (
                    ("OSD", "drinking_water_osd"),
                    ("OD", "drinking_water_od"),
                ):
                    selected = frame.loc[categories == category]
                    if not selected.empty:
                        append(layer, selected)
            elif source_key == "marine_plan":
                if "zone_type" not in frame.columns:
                    raise ValueError(
                        "Marine-plan WFS is missing its verified "
                        "'zone_type' field"
                    )
                categories = frame["zone_type"].astype(str)
                for codes, layer in (
                    ({"S"}, "marine_shipping"),
                    ({"Ev", "Ei"}, "marine_renewables"),
                    ({"R", "N"}, "marine_materials"),
                    ({"Ek"}, "marine_cable_corridor"),
                ):
                    selected = frame.loc[categories.isin(codes)]
                    if not selected.empty:
                        append(layer, selected)
            elif source_key == "offshore_wind":
                frame = clip_vector(frame, mask)
                if "status" not in frame.columns:
                    raise ValueError(
                        "EMODnet wind-farm WFS is missing its verified "
                        "'status' field"
                    )
                categories = frame["status"].map(wind_farm_category)
                planned = frame.loc[categories == "planned"]
                barriers = frame.loc[categories == "barrier"]
                if not planned.empty:
                    append("offshore_wind_planned", planned)
                if not barriers.empty:
                    append("offshore_wind_barriers", barriers)
            elif source_key == "munitions_points":
                projected = frame.to_crs(TARGET_CRS)
                projected.geometry = projected.geometry.buffer(500)
                append("munitions_points", projected)
            else:
                layer = {
                    "bnbo": "bnbo",
                    "groundwater_catchments": "groundwater_catchments",
                    "ancient_monuments_area": "ancient_monuments_area",
                    "ancient_monuments_line": "ancient_monuments_line",
                    "ancient_monuments_point": "ancient_monuments_point",
                    "ancient_monument_protection": "ancient_monument_protection",
                    "lake_protection_lines": "water_protection_lines",
                    "stream_protection_lines": "water_protection_lines",
                    "contaminated_v2": "contaminated_v2",
                    "contaminated_v1": "contaminated_v1",
                    "munitions_polygons": "munitions_barriers",
                    "subsea_pipelines": "subsea_pipelines",
                    "subsea_cables": "subsea_cables",
                    "beach_protection": "beach_protection",
                    "fredskov": "fredskov",
                }.get(source_key)
                if layer is None:
                    raise ValueError(
                        f"No phase-B preparation rule for {source_key!r}"
                    )
                append(layer, frame)

    missing = [
        layer
        for layer in (
            "drinking_water_osd",
            "drinking_water_od",
            "bnbo",
            "groundwater_catchments",
            "ancient_monuments_area",
            "ancient_monuments_line",
            "ancient_monuments_point",
            "ancient_monument_protection",
            "water_protection_lines",
            "contaminated_v2",
            "contaminated_v1",
            "marine_shipping",
            "marine_renewables",
            "marine_materials",
            "marine_cable_corridor",
            "munitions_barriers",
            "munitions_points",
            "subsea_pipelines",
            "subsea_cables",
        )
        if not feature_counts.get(layer)
    ]
    if missing:
        raise ValueError(
            "Approved phase-B sources produced no features in the analysis "
            f"extent for required layers: {missing}"
        )
    LOG.info("Prepared phase-B layers: %s", feature_counts)
    return output_path


def read_zip_shapefile(zip_path: Path, extract_dir: Path) -> gpd.GeoDataFrame:
    shapefiles = list(extract_dir.rglob("*.shp"))
    if not shapefiles:
        safe_extract(zip_path, extract_dir)
        shapefiles = list(extract_dir.rglob("*.shp"))
    if not shapefiles:
        raise FileNotFoundError(f"No shapefile in {zip_path}")
    return gpd.read_file(shapefiles[0])


def prepare_protected_areas(extent: gpd.GeoDataFrame) -> None:
    mask = extent.geometry.iloc[0]
    protected_dir = RAW / "miljoeportal" / "extracted"
    nature = clip_vector(
        read_zip_shapefile(
            RAW / "miljoeportal" / "protected-nature.zip",
            protected_dir / "protected-nature",
        ),
        mask,
    )
    reserves = clip_vector(
        read_zip_shapefile(
            RAW / "miljoeportal" / "protected-reserves.zip",
            protected_dir / "protected-reserves",
        ),
        mask,
    )
    write_gpkg(
        PROCESSED / "protected_areas.gpkg",
        {"protected_nature_s3": nature, "fredninger": reserves},
    )


def prepare_natura2000(extent: gpd.GeoDataFrame) -> None:
    mask = extent.geometry.iloc[0]
    layers: dict[str, gpd.GeoDataFrame] = {}
    for layer_id, name in ((0, "habitats"), (1, "birds")):
        filename = RAW / "eea" / EEA_LAYER_NAMES[layer_id]
        source = gpd.read_file(filename)
        layers[name] = clip_vector(source, mask)
        LOG.info("Prepared Natura 2000 %s: %s features", name, len(layers[name]))
    write_gpkg(PROCESSED / "natura2000.gpkg", layers)


def extract_population_raster() -> Path:
    archive = RAW / "ghsl" / "population-2020-100m.zip"
    extract_dir = RAW / "ghsl" / "extracted"
    rasters = list(extract_dir.rglob("*.tif")) + list(extract_dir.rglob("*.tiff"))
    if rasters:
        return rasters[0]
    extract_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as source:
        raster_members = [
            item for item in source.infolist()
            if not item.is_dir() and Path(item.filename).suffix.lower() in {".tif", ".tiff"}
        ]
        if len(raster_members) != 1:
            raise ValueError(
                f"Expected one population GeoTIFF in {archive}, "
                f"found {len(raster_members)}"
            )
        member = raster_members[0]
        output = extract_dir / Path(member.filename).name
        with source.open(member) as input_stream, output.open("wb") as output_stream:
            shutil.copyfileobj(input_stream, output_stream, length=1024 * 1024)
    return output


def prepare_population(extent: gpd.GeoDataFrame) -> None:
    source_path = extract_population_raster()
    mask_bounds = tuple(float(value) for value in extent.total_bounds)
    source_bounds = transform_bounds(
        TARGET_CRS,
        "ESRI:54009",
        *mask_bounds,
        densify_pts=21,
    )
    resolution = 100.0
    left, bottom, right, top = source_bounds
    target_left = math.floor(mask_bounds[0] / resolution) * resolution
    target_bottom = math.floor(mask_bounds[1] / resolution) * resolution
    target_right = math.ceil(mask_bounds[2] / resolution) * resolution
    target_top = math.ceil(mask_bounds[3] / resolution) * resolution
    width = int(round((target_right - target_left) / resolution))
    height = int(round((target_top - target_bottom) / resolution))
    destination_transform = from_origin(
        target_left, target_top, resolution, resolution
    )
    output_path = PROCESSED / "population_2020_100m.tif"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with rasterio.open(source_path) as source:
        if source.crs is None:
            raise ValueError(f"Population raster has no CRS: {source_path}")
        window = source.window(left, bottom, right, top)
        window = window.intersection(
            rasterio.windows.Window(0, 0, source.width, source.height)
        )
        if window.width <= 0 or window.height <= 0:
            raise ValueError("Population raster does not overlap the study extent")
        source_data = source.read(1, window=window, masked=True)
        source_array = source_data.filled(-9999).astype(np.float32, copy=False)
        destination = np.full((height, width), -9999, dtype=np.float32)
        reproject(
            source=source_array,
            destination=destination,
            src_transform=source.window_transform(window),
            src_crs=source.crs,
            src_nodata=-9999,
            dst_transform=destination_transform,
            dst_crs=TARGET_CRS,
            dst_nodata=-9999,
            resampling=Resampling.average,
        )
        profile = {
            "driver": "GTiff",
            "height": height,
            "width": width,
            "count": 1,
            "dtype": "float32",
            "crs": TARGET_CRS,
            "transform": destination_transform,
            "nodata": -9999,
            "compress": "deflate",
            "predictor": 3,
            "tiled": True,
        }
        with rasterio.open(output_path, "w", **profile) as output:
            output.write(destination, 1)
            output.set_band_description(1, "Population per 100 m source cell, 2020")
            output.update_tags(
                source="GHSL GHS-POP R2023A, epoch 2020",
                resampling="area-average from 100 m equal-area cells",
            )
    LOG.info("Prepared population raster: %s", output_path)


def write_source_register(manifest: dict[str, dict[str, Any]]) -> None:
    rows = [
        (
            "Geofabrik Denmark extract boundary",
            "OpenStreetMap contributors; Geofabrik",
            GEOFABRIK_POLY,
            "Open Database License (ODbL) 1.0; attribution required",
            "EPSG:4326",
            "geofabrik_denmark_boundary",
        ),
        (
            "OpenStreetMap Denmark extract (GeoPackage export)",
            "OpenStreetMap contributors; Geofabrik",
            GEOFABRIK_GPKG,
            "Open Database License (ODbL) 1.0; attribution required",
            "EPSG:4326 (source); EPSG:25832 (processed)",
            "geofabrik_osm_gpkg",
        ),
        (
            "OpenStreetMap Denmark extract (PBF; power lines and gas pipelines)",
            "OpenStreetMap contributors; Geofabrik",
            GEOFABRIK_PBF,
            "Open Database License (ODbL) 1.0; attribution required",
            "EPSG:4326 (source); EPSG:25832 (processed)",
            "geofabrik_osm_denmark",
        ),
        (
            "OpenStreetMap coastline-derived land polygons",
            "OpenStreetMap contributors; osmdata.openstreetmap.de",
            LAND_POLYGONS,
            "ODbL 1.0; attribution required",
            "EPSG:4326 (source); EPSG:25832 (processed)",
            "osm_land_polygons",
        ),
        (
            "Natura 2000 Habitats Directive sites, version end 2024",
            "European Environment Agency",
            EEA_LAYER_URL.format(layer=0),
            "EEA reuse terms; attribution required; see dataset metadata",
            "EPSG:3035 (catalogue product); EPSG:25832 (query output)",
            "natura2000_0",
        ),
        (
            "Natura 2000 Birds Directive sites, version end 2024",
            "European Environment Agency",
            EEA_LAYER_URL.format(layer=1),
            "EEA reuse terms; attribution required; see dataset metadata",
            "EPSG:3035 (catalogue product); EPSG:25832 (query output)",
            "natura2000_1",
        ),
        (
            "Protected nature types (§3)",
            "Danmarks Miljøportal",
            "https://arealdata-api.miljoeportal.dk/datasets/"
            "urn:dmp:ds:beskyttede-naturtyper",
            "CC0 1.0",
            "EPSG:25832",
            "protected_nature",
        ),
        (
            "Fredede områder",
            "Danmarks Miljøportal",
            "https://arealdata-api.miljoeportal.dk/datasets/"
            "urn:dmp:ds:fredede-omraader",
            "CC0 1.0",
            "EPSG:25832",
            "protected_reserves",
        ),
        (
            "GHS-POP R2023A, epoch 2020, 100 m",
            "European Commission Joint Research Centre",
            POPULATION,
            "European Commission reuse notice; source acknowledgment required",
            "ESRI:54009 (source); EPSG:25832 (processed)",
            "ghsl_population_2020",
        ),
    ]
    for source_key, source in WFS_SOURCES.items():
        manifest_key = f"phase_b_{source_key}"
        if manifest_key not in manifest:
            continue
        rows.append(
            (
                f"{source['title']} ({source['typename']})",
                source["publisher"],
                source["endpoint"] + "?service=WFS&request=GetCapabilities",
                source["license"],
                f"{source['crs']} (source and processed)",
                manifest_key,
            )
        )
    for source in DEA_STORAGE_AREAS:
        rows.append(
            (
                f"DEA CO2 storage area: {source['name']}",
                "Danish Energy Agency (Energistyrelsen)",
                source["url"],
                "No licence stated; attribution: Danish Energy Agency "
                "(Energistyrelsen), CO2 storage licensing map",
                "EPSG:4326 (processed from the source layer)",
                f"dea_storage_area_{source['hotspot_id']}",
            )
        )
    content = [
        "# Data sources",
        "",
        "Acquisition date below is the date recorded by the download run. "
        "The raw files and a SHA-256 manifest are in the git-ignored "
        "`data/raw/` directory. Processed vector outputs use EPSG:25832; "
        "the population raster uses EPSG:25832 at 100 m.",
        "",
        "| Dataset | Publisher | Source URL | Licence / terms | Source CRS → processed CRS | Download date |",
        "|---|---|---|---|---|---|",
    ]
    for name, publisher, url, license_text, crs, manifest_key in rows:
        source_record = manifest.get(manifest_key)
        if source_record is None:
            raise ValueError(f"Missing acquisition provenance for {manifest_key!r}")
        download_date = source_record["download_date"] or "unknown (pre-existing file)"
        content.append(
            f"| {name} | {publisher} | <{url}> | {license_text} | {crs} | {download_date} |"
        )
    content.append(
        "| OpenStreetMap standard tiles (planned web basemap) | "
        "OpenStreetMap contributors | "
        "<https://tile.openstreetmap.org/{z}/{x}/{y}.png> | "
        "OSM tile policy; visible attribution, caching, no bulk download | "
        "EPSG:3857 | Not downloaded (runtime tiles) |"
    )
    content.extend(
        [
            "",
            "OSM roads and forest are extracted from Geofabrik's GeoPackage "
            "export. The phase-A power-line and gas-pipeline corridors are "
            "extracted from the PBF lines layer; power lines are limited to "
            "tagged `power=line` ways with voltage of at least 132 kV, and "
            "pipelines to `man_made=pipeline` ways tagged `substance=gas`.",
            "",
            "Phase-B WFS pages are retained in `data/raw/phase-b/`; "
            "Datafordeler request credentials are not included in the "
            "manifest or the saved pages.",
            "",
            "## Hotspot coordinates and project metadata",
            "",
            "The 18 candidate points in `data/input/hotspots.csv` are routing "
            "anchors, not surveyed pipeline endpoints or proof of commercial "
            "storage permission. Coordinates are stored in WGS84 (EPSG:4326). "
            "Storage exploration-area points are representative centroids or "
            "platform proxies; corresponding official DEA storage polygons "
            "are available in `data/processed/storage_areas.geojson`.",
            "",
            "| Information | Publisher | Reference URL | Terms / caveat | CRS / date |",
            "|---|---|---|---|---|",
            "| Gassum, Havnsø, Rødby, Stenlille and Thorning storage-area coordinates and statuses | Danish Energy Agency | <https://energidata.maps.arcgis.com/apps/instant/basic/index.html?appid=2bd1bfe3bf644cf4adbe683d2f3cad09> | Map item does not state licence terms; this project uses cited representative points only, not the polygons | DEA area centroids EPSG:25832 transformed to EPSG:4326; researched 2026-10-07 |",
            "| Inez, Lisa and Jammerbugt offshore storage-area coordinates | Danish Energy Agency | <https://energidata.maps.arcgis.com/apps/instant/basic/index.html?appid=2bd1bfe3bf644cf4adbe683d2f3cad09> | Designation/licence polygons are provided separately below; candidate points are polygon centroids | EPSG:4326; researched 2026-10-08 |",
            "| DEA CO2 storage licensing-map polygons (10 storage areas) | Danish Energy Agency (Energistyrelsen) | <https://energidata.maps.arcgis.com/apps/instant/basic/index.html?appid=2bd1bfe3bf644cf4adbe683d2f3cad09> | No licence stated; attribution: Danish Energy Agency (Energistyrelsen), CO2 storage licensing map | EPSG:4326; downloaded as source layers and written to `data/processed/storage_areas.geojson` |",
            "| Nini A and Harald platform coordinate proxies | FOGA | <https://www.foga.dk/en/foga-info-north-sea/totalenergies/haraldtrym/> | Approximate platform proxies; not surveyed injection points | WGS84 coordinates; researched 2026-10-07 |",
            "| EU ETS verified 2024 emissions | European Commission, DG CLIMA / Union Registry | <https://climate.ec.europa.eu/areas-action/carbon-markets/eu-emissions-trading-system-eu-ets/union-registry_en> | Fossil t CO2e; excludes biogenic CO2. Registry source terms apply; no source file redistributed | Not spatial; 2024 values from the 2026-04-01 extract cited in research notes |",
            "| Aalborg Portland capture contract | Danish Energy Agency | <https://ens.dk/forsyning-og-forbrug/ccs-udbud-og-anden-stoette-til-udvikling-af-ccs> | Planned capture, not operational volume | Not spatial; researched 2026-10-07 |",
            "| Ørsted Asnæs/Avedøre combined capture contract | Danish Energy Agency | <https://ens.dk/en/press/first-tender-ccus-subsidy-scheme-has-been-finalized-danish-energy-agency-awards-contract> | 430 kt/yr is combined; individual split is not verified; described as biogenic | Not spatial; researched 2026-10-07 |",
            "| Greenport Hirtshals capacity targets | Greenport Scandinavia | <https://greenportscandinavia.com/about/> | Targets, not captured volumes | Not spatial; researched 2026-10-07 |",
            "| Aalborg East terminal design capacity | Port of Aalborg | <https://portofaalborg.dk/en/new-co2-reception-facilities-will-make-aalborg-one-of-europes-leaders-in-carbon-management/> | Announced design capacity, not captured volume | Not spatial; researched 2026-10-07 |",
            "| Fjernvarme Fyn capture proposal | Fjernvarme Fyn | <https://www.fjernvarmefyn.dk/nyheder/fjernvarme-fyn-ansoeger-ikke-statens-ccs-pulje/> | Planned estimate; company did not apply to the state fund | Not spatial; researched 2026-10-07 |",
            "",
            "The extent uses the Geofabrik `denmark.poly` boundary as an "
            "approximation. Foreign OSM land inside the buffered analysis "
            "region is removed; a narrow strip may remain on the Danish side "
            "because the extract boundary is not a surveyed legal border. "
            "Foreign waters remain part of the sea routing area.",
        ]
    )
    content.extend(
        [
            "",
            "Additional source endpoints used by the downloader:",
            "",
            f"- Geofabrik Denmark extract boundary: <{GEOFABRIK_POLY}> (EPSG:4326).",
            "- Natura 2000 metadata: <https://sdi.eea.europa.eu/catalogue/"
            "datahub/api/records/91357f39-7866-41ce-b447-43905c364ec8>. "
            "The EEA REST query downloads Denmark's Habitat Directive and "
            "Birds Directive layers; output queries request EPSG:25832.",
            "- Danmarks Miljøportal distributes the §3 and fredede datasets "
            "as shapefile downloads and exposes EPSG:25832 WFS metadata.",
            "- GHSL's full 100 m global archive is retained in raw storage; "
            "only the buffered Denmark extent is reprojected to the processed "
            "raster.",
            "",
            "No download date is claimed until a source is actually downloaded. "
            "When multiple sources are downloaded on different days, update "
            "this register with their individual dates from "
            "`data/raw/acquisition-manifest.json`.",
            "",
        ]
    )
    SOURCES_FILE.parent.mkdir(parents=True, exist_ok=True)
    SOURCES_FILE.write_text("\n".join(content), encoding="utf-8")


def prepare_data(
    manifest: dict[str, dict[str, Any]],
    config_path: Path = CONFIG_FILE,
    layers: set[str] | None = None,
    resume: str | None = None,
) -> None:
    if resume == "phase_b":
        extent_path = PROCESSED / "coast_land_water.gpkg"
        if not extent_path.exists():
            raise FileNotFoundError(
                "Phase-B resume requires the completed base extent: "
                f"{extent_path}"
            )
        extent = gpd.read_file(
            extent_path, layer="analysis_extent"
        ).to_crs(TARGET_CRS)
        prepare_phase_b_layers(extent)
        prepare_storage_areas()
        write_source_register(manifest)
        LOG.info("Phase-B resume completed")
        return

    if layers is not None:
        extent_path = PROCESSED / "coast_land_water.gpkg"
        if not extent_path.exists():
            raise FileNotFoundError(
                "Phase-A layer extraction requires completed base preparation: "
                f"{extent_path}"
            )
        extent = gpd.read_file(
            extent_path, layer="analysis_extent"
        ).to_crs(TARGET_CRS)
        prepare_phase_a_layers(extent, layers)
        LOG.info("Selective phase-A layer preparation completed")
        return

    required = [
        RAW / "geofabrik" / "denmark.poly",
        RAW / "geofabrik" / "denmark-latest.osm.pbf",
        RAW / "geofabrik" / "denmark-latest-free.gpkg.zip",
        RAW / "osm-land" / "land-polygons-split-4326.zip",
        RAW / "miljoeportal" / "protected-nature.zip",
        RAW / "miljoeportal" / "protected-reserves.zip",
        RAW / "ghsl" / "population-2020-100m.zip",
        *(RAW / "eea" / name for name in EEA_LAYER_NAMES.values()),
    ]
    missing = [path for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError(
            "Missing raw source files; run the downloader first: "
            + ", ".join(str(path) for path in missing)
        )

    PROCESSED.mkdir(parents=True, exist_ok=True)
    with config_path.open(encoding="utf-8") as stream:
        config = yaml.safe_load(stream)
    corridor_half_width_m = float(
        config.get("routing", {}).get("offshore_corridor_half_width_m", 10_000)
    )
    extent, country_land, foreign_land = boundary_and_land(
        corridor_half_width_m=corridor_half_width_m
    )
    prepare_coast_and_extent(extent, country_land, foreign_land)
    prepare_osm(extent)
    prepare_phase_a_layers(extent, {"forest", "power_lines", "pipelines"})
    prepare_protected_areas(extent)
    prepare_natura2000(extent)
    prepare_population(extent)
    prepare_phase_b_layers(extent)
    prepare_storage_areas()
    if manifest:
        write_source_register(manifest)
    LOG.info("Data acquisition and preparation completed")


def load_manifest() -> dict[str, dict[str, Any]]:
    path = RAW / "acquisition-manifest.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Acquire and prepare the approved Denmark routing datasets."
    )
    operation = parser.add_mutually_exclusive_group()
    operation.add_argument(
        "--download-only",
        action="store_true",
        help="Download approved source files without processing them.",
    )
    operation.add_argument(
        "--prepare-only",
        action="store_true",
        help="Prepare existing raw files without downloading.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Redownload existing source files.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=CONFIG_FILE,
        help="YAML configuration containing the offshore corridor width.",
    )
    parser.add_argument(
        "--layers",
        type=lambda value: {
            layer.strip() for layer in value.split(",") if layer.strip()
        },
        metavar="LIST",
        help=(
            "Prepare only these phase-A layers (forest,power_lines,pipelines), "
            "plus major/minor roads. Requires --prepare-only."
        ),
    )
    parser.add_argument(
        "--resume",
        choices=["phase_b"],
        help=(
            "Resume only phase B from existing prepared base layers. "
            "Requires --prepare-only."
        ),
    )
    args = parser.parse_args()
    if args.layers and not args.prepare_only:
        parser.error("--layers requires --prepare-only")
    if args.resume and not args.prepare_only:
        parser.error("--resume requires --prepare-only")
    if args.resume and args.layers:
        parser.error("--resume cannot be combined with --layers")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if args.prepare_only:
        manifest = load_manifest()
    else:
        manifest = download_sources(force=args.force)
    if not args.download_only:
        prepare_data(manifest, args.config, args.layers, args.resume)


if __name__ == "__main__":
    main()
