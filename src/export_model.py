"""Export the 250 m browser model pack from prepared project inputs."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import logging
import math
from pathlib import Path
from typing import Any

import numpy as np
import pyogrio
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.warp import reproject
from scipy.ndimage import convolve, distance_transform_edt

from src.cost_surface import (
    PROCESSED,
    ROOT,
    landfall_cells,
    load_config,
    make_grid,
    parallel_corridor_mask,
    population_counts,
    rasterize_extent_and_land,
    rasterize_layer,
    validate_cost_scores,
)


LOG = logging.getLogger("export_model")
MODEL_DIR = ROOT / "web" / "data" / "model"
PACK_VERSION = 1
TRANSFER_TARGET_BYTES = 15_000_000
FLOAT_NODATA = -9999.0
DISTANCE_NODATA = np.iinfo(np.uint16).max


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode("utf-8")


def _write_json(path: Path, value: Any) -> dict[str, Any]:
    payload = _canonical_json_bytes(value)
    path.write_bytes(payload)
    return {
        "file": path.name,
        "dtype": "utf-8-json",
        "shape": None,
        "byte_order": "not-applicable",
        "order": "not-applicable",
        "compression": "none",
        "bytes": len(payload),
        "uncompressed_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _write_gzip_array(path: Path, array: np.ndarray) -> dict[str, Any]:
    dtype = array.dtype
    if dtype.kind in "iu" and dtype.itemsize > 1:
        dtype = dtype.newbyteorder("<")
    elif dtype.kind == "f":
        dtype = dtype.newbyteorder("<")
    values = np.ascontiguousarray(array, dtype=dtype)
    digest = hashlib.sha256()
    with path.open("wb") as raw_stream:
        with gzip.GzipFile(
            filename="",
            mode="wb",
            fileobj=raw_stream,
            compresslevel=6,
            mtime=0,
        ) as compressed_stream:
            for row in values:
                chunk = row.tobytes(order="C")
                digest.update(chunk)
                compressed_stream.write(chunk)
    return {
        "file": path.name,
        "dtype": values.dtype.name,
        "shape": list(values.shape),
        "byte_order": "little" if values.dtype.itemsize > 1 else "not-applicable",
        "order": "C-row-major",
        "compression": "gzip",
        "bytes": path.stat().st_size,
        "uncompressed_bytes": values.nbytes,
        "sha256": digest.hexdigest(),
        "compressed_sha256": _sha256_file(path),
    }


def _resample_average(
    source: np.ndarray,
    source_transform: rasterio.Affine,
    target_shape: tuple[int, int],
    target_transform: rasterio.Affine,
    crs: str,
) -> np.ndarray:
    destination = np.full(target_shape, -1.0, dtype=np.float32)
    reproject(
        source=np.asarray(source, dtype=np.float32),
        destination=destination,
        src_transform=source_transform,
        src_crs=crs,
        dst_transform=target_transform,
        dst_crs=crs,
        src_nodata=None,
        dst_nodata=-1.0,
        resampling=Resampling.average,
        init_dest_nodata=True,
    )
    destination[destination == -1.0] = 0.0
    return destination


def _resample_any(
    source: np.ndarray,
    source_transform: rasterio.Affine,
    target_shape: tuple[int, int],
    target_transform: rasterio.Affine,
    crs: str,
) -> np.ndarray:
    destination = np.full(target_shape, 255, dtype=np.uint8)
    reproject(
        source=np.asarray(source, dtype=np.uint8),
        destination=destination,
        src_transform=source_transform,
        src_crs=crs,
        dst_transform=target_transform,
        dst_crs=crs,
        src_nodata=None,
        dst_nodata=255,
        resampling=Resampling.max,
        init_dest_nodata=True,
    )
    return destination == 1


def _aggregate_layer_mask(
    source_mask: np.ndarray,
    geometry: str,
    source_transform: rasterio.Affine,
    target_shape: tuple[int, int],
    target_transform: rasterio.Affine,
    crs: str,
    area_threshold: float,
) -> np.ndarray:
    if geometry == "linear":
        return _resample_any(
            source_mask, source_transform, target_shape, target_transform, crs
        )
    if geometry == "polygon":
        return _resample_average(
            source_mask, source_transform, target_shape, target_transform, crs
        ) >= area_threshold
    raise ValueError(f"Unsupported layer geometry: {geometry}")


def _layer_source(
    name: str,
    layer_config: dict[str, Any],
    available_inputs: dict[str, set[str]],
    config: dict[str, Any],
    source_transform: rasterio.Affine,
    source_width: int,
    source_height: int,
    source_extent: np.ndarray,
    source_land: np.ndarray,
    source_buildings: np.ndarray,
    crs: str,
) -> tuple[np.ndarray | None, bool]:
    source_path = PROCESSED / str(layer_config["file"])
    source_layer = str(layer_config["layer"])
    source_layers = available_inputs.get(str(source_path.resolve()), set())
    available = source_path.exists() and source_layer in source_layers
    if not available:
        if layer_config.get("optional", False):
            LOG.warning("Optional model layer is unavailable: %s", name)
            return None, False
        if not source_path.exists():
            raise FileNotFoundError(
                f"Required processed input is missing for {name}: {source_path}"
            )
        raise ValueError(
            f"Required source layer {source_layer!r} is missing from {source_path}"
        )

    geometry = str(layer_config["geometry"])
    if geometry not in {"linear", "polygon"}:
        raise ValueError(f"Unsupported geometry for layer {name!r}: {geometry}")
    all_touched = bool(
        config["rasterization"][
            "linear_all_touched" if geometry == "linear" else "polygon_all_touched"
        ]
    )
    mask = rasterize_layer(
        source_path,
        source_layer,
        source_transform,
        source_width,
        source_height,
        all_touched,
        crs,
    ).astype(bool)
    mask &= source_extent
    mask &= ~source_buildings
    if layer_config.get("surface", "any") == "land":
        mask &= source_land
    elif layer_config.get("surface", "any") != "any":
        raise ValueError(
            f"Unsupported surface constraint for layer {name!r}: "
            f"{layer_config.get('surface')!r}"
        )
    return mask, all_touched


def _available_source_layers(config: dict[str, Any]) -> dict[str, set[str]]:
    paths = {
        (PROCESSED / str(layer["file"])).resolve()
        for layer in config["layers"].values()
    }
    paths.update(
        (PROCESSED / str(asset["file"])).resolve()
        for asset in config.get("parallel_corridor", {}).get("assets", [])
    )
    paths.add((PROCESSED / "water_and_urban.gpkg").resolve())
    available: dict[str, set[str]] = {}
    for path in paths:
        if path.exists():
            available[str(path)] = {
                str(row[0]) for row in pyogrio.list_layers(path)
            }
        else:
            available[str(path)] = set()
    return available


def _aligned_window_grid(
    full_bounds: tuple[float, float, float, float],
    resolution: int,
    requested_bounds: tuple[float, float, float, float],
) -> tuple[rasterio.Affine, int, int, tuple[float, float, float, float]]:
    xmin, ymin, xmax, ymax = requested_bounds
    if not all(math.isfinite(value) for value in requested_bounds):
        raise ValueError("Bounding-box coordinates must be finite")
    if xmin >= xmax or ymin >= ymax:
        raise ValueError("Bounding box must have positive width and height")
    full_left, full_bottom, full_right, full_top = full_bounds
    left = max(full_left, math.floor(xmin / resolution) * resolution)
    bottom = max(full_bottom, math.floor(ymin / resolution) * resolution)
    right = min(full_right, math.ceil(xmax / resolution) * resolution)
    top = min(full_top, math.ceil(ymax / resolution) * resolution)
    if left >= right or bottom >= top:
        raise ValueError("Requested bounding box does not overlap the analysis grid")
    width = int(round((right - left) / resolution))
    height = int(round((top - bottom) / resolution))
    return (
        from_origin(left, top, resolution, resolution),
        width,
        height,
        (left, bottom, right, top),
    )


def _check_configured_layer_bits(config: dict[str, Any]) -> None:
    layer_count = len(config["layers"])
    if layer_count + 5 > 64:
        raise ValueError(
            "The browser pack supports at most 59 source layers plus five "
            f"derived flags; configured layer count is {layer_count}"
        )


def export_model(
    config_path: Path = ROOT / "config" / "costs.yaml",
    output_dir: Path = MODEL_DIR,
    bbox: tuple[float, float, float, float] | None = None,
) -> dict[str, Any]:
    """Create a gzip-compressed, self-describing 250 m model pack."""
    config_path = config_path.resolve()
    config = load_config(config_path)
    _check_configured_layer_bits(config)
    derived_costs = (
        {str(config["landfall"]["cost"])}
        if config.get("landfall", {}).get("enabled", False)
        else set()
    )
    validate_cost_scores(
        config["costs"],
        config["layers"],
        [str(name) for name in config.get("barriers", [])],
        float(config.get("score_minimum", 1)),
        derived_costs,
    )
    grid_config = config["grid"]
    browser_config = config["browser_model"]
    if int(grid_config["cost_reference_resolution_m"]) <= 0:
        raise ValueError("Cost reference resolution must be positive")
    crs = str(grid_config["crs"])
    resolution = int(browser_config["resolution_m"])
    source_resolution = int(browser_config["source_resolution_m"])
    area_threshold = float(browser_config["area_presence_threshold"])
    share_scale = int(browser_config["building_share_scale"])
    building_threshold = int(browser_config["building_barrier_share_threshold"])
    tie_break = str(browser_config["land_sea_tie_break"])
    if source_resolution <= 0 or resolution <= 0:
        raise ValueError("Browser model grid resolutions must be positive")
    if not 0 < area_threshold <= 1:
        raise ValueError("Area-presence threshold must be in (0, 1]")
    if not 0 < share_scale <= np.iinfo(np.uint8).max:
        raise ValueError("Building-share scale must fit a positive uint8 value")
    if not 0 < building_threshold <= share_scale:
        raise ValueError("Building barrier threshold must be within share scale")
    if tie_break not in {"land", "sea"}:
        raise ValueError("Land/sea tie break must be 'land' or 'sea'")
    if (
        str(browser_config["area_resampling"]) != "average"
        or str(browser_config["linear_resampling"]) != "max"
    ):
        raise ValueError(
            "Browser aggregation supports average area and max/any linear resampling"
        )
    if str(config["costs"]["population_risk"].get("kernel", "circular")) != "circular":
        raise ValueError("Browser population-risk input supports a circular kernel")
    proximity_settings = config["costs"].get("dwelling_proximity", {})
    if (
        proximity_settings.get("enabled", True)
        and str(proximity_settings.get("distance_metric", "euclidean"))
        != "euclidean"
    ):
        raise ValueError("Dwelling proximity supports Euclidean distance only")
    routing_settings = config.get("routing", {})
    if (
        str(routing_settings.get("path_method", "MCP_Geometric"))
        != "MCP_Geometric"
        or not bool(routing_settings.get("fully_connected", True))
        or str(routing_settings.get("snap_distance_metric", "euclidean"))
        != "euclidean"
    ):
        raise ValueError(
            "The browser pack requires fully-connected MCP_Geometric routing "
            "and Euclidean hotspot snapping"
        )
    reference_resolution = int(grid_config["cost_reference_resolution_m"])
    cost_scale = resolution / reference_resolution
    if not math.isfinite(cost_scale) or cost_scale <= 0:
        raise ValueError("Invalid cost scale for the browser grid")

    extent_path = PROCESSED / "coast_land_water.gpkg"
    source_transform, source_width, source_height, full_source_bounds = make_grid(
        extent_path, source_resolution, crs
    )
    target_transform, width, height, full_target_bounds = make_grid(
        extent_path, resolution, crs
    )
    bounds = full_target_bounds
    if bbox is not None:
        target_transform, width, height, bounds = _aligned_window_grid(
            full_target_bounds, resolution, bbox
        )
        source_transform, source_width, source_height, _ = _aligned_window_grid(
            full_source_bounds, source_resolution, bounds
        )
    target_shape = (height, width)
    source_extent, source_land = rasterize_extent_and_land(
        source_transform,
        source_width,
        source_height,
        crs,
        bool(config["rasterization"]["polygon_all_touched"]),
        bool(config["rasterization"]["extent_all_touched"]),
    )
    source_land &= source_extent
    source_sea = source_extent & ~source_land

    building_config = config["rasterization"]
    source_buildings = rasterize_layer(
        PROCESSED / "water_and_urban.gpkg",
        "buildings",
        source_transform,
        source_width,
        source_height,
        bool(building_config["polygon_all_touched"]),
        crs,
    ).astype(bool)
    source_buildings &= source_extent

    target_extent, _ = rasterize_extent_and_land(
        target_transform,
        width,
        height,
        crs,
        bool(config["rasterization"]["polygon_all_touched"]),
        bool(config["rasterization"]["extent_all_touched"]),
    )
    land_fraction = _resample_average(
        source_land, source_transform, target_shape, target_transform, crs
    )
    sea_fraction = _resample_average(
        source_sea, source_transform, target_shape, target_transform, crs
    )
    land_dominates = (
        land_fraction >= sea_fraction
        if tie_break == "land"
        else land_fraction > sea_fraction
    )
    target_land = target_extent & land_dominates
    target_sea = target_extent & ~target_land

    buildings_share = np.rint(
        np.clip(
            _resample_average(
                source_buildings,
                source_transform,
                target_shape,
                target_transform,
                crs,
            ),
            0,
            1,
        )
        * share_scale
    ).astype(np.uint8)
    building_mask = buildings_share >= building_threshold

    if np.any(building_mask):
        distance_m = distance_transform_edt(
            ~building_mask, sampling=(resolution, resolution)
        )
        building_distance = np.minimum(
            np.rint(distance_m), DISTANCE_NODATA - 1
        ).astype(np.uint16)
    else:
        building_distance = np.full(
            target_shape, DISTANCE_NODATA, dtype=np.uint16
        )
    building_distance[~target_extent] = DISTANCE_NODATA

    population = population_counts(
        target_extent, target_transform, width, height, crs, resolution
    )
    population_1km = _population_risk_inputs(
        population, resolution, config["costs"].get("population_risk", {})
    )

    available_inputs = _available_source_layers(config)
    layer_names = sorted(config["layers"])
    bit_names: dict[str, int] = {
        name: index for index, name in enumerate(layer_names)
    }
    derived_bits = {
        "land": len(layer_names),
        "sea": len(layer_names) + 1,
        "buildings": len(layer_names) + 2,
        "landfall": len(layer_names) + 3,
        "parallel_band": len(layer_names) + 4,
    }
    presence = np.zeros((2, height, width), dtype="<u4")
    layer_metadata: list[dict[str, Any]] = []
    barrier_masks: dict[str, np.ndarray] = {}
    parallel_assets = np.zeros(target_shape, dtype=bool)
    for name in layer_names:
        layer_config = config["layers"][name]
        mask100, all_touched = _layer_source(
            name,
            layer_config,
            available_inputs,
            config,
            source_transform,
            source_width,
            source_height,
            source_extent,
            source_land,
            source_buildings,
            crs,
        )
        available = mask100 is not None
        mask250 = np.zeros(target_shape, dtype=bool)
        if mask100 is not None:
            mask250 = _aggregate_layer_mask(
                mask100,
                str(layer_config["geometry"]),
                source_transform,
                target_shape,
                target_transform,
                crs,
                area_threshold,
            )
            mask250 &= target_extent & ~building_mask
            surface = layer_config.get("surface", "any")
            if surface == "land":
                mask250 &= target_land
            cost_key = str(layer_config["cost"])
            if cost_key in config.get("barriers", []):
                barrier_masks[cost_key] = (
                    barrier_masks.get(cost_key, np.zeros(target_shape, dtype=bool))
                    | mask250
                )
            elif cost_key not in config["costs"]:
                raise ValueError(
                    f"Layer {name!r} uses undefined cost class {cost_key!r}"
                )
            if layer_config.get("parallel_asset", False):
                parallel_assets |= mask250

        bit = bit_names[name]
        if available:
            _set_presence_bit(presence, mask250, bit)
        layer_metadata.append(
            {
                "name": name,
                "bit": bit,
                "cost": str(layer_config["cost"]),
                "surface": str(layer_config.get("surface", "any")),
                "geometry": str(layer_config["geometry"]),
                "all_touched": bool(all_touched) if all_touched is not None else None,
                "available": available,
                "optional": bool(layer_config.get("optional", False)),
                "default_action": (
                    "barrier"
                    if str(layer_config["cost"]) in config.get("barriers", [])
                    else "cost"
                ),
            }
        )
        LOG.info(
            "Prepared layer %s (%s, %s)",
            name,
            "available" if available else "unavailable",
            int(np.count_nonzero(mask250)),
        )

    _set_presence_bit(presence, target_land, derived_bits["land"])
    _set_presence_bit(presence, target_sea, derived_bits["sea"])
    _set_presence_bit(presence, buildings_share > 0, derived_bits["buildings"])
    landfall_config = config.get("landfall", {})
    landfall_mask = (
        landfall_cells(
            target_land & ~building_mask,
            target_sea,
            target_extent,
            int(landfall_config.get("connectivity", 8)),
        )
        if landfall_config.get("enabled", False)
        else np.zeros(target_shape, dtype=bool)
    )
    _set_presence_bit(presence, landfall_mask, derived_bits["landfall"])
    parallel_mask = _parallel_band(
        config,
        available_inputs,
        target_transform,
        target_shape,
        target_extent,
        building_mask,
        barrier_masks,
        parallel_assets,
        crs,
    )
    _set_presence_bit(presence, parallel_mask, derived_bits["parallel_band"])

    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    lo = presence[0].copy()
    hi = presence[1].copy()
    low_path = output_dir / "presence_lo.bin.gz"
    high_path = output_dir / "presence_hi.bin.gz"
    files = [
        _write_gzip_array(low_path, lo),
        _write_gzip_array(high_path, hi),
    ]
    float_population = np.where(
        np.isfinite(population) & target_extent, population, FLOAT_NODATA
    ).astype("<f4")
    float_risk = np.where(
        np.isfinite(population_1km) & target_extent,
        population_1km,
        FLOAT_NODATA,
    ).astype("<f4")
    files.extend(
        [
            _write_gzip_array(output_dir / "population.bin.gz", float_population),
            _write_gzip_array(
                output_dir / "population_1km.bin.gz", float_risk
            ),
            _write_gzip_array(
                output_dir / "building_distance.bin.gz", building_distance
            ),
            _write_gzip_array(
                output_dir / "buildings_share.bin.gz", buildings_share
            ),
            _write_gzip_array(
                output_dir / "parallel.bin.gz", parallel_mask.astype(np.uint8)
            ),
            _write_gzip_array(
                output_dir / "landfall.bin.gz", landfall_mask.astype(np.uint8)
            ),
        ]
    )

    effective_config_bytes = _canonical_json_bytes(config)
    effective_config_hash = hashlib.sha256(effective_config_bytes).hexdigest()
    source_config_hash = _sha256_file(config_path)
    grid_document = {
        "crs": crs,
        "resolution_m": resolution,
        "source_resolution_m": source_resolution,
        "area_presence_threshold": area_threshold,
        "area_resampling": str(browser_config["area_resampling"]),
        "linear_resampling": str(browser_config["linear_resampling"]),
        "building_share_scale": share_scale,
        "cost_reference_resolution_m": reference_resolution,
        "cost_scale": cost_scale,
        "width": width,
        "height": height,
        "bounds": list(bounds),
        "transform_gdal": list(target_transform.to_gdal()),
        "row_order": "north-to-south",
        "column_order": "west-to-east",
        "array_order": "C-row-major",
        "extent_mask": "land and sea bits are both clear outside extent",
        "barrier_mask": (
            f"buildings_share threshold >={building_threshold}/{share_scale} "
            "plus configured barrier layers"
        ),
        "float_nodata": FLOAT_NODATA,
        "distance_nodata": int(DISTANCE_NODATA),
        "building_barrier_share_threshold": building_threshold,
        "land_sea_tie_break": tie_break,
        "routing_method": str(
            config.get("routing", {}).get("path_method", "MCP_Geometric")
        ),
        "routing_fully_connected": bool(
            config.get("routing", {}).get("fully_connected", True)
        ),
        "browser_adjustable_parameter_paths": [
            "costs.<numeric cost key>",
            "costs.dwelling_proximity.enabled",
            "costs.dwelling_proximity.max_distance_m",
            "costs.dwelling_proximity.max_score",
            "costs.population.enabled",
            "costs.population.min_per_cell",
            "costs.population.minimum",
            "costs.population.maximum",
            "costs.population.quantiles",
            "costs.population_risk.enabled",
            "costs.population_risk.threshold_people",
            "costs.population_risk.maximum",
            "costs.population_risk.quantiles",
            "parallel_corridor.factor",
            "barriers",
            "combine_groups",
            "discount_classes",
        ],
        "pack_rebuild_required_for": [
            "grid.crs",
            "browser_model.*",
            "rasterization.*",
            "layers.*",
            "costs.population_risk.radius_m",
            "costs.population_risk.kernel",
            "landfall.enabled",
            "landfall.connectivity",
            "parallel_corridor.enabled",
            "parallel_corridor.assets",
            "parallel_corridor.exclude_osm_ids",
            "parallel_corridor.inner_distance_m",
            "parallel_corridor.outer_distance_m",
        ],
        "precomputed": [
            {
                "parameter": "browser_model.source_resolution_m",
                "value": source_resolution,
                "reason": "Source geometry masks are rasterized at this resolution before 250 m aggregation.",
                "browser_adjustable": False,
                "requires_reexport": True,
            },
            {
                "parameter": "browser_model.resolution_m",
                "value": resolution,
                "reason": "The browser cost grid and routes use this fixed grid resolution.",
                "browser_adjustable": False,
                "requires_reexport": True,
            },
            {
                "parameter": "browser_model.area_presence_threshold",
                "value": area_threshold,
                "reason": (
                    "Area-layer masks are aggregated from source-resolution "
                    f"({source_resolution} m) raster coverage."
                ),
                "browser_adjustable": False,
                "requires_reexport": True,
            },
            {
                "parameter": "browser_model.area_resampling",
                "value": str(browser_config["area_resampling"]),
                "reason": "Area-layer coverage masks are precomputed.",
                "browser_adjustable": False,
                "requires_reexport": True,
            },
            {
                "parameter": "browser_model.linear_resampling",
                "value": str(browser_config["linear_resampling"]),
                "reason": "Linear-layer any-hit masks are precomputed.",
                "browser_adjustable": False,
                "requires_reexport": True,
            },
            {
                "parameter": "building_distance.threshold",
                "value": building_threshold,
                "config_parameter": (
                    "browser_model.building_barrier_share_threshold"
                ),
                "file": "building_distance.bin.gz",
                "reason": "This threshold creates both the building barrier and the precomputed distance plane.",
                "browser_adjustable": False,
                "requires_reexport": True,
            },
            {
                "parameter": "browser_model.building_share_scale",
                "value": share_scale,
                "reason": "Building coverage is quantized to this uint8 scale.",
                "browser_adjustable": False,
                "requires_reexport": True,
            },
            {
                "parameter": "browser_model.land_sea_tie_break",
                "value": tie_break,
                "reason": "Land and sea presence bits are already classified in the pack.",
                "browser_adjustable": False,
                "requires_reexport": True,
            },
            {
                "parameter": "rasterization",
                "value": config["rasterization"],
                "reason": "Source-layer presence masks are rasterized before export.",
                "browser_adjustable": False,
                "requires_reexport": True,
            },
            {
                "parameter": "landfall.enabled",
                "value": bool(landfall_config.get("enabled", False)),
                "reason": "Landfall presence is precomputed.",
                "browser_adjustable": False,
                "requires_reexport": True,
            },
            {
                "parameter": "parallel_corridor.enabled",
                "value": bool(
                    config.get("parallel_corridor", {}).get("enabled", False)
                ),
                "reason": "The parallel band is precomputed.",
                "browser_adjustable": False,
                "requires_reexport": True,
            },
            {
                "parameter": "costs.population_risk.radius_m",
                "value": float(config["costs"]["population_risk"]["radius_m"]),
                "file": "population_1km.bin.gz",
                "reason": "Population-risk neighbourhood is precomputed in population_1km.bin.gz.",
                "browser_adjustable": False,
                "requires_reexport": True,
            },
            {
                "parameter": "landfall.connectivity",
                "value": int(landfall_config.get("connectivity", 8)),
                "reason": "Landfall presence is precomputed from the configured neighbourhood.",
                "browser_adjustable": False,
                "requires_reexport": True,
            },
            {
                "parameter": "parallel_corridor.inner_distance_m",
                "value": float(
                    config.get("parallel_corridor", {}).get("inner_distance_m", 0)
                ),
                "file": "parallel.bin.gz",
                "reason": (
                    "The parallel band is precomputed from configured assets "
                    "and distance limits."
                ),
                "browser_adjustable": False,
                "requires_reexport": True,
            },
            {
                "parameter": "parallel_corridor.outer_distance_m",
                "value": float(
                    config.get("parallel_corridor", {}).get("outer_distance_m", 0)
                ),
                "file": "parallel.bin.gz",
                "reason": (
                    "The parallel band is precomputed from configured assets "
                    "and distance limits."
                ),
                "browser_adjustable": False,
                "requires_reexport": True,
            },
        ],
        "requested_bbox_epsg25832": list(bbox) if bbox is not None else None,
        "is_smoke_subset": bbox is not None,
    }
    layer_document = {
        "bitplanes": {
            "low": {"file": "presence_lo.bin.gz", "dtype": "uint32", "bits": [0, 31]},
            "high": {"file": "presence_hi.bin.gz", "dtype": "uint32", "bits": [32, 63]},
        },
        "layers": layer_metadata,
        "derived": [
            {"name": "land", "bit": derived_bits["land"], "cost": "open_land"},
            {"name": "sea", "bit": derived_bits["sea"], "cost": "open_sea"},
            {
                "name": "buildings",
                "bit": derived_bits["buildings"],
                "cost": "building_barrier",
                "default_action": "barrier",
                "share_file": "buildings_share.bin.gz",
            },
            {
                "name": "landfall",
                "bit": derived_bits["landfall"],
                "cost": str(landfall_config.get("cost", "landfall")),
                "default_action": "cost",
                "connectivity": int(landfall_config.get("connectivity", 8)),
            },
            {
                "name": "parallel_band",
                "bit": derived_bits["parallel_band"],
                "factor": float(
                    config.get("parallel_corridor", {}).get("factor", 1.0)
                ),
                "inner_distance_m": float(
                    config.get("parallel_corridor", {}).get("inner_distance_m", 0)
                ),
                "outer_distance_m": float(
                    config.get("parallel_corridor", {}).get("outer_distance_m", 0)
                ),
                "browser_adjustable_distances": False,
            },
        ],
        "continuous": {
            "buildings_share": {
                "file": "buildings_share.bin.gz",
                "dtype": "uint8",
                "scale": share_scale,
                "meaning": (
                    "fraction of source-resolution building cells represented "
                    "in this browser-grid cell"
                ),
            },
            "building_distance": {
                "file": "building_distance.bin.gz",
                "dtype": "uint16",
                "units": "metres",
                "nodata": int(DISTANCE_NODATA),
            },
            "population": {
                "file": "population.bin.gz",
                "dtype": "float32",
                "units": f"people per {resolution} m cell",
                "nodata": FLOAT_NODATA,
            },
            "population_1km": {
                "file": "population_1km.bin.gz",
                "dtype": "float32",
                "units": "people within configured circular radius",
                "radius_m": float(config["costs"]["population_risk"]["radius_m"]),
                "kernel": str(
                    config["costs"]["population_risk"].get("kernel", "circular")
                ),
                "browser_adjustable": False,
                "requires_reexport": True,
                "nodata": FLOAT_NODATA,
            },
            "parallel": {
                "file": "parallel.bin.gz",
                "dtype": "uint8",
                "meaning": f"1 inside the configured {resolution} m parallel corridor",
            },
            "landfall": {
                "file": "landfall.bin.gz",
                "dtype": "uint8",
                "meaning": (
                    "1 on land cells adjacent to sea in the configured "
                    f"{int(landfall_config.get('connectivity', 8))}-neighbourhood"
                ),
            },
        },
    }
    files.extend(
        [
            _write_json(output_dir / "grid.json", grid_document),
            _write_json(output_dir / "config.json", config),
            _write_json(output_dir / "layers.json", layer_document),
        ]
    )
    manifest = {
        "version": PACK_VERSION,
        "source_config": (
            str(config_path.relative_to(ROOT))
            if config_path.is_relative_to(ROOT)
            else str(config_path)
        ),
        "source_config_sha256": source_config_hash,
        "effective_config_sha256": effective_config_hash,
        "aggregation": {
            "area_layers": (
                f"average source-grid coverage >= {area_threshold}"
            ),
            "linear_layers": "any source-grid raster hit",
            "land_sea": (
                f"majority of {source_resolution} m land versus sea coverage; "
                f"target extent from {resolution} m grid; ties to {tie_break}"
            ),
            "buildings": (
                f"uint8 rounded mean coverage; barrier at "
                f">={building_threshold}/{share_scale}"
            ),
        },
        "export_window": {
            "requested_bbox_epsg25832": list(bbox) if bbox is not None else None,
            "grid_bounds": list(bounds),
            "is_smoke_subset": bbox is not None,
        },
        "files": files,
        "transfer_target_bytes": TRANSFER_TARGET_BYTES,
    }
    manifest_entry = _write_json(output_dir / "manifest.json", manifest)
    transfer_bytes = sum(entry["bytes"] for entry in files) + manifest_entry["bytes"]
    summary = {
        "output_dir": str(output_dir),
        "shape": [height, width],
        "crs": crs,
        "resolution_m": resolution,
        "layers": len(layer_metadata),
        "available_layers": sum(row["available"] for row in layer_metadata),
        "files": len(files) + 1,
        "transfer_bytes": transfer_bytes,
        "transfer_target_bytes": TRANSFER_TARGET_BYTES,
        "within_transfer_target": transfer_bytes <= TRANSFER_TARGET_BYTES,
        "source_config_sha256": source_config_hash,
        "effective_config_sha256": effective_config_hash,
        "bbox_epsg25832": list(bbox) if bbox is not None else None,
        "is_smoke_subset": bbox is not None,
    }
    LOG.info("Browser model pack: %s", json.dumps(summary, sort_keys=True))
    if transfer_bytes > TRANSFER_TARGET_BYTES:
        LOG.warning(
            "Compressed model pack is %s bytes, over the %s-byte target",
            transfer_bytes,
            TRANSFER_TARGET_BYTES,
        )
    return summary


def _set_presence_bit(
    presence: np.ndarray, mask: np.ndarray, bit: int
) -> None:
    plane_index, bit_offset = divmod(bit, 32)
    value = np.uint32(1 << bit_offset)
    presence[plane_index, mask] |= value


def _population_risk_inputs(
    population: np.ndarray,
    resolution_m: int,
    settings: dict[str, Any],
) -> np.ndarray:
    radius = float(settings["radius_m"])
    kernel_shape = str(settings["kernel"])
    if (
        not math.isfinite(radius)
        or radius <= 0
        or resolution_m <= 0
        or kernel_shape != "circular"
    ):
        raise ValueError("Invalid population-risk settings for model pack")
    radius_cells = int(math.ceil(radius / resolution_m))
    offsets = np.arange(-radius_cells, radius_cells + 1, dtype=np.int32)
    rows, cols = np.meshgrid(offsets, offsets, indexing="ij")
    kernel = (
        (rows * resolution_m) ** 2 + (cols * resolution_m) ** 2 <= radius**2
    ).astype(np.float32)
    focal_population = convolve(
        np.where(np.isfinite(population), population, 0).astype(np.float32),
        kernel,
        mode="constant",
        cval=0,
    ).astype(np.float32)
    return focal_population


def _parallel_band(
    config: dict[str, Any],
    available_inputs: dict[str, set[str]],
    transform: rasterio.Affine,
    shape: tuple[int, int],
    extent_mask: np.ndarray,
    building_mask: np.ndarray,
    barrier_masks: dict[str, np.ndarray],
    parallel_assets: np.ndarray,
    crs: str,
) -> np.ndarray:
    settings = config.get("parallel_corridor", {})
    if not settings.get("enabled", False):
        return np.zeros(shape, dtype=bool)
    if str(settings.get("distance_metric", "euclidean")) != "euclidean":
        raise ValueError("Parallel corridor supports Euclidean distance only")
    factor = float(settings["factor"])
    if not 0 < factor <= 1:
        raise ValueError("Parallel corridor factor must be in (0, 1]")
    assets = parallel_assets.copy()
    excluded_ids = sorted(
        {str(identifier) for identifier in settings.get("exclude_osm_ids", [])}
    )
    for asset in settings.get("assets", []):
        source_path = PROCESSED / str(asset["file"])
        source_layer = str(asset["layer"])
        layer_names = available_inputs.get(str(source_path.resolve()), set())
        if not source_path.exists() or source_layer not in layer_names:
            raise FileNotFoundError(
                f"Required parallel-corridor input is missing: "
                f"{source_path}:{source_layer}"
            )
        assets |= rasterize_layer(
            source_path,
            source_layer,
            transform,
            shape[1],
            shape[0],
            bool(config["rasterization"]["linear_all_touched"]),
            crs,
            excluded_ids,
        ).astype(bool)
    assets &= extent_mask
    barriers = np.zeros(shape, dtype=bool)
    for mask in barrier_masks.values():
        barriers |= mask
    valid_surface = extent_mask & ~building_mask & ~barriers
    corridor = parallel_corridor_mask(
        assets,
        valid_surface,
        int(config["browser_model"]["resolution_m"]),
        float(settings["inner_distance_m"]),
        float(settings["outer_distance_m"]),
    )
    corridor &= ~assets
    return corridor


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export the configurable 250 m browser model pack."
    )
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "costs.yaml")
    parser.add_argument("--output", type=Path, default=MODEL_DIR)
    parser.add_argument(
        "--bbox",
        nargs=4,
        type=float,
        metavar=("XMIN", "YMIN", "XMAX", "YMAX"),
        help="Optional EPSG:25832 bounding-box subset for smoke exports.",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(message)s",
    )
    bbox = tuple(args.bbox) if args.bbox is not None else None
    result = export_model(args.config, args.output, bbox)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
