"""Package the published routing inputs and results for ArcGIS Pro."""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pyogrio
import rasterio
import yaml
from pyproj import Transformer

from src import cost_surface, routing


ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"
WEB_DATA = ROOT / "web" / "data"
OUTPUT = ROOT / "web" / "downloads" / "co2_arcgis_starter_kit.zip"
LOG = logging.getLogger("export_arcgis")
WEIGHT_COLUMNS = (
    "layer",
    "raster",
    "cost_key",
    "weight",
    "treatment",
    "group",
    "surface",
)


def _raster_profile(
    reference: rasterio.io.DatasetReader,
    dtype: str,
    nodata: float | int | None = None,
) -> dict[str, Any]:
    return {
        "driver": "GTiff",
        "width": reference.width,
        "height": reference.height,
        "count": 1,
        "crs": reference.crs,
        "transform": reference.transform,
        "dtype": dtype,
        "nodata": nodata,
        "compress": "LZW",
        "tiled": True,
        "blockxsize": 256,
        "blockysize": 256,
        "BIGTIFF": "IF_SAFER",
    }


def _write_mask(path: Path, profile: dict[str, Any], mask: np.ndarray) -> None:
    with rasterio.open(path, "w", **profile) as target:
        target.write(mask.astype(np.uint8, copy=False), 1)


def _copy_cost_raster(
    source_path: Path, destination: Path, profile: dict[str, Any]
) -> None:
    with rasterio.open(source_path) as source, rasterio.open(
        destination, "w", **profile
    ) as target:
        target.update_tags(**source.tags())
        for _, window in source.block_windows(1):
            target.write(source.read(1, window=window), 1, window=window)


