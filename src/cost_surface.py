"""Build the configurable least-cost routing surface."""

from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import re
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pyogrio
import rasterio
import yaml
from scipy.ndimage import binary_dilation, convolve, distance_transform_edt
from rasterio.features import rasterize
from rasterio.transform import from_origin
from rasterio.warp import Resampling, reproject
from shapely.geometry.base import BaseGeometry

from src.freshness import config_fingerprint


ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"
CONFIG = ROOT / "config" / "costs.yaml"
LOG = logging.getLogger("cost_surface")
BATCH_SIZE = 50_000


def path_for_metadata(path: Path) -> str:
    resolved_path = path.resolve()
    try:
        return str(resolved_path.relative_to(ROOT))
    except ValueError:
        return str(resolved_path)


def load_config(path: Path = CONFIG) -> dict[str, Any]:
    def load(current_path: Path, seen: set[Path]) -> dict[str, Any]:
        resolved_path = current_path.resolve()
        if resolved_path in seen:
            raise ValueError(f"Configuration inheritance cycle at {current_path}")
        with current_path.open(encoding="utf-8") as stream:
            current = yaml.safe_load(stream)
        if not isinstance(current, dict):
            raise ValueError(f"Expected a YAML mapping in {current_path}")
        base_name = current.pop("extends", None)
        replace_sections = set(current.pop("replace_sections", []))
        if base_name is None:
            return current
        base = load(
            current_path.parent / str(base_name), seen | {resolved_path}
        )

        def merge(destination: dict[str, Any], overlay: dict[str, Any]) -> None:
            for key, value in overlay.items():
                if (
                    key in replace_sections
                    or key not in destination
                    or not isinstance(value, dict)
                    or not isinstance(destination[key], dict)
                ):
                    destination[key] = value
                else:
                    merge(destination[key], value)

        merge(base, current)
        return base

    return load(path, set())


def validate_cost_scores(
    costs: dict[str, Any],
    layers: dict[str, Any],
    barriers: list[str],
    minimum_score: float = 1,
    additional_cost_names: set[str] | None = None,
) -> None:
    barrier_names = set(barriers)
    score_names = {"open_land", "open_sea", "building_barrier"}
    score_names.update(
        str(layer["cost"])
        for layer in layers.values()
        if "cost" in layer and str(layer["cost"]) not in barrier_names
    )
    score_names.update(additional_cost_names or set())
    for name in sorted(score_names):
        if name not in costs:
            raise ValueError(f"Missing configured cost score for {name!r}")
        score = float(costs[name])
        if (
            not math.isfinite(score)
            or not minimum_score <= score <= 10
        ):
            raise ValueError(
                f"Cost score for {name!r} must be between "
                f"{minimum_score:g} and 10"
            )

    population = costs.get("population")
    if not isinstance(population, dict):
        raise ValueError("Population costs must define a minimum and maximum score")
    min_per_cell = float(population.get("min_per_cell", 0))
    if not math.isfinite(min_per_cell) or min_per_cell < 0:
        raise ValueError("Population threshold must be a finite non-negative value")
    minimum = float(population["minimum"])
    maximum = float(population["maximum"])
    if (
        not math.isfinite(minimum)
        or not math.isfinite(maximum)
        or minimum < minimum_score
        or maximum > 10
        or maximum < minimum
    ):
        raise ValueError(
            f"Population cost scores must be between {minimum_score:g} and 10"
        )
    if "building_barrier" not in barriers:
        raise ValueError("Buildings must remain impassable barriers")
    risk = costs.get("population_risk")
    if isinstance(risk, dict) and risk.get("enabled", False):
        maximum_risk = float(risk["maximum"])
        if (
            not math.isfinite(maximum_risk)
            or not minimum_score <= maximum_risk <= 10
        ):
            raise ValueError(
                "Population-risk score must be between "
                f"{minimum_score:g} and 10"
            )


def validate_class_bits(class_bits: dict[str, Any]) -> np.dtype[Any]:
    observed_bits: set[int] = set()
    maximum_bit = 0
    for class_name, configured_bit in class_bits.items():
        bit = int(configured_bit)
        if (
            bit <= 0
            or bit & (bit - 1)
            or bit in observed_bits
        ):
            raise ValueError(
                f"Class bit for {class_name!r} must be a unique power of two"
            )
        observed_bits.add(bit)
        maximum_bit = max(maximum_bit, bit)
    for dtype in (np.dtype("uint16"), np.dtype("uint32"), np.dtype("uint64")):
        if maximum_bit <= np.iinfo(dtype).max:
            return dtype
    raise ValueError("Configured class bits exceed the uint64 range")


