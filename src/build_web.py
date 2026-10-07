"""Build static MapLibre raster overlays and publishable site metadata."""

from __future__ import annotations

import argparse
import json
import logging
import math
import time
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import rasterio
import yaml
from PIL import Image
from pyproj import Transformer
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.warp import reproject, transform_bounds


ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"
WEB = ROOT / "web"
CONFIG = ROOT / "config" / "costs.yaml"
LOG = logging.getLogger("build_web")

LAYER_PRESENTATION = {
    "open_land": ("Open land", "#73aa62", "Base surface"),
    "open_sea": ("Open sea", "#3987bd", "Base surface"),
    "road_major": ("Major roads (motorway–primary)", "#e35b45", "Infrastructure"),
    "road_minor": ("Minor roads (secondary–tertiary)", "#f2a07b", "Infrastructure"),
    "railway_crossing": ("Railways", "#8a54a2", "Infrastructure"),
    "watercourse_crossing": ("Watercourses", "#198cc2", "Water"),
    "urban_area": ("Urban areas", "#de8c3d", "Land use"),
    "lake": ("Lakes and mapped water", "#3179c2", "Water"),
    "wetland": ("Wetlands", "#46a5a0", "Water"),
    "natura2000_habitats": ("Natura 2000 habitats", "#dcbe42", "Protected areas"),
    "natura2000_birds": ("Natura 2000 birds", "#f07838", "Protected areas"),
    "protected_nature_s3": ("Protected nature (§3)", "#6d994d", "Protected areas"),
    "protected_reserves": ("Protected reserves", "#a162a8", "Protected areas"),
    "forest": ("Forest", "#2f7d4a", "Land use"),
    "population": ("Population density", "#d84141", "Population"),
    "dwelling_proximity": ("Within 200 m of buildings", "#c2185b", "Population"),
    "parallel_corridor": ("Alongside existing infrastructure", "#00897b", "Infrastructure"),
    "building_barrier": ("Buildings (barriers)", "#242424", "Infrastructure"),
}