def _write_rasters(directory: Path, config: dict[str, Any]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    reference_path = PROCESSED / "cost_surface_100m.tif"
    with rasterio.open(reference_path) as reference:
        target_crs = str(config["grid"]["crs"])
        resolution = int(config["grid"]["resolution_m"])
        transform, width, height, _ = cost_surface.make_grid(
            PROCESSED / "coast_land_water.gpkg", resolution, target_crs
        )
        actual_grid = (reference.crs, reference.transform, reference.width, reference.height)
        expected_grid = (
            rasterio.crs.CRS.from_string(target_crs),
            transform,
            width,
            height,
        )
        if actual_grid != expected_grid:
            raise ValueError(
                "The published cost surface is not aligned with the configured "
                "analysis grid"
            )

        extent_mask, land_mask = cost_surface.rasterize_extent_and_land(
            transform,
            width,
            height,
            target_crs,
            bool(config["rasterization"]["polygon_all_touched"]),
            bool(config["rasterization"].get("extent_all_touched", False)),
        )
        land_mask &= extent_mask
        sea_mask = extent_mask & ~land_mask
        masks_profile = _raster_profile(reference, "uint8")
        _write_mask(directory / "land.tif", masks_profile, land_mask)
        _write_mask(directory / "sea.tif", masks_profile, sea_mask)

        building_path = PROCESSED / "water_and_urban.gpkg"
        building_mask = cost_surface.rasterize_layer(
            building_path,
            "buildings",
            transform,
            width,
            height,
            bool(config["rasterization"]["polygon_all_touched"]),
            target_crs,
        ).astype(bool)
        building_mask &= extent_mask
        _write_mask(directory / "buildings.tif", masks_profile, building_mask)

        population = cost_surface.population_counts(
            extent_mask, transform, width, height, target_crs, resolution
        )
        population_profile = _raster_profile(
            reference, "float32", float(config["grid"]["nodata"])
        )
        population_path = directory / "population.tif"
        population_values = np.where(
            np.isfinite(population), population, population_profile["nodata"]
        ).astype(np.float32)
        with rasterio.open(population_path, "w", **population_profile) as target:
            target.write(population_values, 1)

        for name, layer_config in config["layers"].items():
            output_path = directory / f"l_{name}.tif"
            source_path = PROCESSED / str(layer_config["file"])
            source_layer = str(layer_config["layer"])
            available = (
                source_path.exists()
                and source_layer
                in {str(row[0]) for row in pyogrio.list_layers(source_path)}
            )
            if not available:
                if not layer_config.get("optional", False):
                    raise FileNotFoundError(
                        f"Required input for {name!r} is unavailable: "
                        f"{source_path}:{source_layer}"
                    )
                LOG.warning(
                    "Optional layer %s is unavailable; exporting an all-zero mask",
                    name,
                )
                layer_mask = np.zeros((height, width), dtype=np.uint8)
            else:
                geometry_type = str(layer_config["geometry"])
                all_touched_key = (
                    "linear_all_touched"
                    if geometry_type == "linear"
                    else "polygon_all_touched"
                )
                layer_mask = cost_surface.rasterize_layer(
                    source_path,
                    source_layer,
                    transform,
                    width,
                    height,
                    bool(config["rasterization"][all_touched_key]),
                    target_crs,
                ).astype(bool)
                layer_mask &= extent_mask
                layer_mask &= ~building_mask
                surface = layer_config.get("surface", "any")
                if surface == "land":
                    layer_mask &= land_mask
                elif surface != "any":
                    raise ValueError(
                        f"Unsupported surface constraint {surface!r} on {name!r}"
                    )
            _write_mask(output_path, masks_profile, layer_mask)
            LOG.info("Wrote %s", output_path.name)

        parallel_config = config.get("parallel_corridor", {})
        parallel_mask = np.zeros((height, width), dtype=bool)
        if parallel_config.get("enabled", False):
            excluded_ids = [
                str(value) for value in parallel_config.get("exclude_osm_ids", [])
            ]
            for asset in parallel_config.get("assets", []):
                asset_path = PROCESSED / str(asset["file"])
                if not asset_path.exists():
                    raise FileNotFoundError(
                        f"Required parallel asset input is missing: {asset_path}"
                    )
                asset_mask = cost_surface.rasterize_layer(
                    asset_path,
                    str(asset["layer"]),
                    transform,
                    width,
                    height,
                    bool(config["rasterization"]["linear_all_touched"]),
                    target_crs,
                    excluded_ids,
                ).astype(bool)
                parallel_mask |= asset_mask
            parallel_mask &= extent_mask
        _write_mask(directory / "parallel_assets.tif", masks_profile, parallel_mask)

        published_profile = _raster_profile(
            reference, reference.dtypes[0], reference.nodata
        )
        _copy_cost_raster(
            reference_path,
            directory / "published_cost_100m.tif",
            published_profile,
        )


def _write_weights(directory: Path, config: dict[str, Any]) -> None:
    groups: dict[str, str] = {}
    for group, group_config in config.get("combine_groups", {}).items():
        for member in group_config.get("members", []):
            groups[str(member)] = str(group)

    with (directory / "weights.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=WEIGHT_COLUMNS)
        writer.writeheader()
        for name, layer in config["layers"].items():
            cost_key = str(layer["cost"])
            is_barrier = cost_key in config.get("barriers", [])
            weight: Any = "barrier" if is_barrier else config["costs"][cost_key]
            if isinstance(weight, (dict, list)):
                weight = json.dumps(weight, ensure_ascii=False, sort_keys=True)
            writer.writerow(
                {
                    "layer": name,
                    "raster": f"l_{name}.tif",
                    "cost_key": cost_key,
                    "weight": weight,
                    "treatment": "barrier" if is_barrier else "cost",
                    "group": groups.get(cost_key, ""),
                    "surface": layer.get("surface", "any"),
                }
            )


def _write_geodatabase(directory: Path, config: dict[str, Any]) -> None:
    gdb_path = directory / "co2_routing.gdb"
    target_crs = str(config["grid"]["crs"])

    def write_layer(frame: gpd.GeoDataFrame, name: str) -> None:
        if frame.crs is None:
            raise ValueError(f"Geodatabase layer {name!r} has no CRS")
        if frame.crs.to_string() != target_crs:
            frame = frame.to_crs(target_crs)
        pyogrio.write_dataframe(
            frame,
            gdb_path,
            layer=name,
            driver="OpenFileGDB",
            append=gdb_path.exists(),
        )

    with rasterio.open(PROCESSED / "cost_surface_100m.tif") as surface:
        valid_cells = surface.read(1)
        valid_cells = np.isfinite(valid_cells) & (valid_cells != surface.nodata)
        transformer = Transformer.from_crs("EPSG:4326", target_crs, always_xy=True)
        sites = routing.load_hotspots(
            routing.HOTSPOTS_FILE,
            transformer,
            surface.width,
            surface.height,
            surface.transform,
            valid_cells,
            int(config["grid"]["resolution_m"]),
            float(config.get("routing", {}).get("max_snap_distance_m", 2000)),
        )
        site_rows = []
        site_geometries = []
        for site in sites:
            x, y = rasterio.transform.xy(
                surface.transform, site["row"], site["col"], offset="center"
            )
            site_rows.append(
                {
                    "id": site["id"],
                    "name": site["name"],
                    "role": site["role"],
                    "coordinate_basis": "snapped_cell_center",
                    "snap_distance_m": site["snap_distance_m"],
                    "original_lon": site["lon"],
                    "original_lat": site["lat"],
                }
            )
            site_geometries.append(gpd.points_from_xy([x], [y])[0])
        sites_frame = gpd.GeoDataFrame(
            site_rows, geometry=site_geometries, crs=target_crs
        )
        if set(sites_frame["role"]) != {"source", "storage"}:
            raise ValueError(
                "Starter-kit sites must have source/storage roles; "
                f"found {sorted(set(sites_frame['role']))}"
            )
        write_layer(sites_frame, "sites")

    area = gpd.read_file(
        PROCESSED / "coast_land_water.gpkg", layer="analysis_extent"
    )
    area["area_id"] = "analysis_extent"
    area["name"] = "Denmark and surrounding routing waters"
    write_layer(area, "analysis_area")

    for filename, layer_name in (
        ("routes.geojson", "published_routes"),
        ("minimum_spanning_network.geojson", "published_network"),
        ("corridors.geojson", "published_corridors"),
    ):
        source = WEB_DATA / filename
        if not source.exists():
            raise FileNotFoundError(f"Published result is missing: {source}")
        write_layer(gpd.read_file(source), layer_name)

    storage = PROCESSED / "storage_areas.geojson"
    if not storage.exists():
        raise FileNotFoundError(f"Storage-area polygons are missing: {storage}")
    write_layer(gpd.read_file(storage), "storage_areas")

    baltic_pipe = ROOT / "validation" / "baltic_pipe_osm.geojson"
    if not baltic_pipe.exists():
        raise FileNotFoundError(f"Baltic Pipe OSM reference is missing: {baltic_pipe}")
    write_layer(gpd.read_file(baltic_pipe), "baltic_pipe_osm")


def _write_readme(directory: Path, config: dict[str, Any]) -> None:
    resolution = int(config["grid"]["resolution_m"])
    lines = [
        "Research and teaching tool, provided as is; not engineering or",
        "permitting advice. Unzip into a NEW, EMPTY folder and back up your",
        "ArcGIS project first. See DISCLAIMER.",
        "",
        "Denmark CO2 Routing - ArcGIS Pro ModelBuilder starter kit",
        "",
        "Contents: rasters/ (aligned input masks and published cost raster),",
        "co2_routing.gdb (sites and published vector results), weights.csv,",
        "SOURCES.md (source URLs, dates, licences, and attribution), and",
        "DISCLAIMER.md (scope limits, data caveats, and backup checklist).",
        "",
        f"Grid: EPSG:25832; {resolution} m cells; exact transform, width, and",
        "height of the project's data/processed/cost_surface_100m.tif.",
        "All rasters are GeoTIFF with LZW compression. Binary masks use 1 for",
        "present and 0 for absent; 0 outside the analysis area. population.tif",
        "is people per cell with NoData outside the area. The published cost",
        "surface retains its configured NoData value.",
        "",
        "sites in the geodatabase are snapped to the center of their nearest",
        "traversable cost-grid cell; coordinate_basis and snap_distance_m",
        "record this, and original_lon/original_lat preserve the input point.",
        "",
        "l_<layer>.tif files follow config/costs.yaml and the Python cost",
        "surface rasterization rules. Missing optional layers are all-zero",
        "masks. parallel_assets.tif is the configured power-line and gas-pipe",
        "input mask before the 50-300 m corridor band is calculated.",
        "weights.csv has an empty reason column omitted; add explanations",
        "from the project labels if desired. JSON text in weight represents",
        "a configured distance/population rule rather than a single scalar.",
        "",
        "Attribution and licences: OpenStreetMap-derived content, including",
        "the Baltic Pipe reference and infrastructure layers, is (c) OpenStreetMap",
        "contributors and available under the Open Database License (ODbL).",
        "Other source-specific licences and publisher attribution are listed",
        "in SOURCES.md; retain those notices when reusing the data.",
        "",
        "See modelbuilder.md for the step-by-step ArcGIS Pro workflow.",
        "Read DISCLAIMER.md before importing or reusing this package.",
        "The published rasters/routes are analysis outputs, not engineering",
        "designs, permits, cost estimates, or proof of storage capacity.",
    ]
    (directory / "README.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for filename in ("DISCLAIMER.md", "LICENSE"):
        source = ROOT / filename
        if not source.exists():
            raise FileNotFoundError(f"Required package document is missing: {source}")
        (directory / filename).write_text(
            source.read_text(encoding="utf-8"), encoding="utf-8"
        )
    source_register = ROOT / "data" / "SOURCES.md"
    if source_register.exists():
        (directory / "SOURCES.md").write_text(
            source_register.read_text(encoding="utf-8"), encoding="utf-8"
        )
    else:
        raise FileNotFoundError(f"Source register is missing: {source_register}")


def _write_archive(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.unlink(missing_ok=True)
    try:
        with zipfile.ZipFile(
            temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
        ) as archive:
            for path in sorted(source.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(source).as_posix())
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def export_starter_kit(
    output: Path = OUTPUT,
    config_path: Path = cost_surface.CONFIG,
) -> Path:
    config = cost_surface.load_config(config_path)
    build_root = ROOT / "build"
    build_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="arcgis-starter-kit-", dir=build_root) as temp:
        package = Path(temp)
        _write_rasters(package / "rasters", config)
        _write_geodatabase(package, config)
        _write_weights(package, config)
        _write_readme(package, config)
        _write_archive(package, output)
    size_mb = output.stat().st_size / 1_000_000
    LOG.info("Wrote %s (%.1f MB)", output, size_mb)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export the ArcGIS Pro ModelBuilder starter kit."
    )
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--config", type=Path, default=cost_surface.CONFIG)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    export_starter_kit(args.output, args.config)


if __name__ == "__main__":
    main()