def dwelling_proximity_costs(
    building_mask: np.ndarray,
    traversable_land: np.ndarray,
    resolution_m: float,
    max_distance_m: float,
    max_score: float,
) -> tuple[np.ndarray, np.ndarray]:
    if (
        not math.isfinite(resolution_m)
        or not math.isfinite(max_distance_m)
        or not math.isfinite(max_score)
        or resolution_m <= 0
        or max_distance_m <= 0
        or max_score < 0
    ):
        raise ValueError("Invalid dwelling-proximity distance or score")
    if not np.any(building_mask):
        raise ValueError("Dwelling proximity requires at least one building cell")
    distance_m = distance_transform_edt(
        ~building_mask, sampling=(resolution_m, resolution_m)
    )
    mask = (
        traversable_land
        & (distance_m > 0)
        & (distance_m < max_distance_m)
    )
    scores = np.zeros(building_mask.shape, dtype=np.float32)
    scores[mask] = max_score * (1 - distance_m[mask] / max_distance_m)
    return scores, mask


def parallel_corridor_mask(
    asset_mask: np.ndarray,
    traversable_mask: np.ndarray,
    resolution_m: float,
    inner_distance_m: float,
    outer_distance_m: float,
) -> np.ndarray:
    if (
        not math.isfinite(resolution_m)
        or not math.isfinite(inner_distance_m)
        or not math.isfinite(outer_distance_m)
        or resolution_m <= 0
        or inner_distance_m < 0
        or outer_distance_m <= inner_distance_m
    ):
        raise ValueError("Invalid parallel-corridor distance settings")
    if not np.any(asset_mask):
        raise ValueError("Parallel corridor assets rasterized to no cells")
    distance_m = distance_transform_edt(
        ~asset_mask, sampling=(resolution_m, resolution_m)
    )
    return (
        traversable_mask
        & (distance_m >= inner_distance_m)
        & (distance_m <= outer_distance_m)
    )


def max_group_contribution(
    members: Sequence[tuple[np.ndarray, float | np.ndarray]],
    shape: tuple[int, int],
) -> np.ndarray:
    contribution = np.zeros(shape, dtype=np.float32)
    for member_mask, score in members:
        if isinstance(score, np.ndarray):
            contribution[member_mask] = np.maximum(
                contribution[member_mask], score[member_mask]
            )
        else:
            contribution[member_mask] = np.maximum(
                contribution[member_mask], score
            )
    return contribution


def landfall_cells(
    land_mask: np.ndarray,
    sea_mask: np.ndarray,
    extent_mask: np.ndarray,
    connectivity: int = 8,
) -> np.ndarray:
    if connectivity == 8:
        neighbourhood = np.ones((3, 3))
    elif connectivity == 4:
        neighbourhood = np.array(
            [[False, True, False], [True, True, True], [False, True, False]]
        )
    else:
        raise ValueError("Landfall connectivity must be 4 or 8")
    sea_neighbourhood = np.asarray(
        binary_dilation(sea_mask, structure=neighbourhood), dtype=bool
    )
    return land_mask & extent_mask & sea_neighbourhood


def population_risk_costs(
    population_counts: np.ndarray,
    extent_mask: np.ndarray,
    land_mask: np.ndarray,
    resolution_m: int,
    settings: dict[str, Any],
) -> tuple[np.ndarray, np.ndarray, dict[str, float | int]]:
    radius_m = float(settings["radius_m"])
    kernel_shape = str(settings.get("kernel", "circular"))
    threshold = float(settings["threshold_people"])
    max_score = float(settings["maximum"])
    quantile_count = int(settings["quantiles"])
    if (
        not math.isfinite(radius_m)
        or not math.isfinite(threshold)
        or not math.isfinite(max_score)
        or radius_m <= 0
        or threshold < 0
        or not 0 <= max_score <= 10
        or resolution_m <= 0
        or quantile_count < 2
        or kernel_shape != "circular"
    ):
        raise ValueError("Invalid population-risk settings")

    radius_cells = int(math.ceil(radius_m / resolution_m))
    offsets = np.arange(-radius_cells, radius_cells + 1, dtype=np.int32)
    rows, cols = np.meshgrid(offsets, offsets, indexing="ij")
    kernel = (
        (rows * resolution_m) ** 2 + (cols * resolution_m) ** 2
        <= radius_m**2
    ).astype(np.float32)
    focal_population = np.asarray(
        convolve(
            np.where(
                np.isfinite(population_counts), population_counts, 0
            ).astype(np.float32),
            kernel,
            mode="constant",
            cval=0,
        ),
        dtype=np.float32,
    )
    eligible = land_mask & extent_mask & (focal_population > threshold)
    scores = np.zeros(population_counts.shape, dtype=np.float32)
    values = focal_population[eligible]
    if values.size:
        thresholds = np.quantile(values, np.linspace(0, 1, quantile_count + 1))
        score_levels = np.linspace(0, max_score, quantile_count + 1)
        unique_thresholds, inverse = np.unique(thresholds, return_inverse=True)
        if unique_thresholds.size == 1:
            quantile_scores = np.array([max_score], dtype=np.float64)
        else:
            score_sums = np.bincount(inverse, weights=score_levels)
            score_counts = np.bincount(inverse)
            quantile_scores = score_sums / score_counts
        scores[eligible] = np.interp(
            focal_population[eligible], unique_thresholds, quantile_scores
        )
    return scores, eligible, {
        "cells_above_threshold": int(values.size),
        "maximum_focal_population": float(values.max()) if values.size else 0.0,
        "radius_m": radius_m,
        "threshold_people": threshold,
    }


