"""Download, clip, and reproject approved source data for the routing study."""

from __future__ import annotations

import argparse
import csv
import gc
import hashlib
import json
import logging
import math
import re
import shutil
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pyogrio
import rasterio
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
    MultiPolygon,
    Point,
    Polygon,
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
            if extent_geometry.covers(storage_point):
                continue
            coastal_point = nearest_points(land_geometry, storage_point)[0]
            corridors.append(
                LineString([coastal_point, storage_point]).buffer(
                    corridor_half_width_m
                )
            )
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
            "## Hotspot coordinates and project metadata",
            "",
            "The 15 candidate points in `data/input/hotspots.csv` are routing "
            "anchors, not surveyed pipeline endpoints or proof of commercial "
            "storage permission. Coordinates are stored in WGS84 (EPSG:4326). "
            "Storage exploration-area points are representative centroids or "
            "platform proxies; the underlying DEA licensing polygons are not "
            "redistributed.",
            "",
            "| Information | Publisher | Reference URL | Terms / caveat | CRS / date |",
            "|---|---|---|---|---|",
            "| Gassum, Havnsø, Rødby, Stenlille and Thorning storage-area coordinates and statuses | Danish Energy Agency | <https://energidata.maps.arcgis.com/apps/instant/basic/index.html?appid=2bd1bfe3bf644cf4adbe683d2f3cad09> | Map item does not state licence terms; this project uses cited representative points only, not the polygons | DEA area centroids EPSG:25832 transformed to EPSG:4326; researched 2026-10-07 |",
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
) -> None:
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
    prepare_protected_areas(extent)
    prepare_natura2000(extent)
    prepare_population(extent)
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
    args = parser.parse_args()
    if args.layers and not args.prepare_only:
        parser.error("--layers requires --prepare-only")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if args.prepare_only:
        manifest = load_manifest()
    else:
        manifest = download_sources(force=args.force)
    if not args.download_only:
        prepare_data(manifest, args.config, args.layers)


if __name__ == "__main__":
    main()
