"""Build the configurable least-cost routing surface."""

from __future__ import annotations

import argparse
import csv
import json
import logging
import math
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pyogrio
import rasterio
import yaml
from rasterio.features import rasterize
from rasterio.transform import from_origin
from rasterio.warp import Resampling, reproject
from shapely.geometry.base import BaseGeometry


ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"
CONFIG = ROOT / "config" / "costs.yaml"
LOG = logging.getLogger("cost_surface")
BATCH_SIZE = 50_000


def load_config(path: Path = CONFIG) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        config = yaml.safe_load(stream)
    if not isinstance(config, dict):
        raise ValueError(f"Expected a YAML mapping in {path}")
    return config


def validate_cost_scores(
    costs: dict[str, Any],
    layers: dict[str, Any],
    barriers: list[str],
) -> None:
    score_names = {"open_land", "open_sea", "building_barrier"}
    score_names.update(str(layer["cost"]) for layer in layers.values())
    for name in sorted(score_names):
        if name not in costs:
            raise ValueError(f"Missing configured cost score for {name!r}")
        score = float(costs[name])
        if not math.isfinite(score) or not 1 <= score <= 10:
            raise ValueError(f"Cost score for {name!r} must be between 1 and 10")

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
        or minimum < 1
        or maximum > 10
        or maximum < minimum
    ):
        raise ValueError("Population cost scores must be between 1 and 10")
    if "building_barrier" not in barriers:
        raise ValueError("Buildings must remain impassable barriers")


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
            columns=[],
            skip_features=offset,
            max_features=BATCH_SIZE,
            use_arrow=True,
        )
        if frame.empty:
            break
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
        offset += len(frame)
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
) -> tuple[np.ndarray, np.ndarray]:
    extent_path = PROCESSED / "coast_land_water.gpkg"
    extent = gpd.read_file(extent_path, layer="analysis_extent").to_crs(target_crs)
    land = gpd.read_file(extent_path, layer="land").to_crs(target_crs)
    extent_mask = rasterize(
        ((geometry, 1) for geometry in extent.geometry if geometry is not None),
        out_shape=(height, width),
        transform=transform,
        fill=0,
        all_touched=False,
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
    return extent_mask.astype(bool), land_mask.astype(bool)


def population_costs(
    extent_mask: np.ndarray,
    land_mask: np.ndarray,
    transform: rasterio.Affine,
    width: int,
    height: int,
    target_crs: str,
    resolution_m: int,
    settings: dict[str, Any],
) -> tuple[np.ndarray, dict[str, float | int]]:
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
    area_scale = (resolution_m / source_resolution_x) ** 2
    population *= area_scale
    threshold = float(settings.get("min_per_cell", 0)) * area_scale
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


def build_cost_surface(
    config_path: Path = CONFIG,
    output_path: Path | None = None,
) -> Path:
    config = load_config(config_path)
    grid_config = config["grid"]
    costs = config["costs"]
    validate_cost_scores(
        costs,
        config["layers"],
        [str(name) for name in config.get("barriers", [])],
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
    class_mask = np.zeros((height, width), dtype=np.uint16)
    class_bits = config["class_bits"]
    observed_bits: set[int] = set()
    for class_name in class_bits:
        bit = int(class_bits[class_name])
        if (
            bit <= 0
            or bit > np.iinfo(np.uint16).max
            or bit & (bit - 1)
            or bit in observed_bits
        ):
            raise ValueError(
                f"Class bit for {class_name!r} must be a unique uint16 power of two"
            )
        observed_bits.add(bit)
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
    for name, layer_config in config["layers"].items():
        source_path = PROCESSED / layer_config["file"]
        if not source_path.exists():
            raise FileNotFoundError(f"Required processed input is missing: {source_path}")
        geometry_type = layer_config["geometry"]
        if geometry_type not in {"linear", "polygon"}:
            raise ValueError(f"Unsupported geometry type for {name}: {geometry_type}")
        mask = rasterize_layer(
            source_path,
            layer_config["layer"],
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
        cost_key = layer_config["cost"]
        if cost_key not in costs:
            raise ValueError(f"No configured cost for input class {cost_key!r}")
        if cost_key == "building_barrier":
            raise ValueError("Building barriers must not be declared as regular layers")
        class_bit = str(layer_config.get("class_bit", cost_key))
        if class_bit not in class_bits:
            raise ValueError(f"No class bit configured for layer {name!r}")
        class_mask[mask] |= int(class_bits[class_bit])
        if cost_key not in class_masks:
            class_masks[cost_key] = mask
        else:
            np.logical_or(class_masks[cost_key], mask, out=class_masks[cost_key])
        del mask

    for cost_key, mask in class_masks.items():
        score = float(costs[cost_key]) * cost_scale
        cost_surface[
            mask & np.isfinite(cost_surface) & (cost_surface != nodata)
        ] += score
        record_class(cost_key, mask, score)
        del mask

    population_config = costs["population"]
    if population_config.get("enabled", True):
        population, population_summary = population_costs(
            extent_mask,
            traversable_land,
            transform,
            width,
            height,
            target_crs,
            resolution,
            population_config,
        )
        population *= cost_scale
        population_mask = (
            (population > 0)
            & traversable_land
            & np.isfinite(cost_surface)
            & (cost_surface != nodata)
        )
        cost_surface[population_mask] += population[population_mask]
        class_mask[population_mask] |= int(class_bits["population"])
        record_class(
            "population",
            population_mask,
            "quantile-scaled",
            total_contribution=float(population[population_mask].sum()),
        )
    else:
        population_summary = {"enabled": False}

    record_class("building_barrier", building_mask, "barrier", impassable=True)
    class_mask[~extent_mask] = 0

    if not np.any(np.isfinite(cost_surface) & (cost_surface != nodata)):
        raise ValueError("The cost surface contains no traversable cells")
    if np.any(
        (np.isfinite(cost_surface) & (cost_surface != nodata))
        & (cost_surface <= 0)
    ):
        raise ValueError("Traversable cell costs must all be positive")

    output_path = output_path or PROCESSED / f"cost_surface_{resolution}m.tif"
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
            barrier_value=nodata,
            population_method=(
                "Population averaged to grid and scaled to analysis-cell area; "
                "cells below the configured per-100-m-cell threshold are uncosted"
            ),
            extent_bounds_m=",".join(f"{value:.2f}" for value in bounds),
            source_config=str(config_path.relative_to(ROOT)),
        )

    class_output_path = output_path.with_name(
        f"cost_class_mask_{resolution}m.tif"
    )
    class_profile = profile | {
        "dtype": "uint16",
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
        "nodata_and_barrier_value": nodata,
        "traversable_cells": int(
            np.count_nonzero(np.isfinite(cost_surface) & (cost_surface != nodata))
        ),
        "barrier_cells": int(np.count_nonzero(building_mask)),
        "outside_extent_cells": int(np.count_nonzero(~extent_mask)),
        "cost_min": float(np.min(cost_surface[cost_surface != nodata])),
        "cost_max": float(np.max(cost_surface[cost_surface != nodata])),
        "population_summary": population_summary,
        "statistics_csv": str(stats_path.relative_to(ROOT)),
        "class_mask_raster": str(class_output_path.relative_to(ROOT)),
    }
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
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    build_cost_surface(args.config, args.output)


if __name__ == "__main__":
    main()