def make_grid(extent_path: Path, resolution: int, target_crs: str) -> tuple[
    rasterio.Affine, int, int, tuple[float, float, float, float]
]:
    extent = gpd.read_file(extent_path, layer="analysis_extent")
    if extent.crs is None:
        raise ValueError(f"Analysis extent has no CRS: {extent_path}")
    extent = extent.to_crs(target_crs)
    left, bottom, right, top = map(float, extent.total_bounds)
    left = math.floor(left / resolution) * resolution
    bottom = math.floor(bottom / resolution) * resolution
    right = math.ceil(right / resolution) * resolution
    top = math.ceil(top / resolution) * resolution
    width = int(round((right - left) / resolution))
    height = int(round((top - bottom) / resolution))
    return (
        from_origin(left, top, resolution, resolution),
        width,
        height,
        (left, bottom, right, top),
    )


def rasterize_layer(
    gpkg: Path,
    layer: str,
    transform: rasterio.Affine,
    width: int,
    height: int,
    all_touched: bool,
    target_crs: str,
    exclude_osm_ids: list[str] | None = None,
) -> np.ndarray:
    info = pyogrio.read_info(gpkg, layer=layer)
    if not info["features"]:
        raise ValueError(f"Source layer is empty: {gpkg.name}:{layer}")
    mask = np.zeros((height, width), dtype=np.uint8)
    offset = 0
    while offset < info["features"]:
        frame = pyogrio.read_dataframe(
            gpkg,
            layer=layer,
            columns=["osm_id"] if exclude_osm_ids else [],
            skip_features=offset,
            max_features=BATCH_SIZE,
            use_arrow=True,
        )
        if frame.empty:
            break
        batch_count = len(frame)
        if exclude_osm_ids:
            if "osm_id" not in frame.columns:
                raise ValueError(
                    f"Cannot exclude OSM way IDs from {gpkg.name}:{layer}; "
                    "the layer has no osm_id field"
                )
            frame = frame.loc[
                ~frame["osm_id"].astype(str).isin(exclude_osm_ids)
            ]
            if frame.empty:
                offset += batch_count
                continue
        if frame.crs is None:
            raise ValueError(f"Source layer has no CRS: {gpkg.name}:{layer}")
        if frame.crs.to_string() != target_crs:
            frame = frame.to_crs(target_crs)
        shapes: Iterator[tuple[BaseGeometry, int]] = (
            (geometry, 1)
            for geometry in frame.geometry.array
            if geometry is not None and not geometry.is_empty
        )
        rasterize(
            shapes,
            out=mask,
            transform=transform,
            default_value=1,
            all_touched=all_touched,
        )
        offset += batch_count
        LOG.info(
            "Rasterized %s:%s: %s/%s features",
            gpkg.name,
            layer,
            min(offset, info["features"]),
            info["features"],
        )
        del frame
    return mask


def rasterize_extent_and_land(
    transform: rasterio.Affine,
    width: int,
    height: int,
    target_crs: str,
    all_touched: bool,
    extent_all_touched: bool = False,
) -> tuple[np.ndarray, np.ndarray]:
    extent_path = PROCESSED / "coast_land_water.gpkg"
    extent = gpd.read_file(extent_path, layer="analysis_extent").to_crs(target_crs)
    land = gpd.read_file(extent_path, layer="land").to_crs(target_crs)
    extent_mask = rasterize(
        ((geometry, 1) for geometry in extent.geometry if geometry is not None),
        out_shape=(height, width),
        transform=transform,
        fill=0,
        all_touched=extent_all_touched,
        dtype="uint8",
    )
    land_mask = rasterize(
        ((geometry, 1) for geometry in land.geometry if geometry is not None),
        out_shape=(height, width),
        transform=transform,
        fill=0,
        all_touched=all_touched,
        dtype="uint8",
    )
    return (
        np.asarray(extent_mask, dtype=bool),
        np.asarray(land_mask, dtype=bool),
    )


def population_counts(
    extent_mask: np.ndarray,
    transform: rasterio.Affine,
    width: int,
    height: int,
    target_crs: str,
    resolution_m: int,
) -> np.ndarray:
    path = PROCESSED / "population_2020_100m.tif"
    if not path.exists():
        raise FileNotFoundError(f"Required population raster is missing: {path}")
    with rasterio.open(path) as source:
        population = np.full((height, width), np.nan, dtype=np.float32)
        reproject(
            source=rasterio.band(source, 1),
            destination=population,
            src_transform=source.transform,
            src_crs=source.crs,
            src_nodata=source.nodata,
            dst_transform=transform,
            dst_crs=target_crs,
            dst_nodata=np.nan,
            resampling=Resampling.average,
        )
        source_resolution_x, source_resolution_y = source.res
    if not math.isclose(source_resolution_x, source_resolution_y):
        raise ValueError("Population raster requires square source cells")
    population *= (resolution_m / source_resolution_x) ** 2
    population[~extent_mask] = np.nan
    return population