def load_config(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        config = yaml.safe_load(stream)
    if not isinstance(config, dict):
        raise ValueError(f"Expected a YAML mapping in {path}")
    return config


def class_score_label(config: dict[str, Any], class_name: str) -> str:
    """Return the configured 1–10 score of a class bit as display text."""
    if class_name in config.get("barriers", []):
        return "barrier"
    if class_name == "parallel_corridor":
        factor = config.get("parallel_corridor", {}).get("factor")
        return "" if factor is None else f"×{factor:g}"
    cost_key = class_name
    for layer in config.get("layers", {}).values():
        if layer.get("class_bit") == class_name:
            cost_key = layer["cost"]
            break
    score = config.get("costs", {}).get(cost_key)
    if isinstance(score, dict):
        if "max_score" in score:
            return f"0–{score['max_score']:g}"
        return f"{score.get('minimum', '?')}–{score.get('maximum', '?')}"
    return "" if score is None else str(score)


def publish_lines(source: Path, destination: Path, tolerance_m: float) -> None:
    """Copy route GeoJSON for the browser, simplified in metres and rounded."""
    frame = gpd.read_file(source)
    if tolerance_m > 0 and not frame.empty:
        projected = frame.to_crs("EPSG:25832")
        projected["geometry"] = projected.geometry.simplify(
            tolerance_m, preserve_topology=False
        )
        frame = projected.to_crs("EPSG:4326")
    destination.unlink(missing_ok=True)
    frame.to_file(destination, driver="GeoJSON", COORDINATE_PRECISION=6)


def rgba_from_hex(color: str, alpha: int = 225) -> tuple[int, int, int, int]:
    value = color.lstrip("#")
    if len(value) != 6:
        raise ValueError(f"Invalid layer color {color!r}")
    return (
        int(value[0:2], 16),
        int(value[2:4], 16),
        int(value[4:6], 16),
        alpha,
    )


def mask_to_rgba(mask: np.ndarray, color: str) -> np.ndarray:
    image = np.zeros((*mask.shape, 4), dtype=np.uint8)
    image[mask] = rgba_from_hex(color)
    return image


def write_tiles(
    pixels: np.ndarray,
    transform: rasterio.Affine,
    crs: str,
    stem: str,
    image_dir: Path,
    max_px: int,
) -> list[dict[str, Any]]:
    """Split an RGBA image into PNG tiles of at most max_px per side.

    Browsers cannot upload WebGL textures larger than their maximum texture
    size (often 4096 on phones and 8192 on laptops), so a single
    country-wide 100 m image renders as a blank rectangle on many devices.
    Fully transparent tiles are skipped.
    """
    for old in image_dir.glob(f"{stem}*.png"):
        if old.stem == stem or old.stem.startswith(f"{stem}_t"):
            old.unlink()
    height, width = pixels.shape[:2]
    row_edges = np.linspace(0, height, math.ceil(height / max_px) + 1).round().astype(int)
    col_edges = np.linspace(0, width, math.ceil(width / max_px) + 1).round().astype(int)
    tiles = []
    for r, (top, bottom) in enumerate(zip(row_edges[:-1], row_edges[1:])):
        for c, (left, right) in enumerate(zip(col_edges[:-1], col_edges[1:])):
            tile = pixels[top:bottom, left:right]
            if not tile[..., 3].any():
                continue
            name = f"{stem}_t{r}_{c}.png"
            Image.fromarray(np.ascontiguousarray(tile), mode="RGBA").save(
                image_dir / name, format="PNG", optimize=True, compress_level=9
            )
            tile_transform = transform * rasterio.Affine.translation(left, top)
            tiles.append(
                {
                    "url": f"data/layers/{name}",
                    "bounds": output_bounds_wgs84(
                        tile_transform, right - left, bottom - top, crs
                    ),
                }
            )
    return tiles


def create_cost_image(
    source: rasterio.io.DatasetReader,
    destination_transform: rasterio.Affine,
    width: int,
    height: int,
    destination_crs: str,
) -> tuple[np.ndarray, float, float]:
    source_data = source.read(1)
    downsampled = np.full((height, width), np.nan, dtype=np.float32)
    reproject(
        source=source_data,
        destination=downsampled,
        src_transform=source.transform,
        src_crs=source.crs,
        src_nodata=source.nodata,
        dst_transform=destination_transform,
        dst_crs=destination_crs,
        dst_nodata=np.nan,
        resampling=Resampling.average,
    )
    valid = np.isfinite(downsampled)
    if not np.any(valid):
        raise ValueError("Cost surface has no valid cells for map rendering")
    low = float(np.nanpercentile(downsampled[valid], 2))
    high = float(np.nanpercentile(downsampled[valid], 98))
    if high <= low:
        high = low + 1
    normalized = np.clip((downsampled - low) / (high - low), 0, 1)
    stops = np.array(
        [[45, 142, 91], [244, 204, 79], [190, 52, 52]], dtype=np.float32
    )
    midpoint = valid & (normalized <= 0.5)
    upper_half = valid & (normalized > 0.5)
    pixels = np.zeros((height, width, 4), dtype=np.uint8)
    for channel in range(3):
        lower = np.interp(
            normalized[midpoint], [0, 0.5], [stops[0, channel], stops[1, channel]]
        )
        upper = np.interp(
            normalized[upper_half],
            [0.5, 1],
            [stops[1, channel], stops[2, channel]],
        )
        pixels[..., channel][midpoint] = lower.astype(np.uint8)
        pixels[..., channel][upper_half] = upper.astype(np.uint8)
    pixels[..., 3][valid] = 205
    return pixels, low, high


def output_bounds_wgs84(
    transform: rasterio.Affine,
    width: int,
    height: int,
    source_crs: str,
) -> list[list[float]]:
    left, top = transform @ (0, 0)
    right, bottom = transform @ (width, height)
    transformer = Transformer.from_crs(source_crs, "EPSG:4326", always_xy=True)
    top_left = transformer.transform(left, top)
    top_right = transformer.transform(right, top)
    bottom_right = transformer.transform(right, bottom)
    bottom_left = transformer.transform(left, bottom)
    return [list(top_left), list(top_right), list(bottom_right), list(bottom_left)]


def make_display_grid(
    bounds: tuple[float, float, float, float],
    source_crs: str,
    resolution: int,
    destination_crs: str = "EPSG:3857",
) -> tuple[rasterio.Affine, int, int]:
    left, bottom, right, top = transform_bounds(
        source_crs, destination_crs, *bounds, densify_pts=41
    )
    left = math.floor(left / resolution) * resolution
    bottom = math.floor(bottom / resolution) * resolution
    right = math.ceil(right / resolution) * resolution
    top = math.ceil(top / resolution) * resolution
    width = int(math.ceil((right - left) / resolution))
    height = int(math.ceil((top - bottom) / resolution))
    return from_origin(left, top, resolution, resolution), width, height


def route_inputs_present(
    config_path: Path = CONFIG,
) -> tuple[bool, str]:
    hotspot_input = ROOT / "data" / "input" / "hotspots.csv"
    outputs = [
        PROCESSED / "routes.geojson",
        PROCESSED / "minimum_spanning_network.geojson",
        PROCESSED / "hotspots.geojson",
    ]
    if not hotspot_input.exists():
        return (
            False,
            "Routes are not published because data/input/hotspots.csv "
            "has not been supplied.",
        )
    missing = [path.name for path in outputs if not path.exists()]
    if missing:
        return (
            False,
            "Hotspots exist, but route outputs are missing: "
            + ", ".join(missing)
            + ". Run python -m src.routing.",
        )
    resolution = int(load_config(config_path)["grid"]["resolution_m"])
    source_files = [
        hotspot_input,
        PROCESSED / f"cost_surface_{resolution}m.tif",
        PROCESSED / f"cost_class_mask_{resolution}m.tif",
        config_path,
        ROOT / "src" / "routing.py",
    ]
    missing_sources = [path.name for path in source_files if not path.exists()]
    if missing_sources:
        return (
            False,
            "Route input files are missing: " + ", ".join(missing_sources) + ".",
        )
    if min(path.stat().st_mtime for path in outputs) < max(
        path.stat().st_mtime for path in source_files
    ):
        return (
            False,
            "Route files are older than the hotspot input, cost surface, or "
            "cost configuration. Run python -m src.routing.",
        )
    return True, "Source-to-storage routes and minimum spanning network are available."


def build_web(
    cost_path: Path | None = None,
    output_dir: Path = WEB,
    config_path: Path = CONFIG,
) -> Path:
    config = load_config(config_path)
    resolution = int(config["grid"]["resolution_m"])
    cost_path = cost_path or PROCESSED / f"cost_surface_{resolution}m.tif"
    mask_path = PROCESSED / f"cost_class_mask_{resolution}m.tif"
    if not cost_path.exists():
        raise FileNotFoundError(f"Cost surface is missing: {cost_path}")
    if not mask_path.exists():
        raise FileNotFoundError(f"Cost-class mask is missing: {mask_path}")
    output_dir.mkdir(parents=True, exist_ok=True)
    image_dir = output_dir / "data" / "layers"
    image_dir.mkdir(parents=True, exist_ok=True)

    with rasterio.open(cost_path) as cost_source:
        if cost_source.crs is None:
            raise ValueError(f"Cost surface has no CRS: {cost_path}")
        if cost_source.res != (resolution, resolution):
            raise ValueError(f"Cost raster resolution differs from config: {cost_path}")
        if cost_source.transform.c % resolution or cost_source.transform.f % resolution:
            raise ValueError("Cost raster origin is not snapped to grid resolution")
        with rasterio.open(mask_path) as mask_source:
            if (
                mask_source.shape != cost_source.shape
                or mask_source.transform != cost_source.transform
                or mask_source.crs != cost_source.crs
            ):
                raise ValueError("Cost raster and class-mask raster do not align")
            saved_bits = json.loads(mask_source.tags().get("class_bits", "{}"))
            configured_bits = {
                name: int(value)
                for name, value in config["class_bits"].items()
            }
            if saved_bits != configured_bits:
                raise ValueError(
                    "Cost-class bit assignments differ from config; "
                    "rebuild the cost surface before building the web map."
                )
            class_mask = mask_source.read(1).astype(np.uint32)

        display_crs = "EPSG:3857"
        display_resolution = int(config.get("web", {}).get("display_resolution_m", 250))
        if display_resolution <= 0:
            raise ValueError("Web display resolution must be positive")
        display_transform, display_width, display_height = make_display_grid(
            cost_source.bounds,
            cost_source.crs.to_string(),
            display_resolution,
            display_crs,
        )
        corners = output_bounds_wgs84(
            display_transform,
            display_width,
            display_height,
            display_crs,
        )
        max_px = int(config.get("web", {}).get("max_image_px", 4096))
        if max_px < 256:
            raise ValueError("web.max_image_px must be at least 256")
        cost_pixels, cost_min, cost_max = create_cost_image(
            cost_source,
            display_transform,
            display_width,
            display_height,
            display_crs,
        )
        cost_tiles = write_tiles(
            cost_pixels, display_transform, display_crs, "cost_surface", image_dir, max_px
        )
        del cost_pixels
        layers: list[dict[str, Any]] = []
        for class_name, (label, color, group) in LAYER_PRESENTATION.items():
            bit = config["class_bits"].get(class_name)
            if bit is None:
                raise ValueError(f"Missing class-bit mapping for {class_name!r}")
            source_layer = (class_mask & int(bit)) != 0
            destination_layer = np.zeros(
                (display_height, display_width), dtype=np.uint8
            )
            reproject(
                source=source_layer.astype(np.uint8),
                destination=destination_layer,
                src_transform=cost_source.transform,
                src_crs=cost_source.crs,
                src_nodata=0,
                dst_transform=display_transform,
                dst_crs=display_crs,
                dst_nodata=0,
                resampling=Resampling.max,
            )
            tiles = write_tiles(
                mask_to_rgba(destination_layer.astype(bool), color),
                display_transform,
                display_crs,
                class_name,
                image_dir,
                max_px,
            )
            layers.append(
                {
                    "id": class_name,
                    "label": label,
                    "group": group,
                    "color": color,
                    "tiles": tiles,
                    "kind": "image",
                    "default_visible": False,
                    "score": class_score_label(config, class_name),
                    "cells": int(np.count_nonzero(source_layer)),
                }
            )
            LOG.info("Rendered %s map overlay", label)

    routes_available, route_status = route_inputs_present(config_path)
    route_layers = []
    if routes_available:
        route_layers = [
            {
                "id": "hotspots",
                "label": "Emitters, hubs, and storage sites",
                "kind": "geojson",
                "url": "data/hotspots.geojson",
            },
            {
                "id": "routes",
                "label": "Source-to-storage routes",
                "kind": "geojson",
                "url": "data/routes.geojson",
            },
            {
                "id": "minimum_spanning_network",
                "label": "Minimum spanning network",
                "kind": "geojson",
                "url": "data/minimum_spanning_network.geojson",
            },
        ]
        (output_dir / "data" / "hotspots.geojson").write_bytes(
            (PROCESSED / "hotspots.geojson").read_bytes()
        )
        corridors = output_dir / "data" / "corridors.geojson"
        if (
            corridors.exists()
            and corridors.stat().st_mtime >= (PROCESSED / "routes.geojson").stat().st_mtime
        ):
            route_layers.append(
                {
                    "id": "corridors",
                    "label": "Corridor of selected route (≤5% extra cost)",
                    "kind": "geojson",
                    "url": "data/corridors.geojson",
                }
            )
        tolerance = float(config.get("web", {}).get("route_simplify_m", 25))
        for relative_path in ("routes.geojson", "minimum_spanning_network.geojson"):
            publish_lines(
                PROCESSED / relative_path,
                output_dir / "data" / relative_path,
                tolerance,
            )

    info = {
        "title": "Denmark CO₂ pipeline routing",
        "version": int(time.time()),
        "crs": "EPSG:25832",
        "resolution_m": resolution,
        "display_resolution_m": display_resolution,
        "display_crs": display_crs,
        "bounds": corners,
        "cost_tiles": cost_tiles,
        "cost_range_percentile_2_98": [cost_min, cost_max],
        "cost_opacity": 0.58,
        "layers": layers,
        "route_layers": route_layers,
        "routes_available": routes_available,
        "route_status": route_status,
        "attribution": "© OpenStreetMap contributors; source datasets attributed in data/SOURCES.md",
        "rendering_note": (
            "Input map overlays are rendered at the analysis grid's display "
            "resolution. Full-resolution source datasets remain available as "
            "processed GeoPackages."
        ),
    }
    data_dir = output_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "map.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    source_register = ROOT / "data" / "SOURCES.md"
    if source_register.exists():
        (output_dir / "SOURCES.md").write_text(
            source_register.read_text(encoding="utf-8"), encoding="utf-8"
        )
    LOG.info("Static map data written to %s", output_dir)
    return output_dir


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render the static MapLibre application assets."
    )
    parser.add_argument("--cost-surface", type=Path)
    parser.add_argument("--output-dir", type=Path, default=WEB)
    parser.add_argument("--config", type=Path, default=CONFIG)
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    build_web(args.cost_surface, args.output_dir, args.config)


if __name__ == "__main__":
    main()