def population_costs(
    extent_mask: np.ndarray,
    land_mask: np.ndarray,
    transform: rasterio.Affine,
    width: int,
    height: int,
    target_crs: str,
    resolution_m: int,
    settings: dict[str, Any],
    counts: np.ndarray | None = None,
) -> tuple[np.ndarray, dict[str, float | int]]:
    population = (
        counts
        if counts is not None
        else population_counts(
            extent_mask, transform, width, height, target_crs, resolution_m
        )
    )
    reference_resolution = float(
        settings.get("reference_cell_resolution_m", 100)
    )
    if not math.isfinite(reference_resolution) or reference_resolution <= 0:
        raise ValueError("Population reference-cell resolution must be positive")
    threshold = float(settings.get("min_per_cell", 0)) * (
        resolution_m / reference_resolution
    ) ** 2
    eligible = (
        land_mask
        & extent_mask
        & np.isfinite(population)
        & (population > 0)
        & (population >= threshold)
    )
    values = population[eligible]
    if values.size == 0:
        raise ValueError(
            "No population cells meet the configured threshold on land"
        )
    minimum = float(settings["minimum"])
    maximum = float(settings["maximum"])
    quantile_count = int(settings["quantiles"])
    if minimum < 0 or maximum < minimum or quantile_count < 2:
        raise ValueError("Invalid population minimum, maximum, or quantile count")
    probabilities = np.linspace(0.0, 1.0, quantile_count + 1)
    thresholds = np.quantile(values, probabilities)
    scores = np.linspace(minimum, maximum, quantile_count + 1)
    result = np.zeros((height, width), dtype=np.float32)
    unique_thresholds, inverse = np.unique(thresholds, return_inverse=True)
    if unique_thresholds.size == 1:
        quantile_scores = np.array([minimum], dtype=np.float64)
    else:
        score_sums = np.bincount(inverse, weights=scores)
        score_counts = np.bincount(inverse)
        quantile_scores = score_sums / score_counts
    result[eligible] = np.interp(
        population[eligible], unique_thresholds, quantile_scores
    )
    return result, {
        "positive_population_cells": int(values.size),
        "minimum_population": float(values.min()),
        "maximum_population": float(values.max()),
        "threshold_per_analysis_cell": float(threshold),
    }


def write_class_statistics(
    rows: list[dict[str, Any]], output_path: Path
) -> None:
    fields = [
        "class",
        "cost_score",
        "cells",
        "area_km2",
        "total_cost_contribution",
        "impassable",
    ]
    with output_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def load_excluded_osm_ids(path: Path) -> list[str]:
    source = gpd.read_file(path)
    id_columns = [name for name in ("osm_id", "osm_ids") if name in source]
    if not id_columns:
        raise ValueError(
            f"{path} must contain an osm_id or osm_ids property"
        )
    excluded: set[str] = set()
    for column in id_columns:
        for value in source[column].dropna():
            for item in str(value).split(","):
                token = item.strip()
                match = re.fullmatch(r"(?:way/)?(\d+)", token)
                if not match:
                    raise ValueError(
                        f"Invalid OSM way ID {token!r} in {path}"
                    )
                excluded.add(match.group(1))
    if not excluded:
        raise ValueError(f"No OSM way IDs found in {path}")
    return sorted(excluded)


def build_cost_surface(
    config_path: Path = CONFIG,
    output_path: Path | None = None,
    exclude_osm_ids: list[str] | None = None,
) -> Path:
    config_path = config_path.resolve()
    config = load_config(config_path)
    grid_config = config["grid"]
    costs = config["costs"]
    minimum_score = float(config.get("score_minimum", 1))
    landfall_config = config.get("landfall", {})
    population_risk_config = costs.get("population_risk", {})
    derived_cost_names: set[str] = set()
    if landfall_config.get("enabled", False):
        derived_cost_names.add(str(landfall_config["cost"]))
    validate_cost_scores(
        costs,
        config["layers"],
        [str(name) for name in config.get("barriers", [])],
        minimum_score,
        derived_cost_names,
    )
    discount_classes = {
        str(name) for name in config.get("discount_classes", [])
    }
    configured_classes = {
        str(layer["cost"]) for layer in config["layers"].values()
    }
    unknown_discount_classes = discount_classes - configured_classes
    if unknown_discount_classes:
        raise ValueError(
            "Discount classes have no configured input layer: "
            f"{sorted(unknown_discount_classes)}"
        )
    resolution = int(grid_config["resolution_m"])
    reference_resolution = int(grid_config["cost_reference_resolution_m"])
    target_crs = str(grid_config["crs"])
    nodata = float(grid_config["nodata"])
    if resolution <= 0:
        raise ValueError("Grid resolution must be positive")
    if reference_resolution <= 0:
        raise ValueError("Reference cost resolution must be positive")
    if grid_config.get("combine_rule") != "additive":
        raise ValueError("Only the documented additive combine rule is supported")
    cost_scale = resolution / reference_resolution

    transform, width, height, bounds = make_grid(
        PROCESSED / "coast_land_water.gpkg", resolution, target_crs
    )
    extent_mask, land_mask = rasterize_extent_and_land(
        transform,
        width,
        height,
        target_crs,
        bool(config["rasterization"]["polygon_all_touched"]),
        bool(config["rasterization"].get("extent_all_touched", False)),
    )
    land_mask &= extent_mask
    sea_mask = extent_mask & ~land_mask
    building_mask = rasterize_layer(
        PROCESSED / "water_and_urban.gpkg",
        "buildings",
        transform,
        width,
        height,
        bool(config["rasterization"]["polygon_all_touched"]),
        target_crs,
    ).astype(bool) & extent_mask
    traversable_land = land_mask & ~building_mask
    traversable_sea = sea_mask & ~building_mask
    cost_surface = np.full((height, width), nodata, dtype=np.float32)
    cost_surface[traversable_land] = float(costs["open_land"]) * cost_scale
    cost_surface[traversable_sea] = float(costs["open_sea"]) * cost_scale
    cost_surface[building_mask] = nodata
    class_bits = config["class_bits"]
    class_dtype = validate_class_bits(class_bits)
    class_mask = np.zeros((height, width), dtype=class_dtype)
    class_mask[traversable_land] |= int(class_bits["open_land"])
    class_mask[traversable_sea] |= int(class_bits["open_sea"])
    class_mask[building_mask] |= int(class_bits["building_barrier"])
    cell_area_km2 = (resolution * resolution) / 1_000_000
    statistics: list[dict[str, Any]] = []

    def record_class(
        name: str,
        mask: np.ndarray,
        score: float | str,
        impassable: bool = False,
        total_contribution: float | None = None,
    ) -> None:
        cells = int(np.count_nonzero(mask))
        numeric_score = (
            0.0 if impassable else float(score) if isinstance(score, (int, float)) else None
        )
        statistics.append(
            {
                "class": name,
                "cost_score": (
                    "barrier" if impassable else numeric_score if numeric_score is not None else score
                ),
                "cells": cells,
                "area_km2": round(cells * cell_area_km2, 3),
                "total_cost_contribution": (
                    "barrier"
                    if impassable
                    else round(
                        total_contribution
                        if total_contribution is not None
                        else cells * float(numeric_score or 0.0),
                        3,
                    )
                ),
                "impassable": str(impassable).lower(),
            }
        )

    record_class(
        "open_land_base",
        traversable_land,
        float(costs["open_land"]) * cost_scale,
    )
    record_class(
        "open_sea_base",
        traversable_sea,
        float(costs["open_sea"]) * cost_scale,
    )

    class_masks: dict[str, np.ndarray] = {}
    barrier_class_masks: dict[str, np.ndarray] = {}
    parallel_asset_mask = np.zeros((height, width), dtype=bool)
    for name, layer_config in config["layers"].items():
        source_path = PROCESSED / layer_config["file"]
        if not source_path.exists():
            if layer_config.get("optional", False):
                LOG.warning(
                    "Skipping optional cost layer %s; input is missing: %s",
                    name,
                    source_path,
                )
                continue
            raise FileNotFoundError(f"Required processed input is missing: {source_path}")
        geometry_type = layer_config["geometry"]
        if geometry_type not in {"linear", "polygon"}:
            raise ValueError(f"Unsupported geometry type for {name}: {geometry_type}")
        source_layer = str(layer_config["layer"])
        available_layers = {str(row[0]) for row in pyogrio.list_layers(source_path)}
        if source_layer not in available_layers:
            if layer_config.get("optional", False):
                LOG.warning(
                    "Skipping optional cost layer %s; layer %r is absent from %s",
                    name,
                    source_layer,
                    source_path,
                )
                continue
            raise ValueError(
                f"Required source layer {source_layer!r} is missing from "
                f"{source_path}"
            )
        mask = rasterize_layer(
            source_path,
            source_layer,
            transform,
            width,
            height,
            bool(
                config["rasterization"][
                    "linear_all_touched"
                    if geometry_type == "linear"
                    else "polygon_all_touched"
                ]
            ),
            target_crs,
        )
        mask = mask.astype(bool) & extent_mask & ~building_mask
        surface = layer_config.get("surface", "any")
        if surface == "land":
            mask &= land_mask & ~building_mask
        elif surface != "any":
            raise ValueError(
                f"Unsupported surface constraint for layer {name!r}: {surface}"
            )
        cost_key = str(layer_config["cost"])
        barrier_layer = cost_key in config.get("barriers", [])
        if cost_key not in costs and not barrier_layer:
            raise ValueError(f"No configured cost for input class {cost_key!r}")
        if cost_key == "building_barrier":
            raise ValueError("Building barriers must not be declared as regular layers")
        class_bit = str(layer_config.get("class_bit", cost_key))
        if class_bit not in class_bits:
            raise ValueError(f"No class bit configured for layer {name!r}")
        class_mask[mask] |= int(class_bits[class_bit])
        if barrier_layer:
            if cost_key not in barrier_class_masks:
                barrier_class_masks[cost_key] = mask
            else:
                np.logical_or(
                    barrier_class_masks[cost_key], mask,
                    out=barrier_class_masks[cost_key],
                )
        elif cost_key not in class_masks:
            class_masks[cost_key] = mask
        else:
            np.logical_or(class_masks[cost_key], mask, out=class_masks[cost_key])
        if layer_config.get("parallel_asset", False):
            parallel_asset_mask |= mask
        del mask

    if landfall_config.get("enabled", False):
        landfall_name = str(landfall_config["cost"])
        landfall_mask = landfall_cells(
            traversable_land,
            sea_mask,
            extent_mask,
            int(landfall_config.get("connectivity", 8)),
        )
        landfall_bit = str(landfall_config.get("class_bit", landfall_name))
        if landfall_bit not in class_bits:
            raise ValueError(
                f"No class bit configured for derived class {landfall_name!r}"
            )
        class_mask[landfall_mask] |= int(class_bits[landfall_bit])
        class_masks[landfall_name] = landfall_mask

    for barrier_name, mask in barrier_class_masks.items():
        cost_surface[mask] = nodata
        record_class(barrier_name, mask, "barrier", impassable=True)

    combine_groups = config.get("combine_groups", {})
    grouped_classes: set[str] = set()
    deferred_groups: dict[str, list[str]] = {}
    dynamic_classes = {
        "dwelling_proximity",
        "population",
        "population_risk",
    }
    for group_name, group in combine_groups.items():
        members = [str(member) for member in group["members"]]
        if group.get("rule") != "max" or len(members) < 2:
            raise ValueError(
                f"Combine group {group_name!r} must have at least two members "
                "and use the max rule"
            )
        if grouped_classes.intersection(members):
            raise ValueError("A cost class may belong to only one combine group")
        missing_members = set(members) - class_masks.keys() - dynamic_classes
        if missing_members:
            raise ValueError(
                f"Combine group {group_name!r} has missing cost classes: "
                f"{sorted(missing_members)}"
            )
        grouped_classes.update(members)
        if dynamic_classes.intersection(members):
            deferred_groups[str(group_name)] = members
            continue
        combined_mask = np.zeros((height, width), dtype=bool)
        group_members: list[tuple[np.ndarray, float | np.ndarray]] = []
        for member in members:
            member_mask = class_masks.get(
                member, np.zeros((height, width), dtype=bool)
            )
            combined_mask |= member_mask
            member_score = float(costs[member]) * cost_scale
            group_members.append((member_mask, member_score))
        group_contribution = max_group_contribution(
            group_members, (height, width)
        )
        applicable = (
            combined_mask
            & np.isfinite(cost_surface)
            & (cost_surface != nodata)
        )
        cost_surface[applicable] += group_contribution[applicable]
        record_class(
            str(group_name),
            combined_mask,
            "max(" + ", ".join(members) + ")",
            total_contribution=float(group_contribution[applicable].sum()),
        )

    for cost_key, mask in class_masks.items():
        if cost_key in grouped_classes:
            continue
        score = float(costs[cost_key]) * cost_scale
        applicable = mask & np.isfinite(cost_surface) & (cost_surface != nodata)
        if cost_key in discount_classes:
            previous = cost_surface[applicable].copy()
            minimum_cost = float(costs["open_land"]) * cost_scale
            cost_surface[applicable] = np.maximum(
                minimum_cost,
                previous - score,
            )
            total_contribution = float(
                (cost_surface[applicable] - previous).sum()
            )
        else:
            cost_surface[applicable] += score
            total_contribution = None
        record_class(
            cost_key,
            mask,
            score,
            total_contribution=total_contribution,
        )

    dynamic_group_values: dict[
        str, tuple[np.ndarray, np.ndarray]
    ] = {}
    proximity_config = costs.get("dwelling_proximity", {})
    if proximity_config.get("enabled", True):
        if str(proximity_config.get("distance_metric", "euclidean")) != "euclidean":
            raise ValueError("Dwelling proximity supports Euclidean distance only")
        proximity_scores, proximity_mask = dwelling_proximity_costs(
            building_mask,
            traversable_land,
            resolution,
            float(proximity_config["max_distance_m"]),
            float(proximity_config["max_score"]),
        )
        proximity_scores *= cost_scale
        proximity_mask &= np.isfinite(cost_surface) & (cost_surface != nodata)
        class_mask[proximity_mask] |= int(class_bits["dwelling_proximity"])
        if "dwelling_proximity" in grouped_classes:
            dynamic_group_values["dwelling_proximity"] = (
                proximity_mask,
                proximity_scores,
            )
        else:
            cost_surface[proximity_mask] += proximity_scores[proximity_mask]
            record_class(
                "dwelling_proximity",
                proximity_mask,
                "distance-scaled",
                total_contribution=float(proximity_scores[proximity_mask].sum()),
            )

    parallel_config = config.get("parallel_corridor", {})
    if parallel_config.get("enabled", False):
        if str(parallel_config.get("distance_metric", "euclidean")) != "euclidean":
            raise ValueError("Parallel corridor supports Euclidean distance only")
        excluded_ids = sorted(
            {
                str(identifier)
                for identifier in [
                    *parallel_config.get("exclude_osm_ids", []),
                    *(exclude_osm_ids or []),
                ]
            }
        )
        for asset in parallel_config.get("assets", []):
            source_path = PROCESSED / asset["file"]
            if not source_path.exists():
                raise FileNotFoundError(
                    f"Required parallel-corridor input is missing: {source_path}"
                )
            asset_mask = rasterize_layer(
                source_path,
                str(asset["layer"]),
                transform,
                width,
                height,
                bool(config["rasterization"]["linear_all_touched"]),
                target_crs,
                excluded_ids,
            ).astype(bool)
            parallel_asset_mask |= asset_mask & extent_mask
        valid_surface = np.isfinite(cost_surface) & (cost_surface != nodata)
        corridor_mask = parallel_corridor_mask(
            parallel_asset_mask,
            valid_surface,
            resolution,
            float(parallel_config["inner_distance_m"]),
            float(parallel_config["outer_distance_m"]),
        )
        corridor_mask &= ~parallel_asset_mask
        factor = float(parallel_config["factor"])
        if not 0 < factor <= 1:
            raise ValueError("Parallel corridor factor must be in (0, 1]")
        minimum_cost = float(costs["open_land"]) * cost_scale
        original_costs = cost_surface[corridor_mask].copy()
        cost_surface[corridor_mask] = np.maximum(
            minimum_cost,
            cost_surface[corridor_mask] * factor,
        )
        class_mask[corridor_mask] |= int(class_bits["parallel_corridor"])
        record_class(
            "parallel_corridor",
            corridor_mask,
            f"factor-{factor:g}",
            total_contribution=float(
                (cost_surface[corridor_mask] - original_costs).sum()
            ),
        )

    population_config = costs["population"]
    population_enabled = population_config.get("enabled", True)
    risk_enabled = population_risk_config.get("enabled", False)
    population_values: np.ndarray | None = None
    population_summary: dict[str, Any] = {"enabled": False}
    population_risk_summary: dict[str, Any] = {"enabled": False}
    if population_enabled or risk_enabled:
        population_values = population_counts(
            extent_mask,
            transform,
            width,
            height,
            target_crs,
            resolution,
        )
    if population_enabled:
        population, population_summary = population_costs(
            extent_mask,
            traversable_land,
            transform,
            width,
            height,
            target_crs,
            resolution,
            population_config,
            population_values,
        )
        population *= cost_scale
        population_mask = (
            (population > 0)
            & traversable_land
            & np.isfinite(cost_surface)
            & (cost_surface != nodata)
        )
        class_mask[population_mask] |= int(class_bits["population"])
        if "population" in grouped_classes:
            dynamic_group_values["population"] = (
                population_mask,
                population,
            )
        else:
            cost_surface[population_mask] += population[population_mask]
            record_class(
                "population",
                population_mask,
                "quantile-scaled",
                total_contribution=float(population[population_mask].sum()),
            )

    if risk_enabled:
        if population_values is None:
            raise RuntimeError("Population-risk calculation has no population grid")
        risk_scores, risk_mask, population_risk_summary = (
            population_risk_costs(
                population_values,
                extent_mask,
                traversable_land,
                resolution,
                population_risk_config,
            )
        )
        risk_scores *= cost_scale
        risk_mask &= (
            np.isfinite(cost_surface) & (cost_surface != nodata)
        )
        risk_bit = str(
            population_risk_config.get("class_bit", "population_risk")
        )
        if risk_bit not in class_bits:
            raise ValueError("No class bit configured for population_risk")
        class_mask[risk_mask] |= int(class_bits[risk_bit])
        if "population_risk" in grouped_classes:
            dynamic_group_values["population_risk"] = (
                risk_mask,
                risk_scores,
            )
        else:
            cost_surface[risk_mask] += risk_scores[risk_mask]
            record_class(
                "population_risk",
                risk_mask,
                "quantile-scaled",
                total_contribution=float(risk_scores[risk_mask].sum()),
            )

    for group_name, members in deferred_groups.items():
        combined_mask = np.zeros((height, width), dtype=bool)
        deferred_group_members: list[
            tuple[np.ndarray, np.ndarray | float]
        ] = []
        for member in members:
            if member in dynamic_group_values:
                member_mask, member_scores = dynamic_group_values[member]
            elif member in class_masks:
                member_mask = class_masks[member]
                member_scores = np.full(
                    (height, width),
                    float(costs[member]) * cost_scale,
                    dtype=np.float32,
                )
            else:
                member_mask = np.zeros((height, width), dtype=bool)
                member_scores = np.zeros((height, width), dtype=np.float32)
            combined_mask |= member_mask
            deferred_group_members.append((member_mask, member_scores))
        group_contribution = max_group_contribution(
            deferred_group_members, (height, width)
        )
        applicable = (
            combined_mask
            & np.isfinite(cost_surface)
            & (cost_surface != nodata)
        )
        cost_surface[applicable] += group_contribution[applicable]
        record_class(
            group_name,
            combined_mask,
            "max(" + ", ".join(members) + ")",
            total_contribution=float(group_contribution[applicable].sum()),
        )

    record_class("building_barrier", building_mask, "barrier", impassable=True)
    class_mask[~extent_mask] = 0

    if not np.any(np.isfinite(cost_surface) & (cost_surface != nodata)):
        raise ValueError("The cost surface contains no traversable cells")
    if np.any(
        (np.isfinite(cost_surface) & (cost_surface != nodata))
        & (cost_surface <= 0)
    ):
        raise ValueError("Traversable cell costs must all be positive")

    output_path = (
        output_path or PROCESSED / f"cost_surface_{resolution}m.tif"
    ).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    profile = {
        "driver": "GTiff",
        "height": height,
        "width": width,
        "count": 1,
        "dtype": "float32",
        "crs": target_crs,
        "transform": transform,
        "nodata": nodata,
        "compress": "deflate",
        "predictor": 3,
        "tiled": True,
    }
    with rasterio.open(output_path, "w", **profile) as destination:
        destination.write(cost_surface, 1)
        destination.set_band_description(1, "Relative additive pipeline routing cost")
        destination.update_tags(
            resolution_m=resolution,
            cost_reference_resolution_m=reference_resolution,
            cost_scale_factor=cost_scale,
            combine_rule="additive",
            discount_classes=",".join(sorted(discount_classes)),
            barrier_value=nodata,
            population_method=(
                "Population averaged to grid and scaled to analysis-cell area; "
                "cells below the configured per-100-m-cell threshold are uncosted"
            ),
            population_risk_method=(
                "Population summed within the configured circular land-cell "
                "neighbourhood, then quantile scored"
                if risk_enabled
                else "disabled"
            ),
            extent_bounds_m=",".join(f"{value:.2f}" for value in bounds),
            source_config=path_for_metadata(config_path),
        )

    class_output_path = output_path.with_name(
        f"cost_class_mask_{resolution}m.tif"
    )
    class_profile = profile | {
        "dtype": class_dtype.name,
        "nodata": 0,
        "predictor": 2,
    }
    with rasterio.open(class_output_path, "w", **class_profile) as destination:
        destination.write(class_mask, 1)
        destination.set_band_description(1, "Bitmask of traversed cost classes")
        destination.update_tags(
            class_bits=json.dumps(class_bits, sort_keys=True),
            resolution_m=resolution,
        )

    stats_path = output_path.with_name("cost_surface_class_statistics.csv")
    write_class_statistics(statistics, stats_path)
    metadata = {
        "crs": target_crs,
        "resolution_m": resolution,
        "cost_reference_resolution_m": reference_resolution,
        "cost_scale_factor": cost_scale,
        "width": width,
        "height": height,
        "bounds": bounds,
        "combine_rule": "additive",
        "discount_classes": sorted(discount_classes),
        "nodata_and_barrier_value": nodata,
        "traversable_cells": int(
            np.count_nonzero(np.isfinite(cost_surface) & (cost_surface != nodata))
        ),
        "barrier_cells": int(np.count_nonzero(building_mask)),
        "outside_extent_cells": int(np.count_nonzero(~extent_mask)),
        "cost_min": float(np.min(cost_surface[cost_surface != nodata])),
        "cost_max": float(np.max(cost_surface[cost_surface != nodata])),
        "population_summary": population_summary,
        "population_risk_summary": population_risk_summary,
        "statistics_csv": path_for_metadata(stats_path),
        "class_mask_raster": path_for_metadata(class_output_path),
        "effective_config_sha256": config_fingerprint(config),
    }
    if exclude_osm_ids:
        metadata["excluded_parallel_asset_osm_ids"] = sorted(
            {str(identifier) for identifier in exclude_osm_ids}
        )
    metadata_path = output_path.with_name("cost_surface_metadata.json")
    metadata_path.write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    LOG.info("Cost surface written: %s", output_path)
    LOG.info("Class statistics written: %s", stats_path)
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rasterize configured cost layers onto the analysis grid."
    )
    parser.add_argument("--config", type=Path, default=CONFIG)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--exclude-osm-ids-from",
        type=Path,
        help="GeoJSON with an osm_ids property listing OSM way IDs to omit from corridor discounts.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Directory for the cost raster and its class, statistics, and metadata sidecars.",
    )
    args = parser.parse_args()
    if args.exclude_osm_ids_from and not args.output_dir:
        parser.error("--exclude-osm-ids-from requires --output-dir")
    if args.output and args.output_dir:
        parser.error("--output and --output-dir are mutually exclusive")
    config = load_config(args.config)
    resolution = int(config["grid"]["resolution_m"])
    output_path = args.output
    if args.output_dir:
        output_path = args.output_dir / f"cost_surface_{resolution}m.tif"
    excluded_ids: list[str] | None = None
    if args.exclude_osm_ids_from:
        excluded_ids = load_excluded_osm_ids(args.exclude_osm_ids_from)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    build_cost_surface(args.config, output_path, excluded_ids)


if __name__ == "__main__":
    main()
