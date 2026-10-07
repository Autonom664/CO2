"""Compute least-cost paths between CO2 sources and storage hotspots."""

from __future__ import annotations

import argparse
import csv
import json
import logging
import math
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import rasterio
import yaml
from pyproj import Transformer
from shapely.geometry import LineString, Point
from skimage.graph import MCP_Geometric


ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"
HOTSPOTS_FILE = ROOT / "data" / "input" / "hotspots.csv"
CONFIG_FILE = ROOT / "config" / "costs.yaml"
LOG = logging.getLogger("routing")
EXPECTED_HOTSPOTS = 12

CLASS_PROPERTIES = {
    "open_land": "km_open_land",
    "open_sea": "km_open_sea",
    "road_crossing": "km_road_crossing",
    "railway_crossing": "km_railway_crossing",
    "watercourse_crossing": "km_watercourse_crossing",
    "urban_area": "km_urban_area",
    "lake": "km_lake",
    "wetland": "km_wetland",
    "natura2000": "km_natura2000",
    "protected_nature": "km_protected_nature",
    "population": "km_population",
}


def load_config(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        config = yaml.safe_load(stream)
    if not isinstance(config, dict):
        raise ValueError(f"Expected a YAML mapping in {path}")
    return config


def load_hotspots(
    path: Path,
    transformer: Transformer,
    width: int,
    height: int,
    transform: rasterio.Affine,
    valid_cells: np.ndarray,
    resolution: int,
    max_snap_m: float,
) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(
            f"Hotspot input is required for routing: {path}. "
            "Provide 12 rows with id,name,lon,lat columns; the coordinates "
            "must be documented candidate locations."
        )
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"id", "name", "lon", "lat"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError(
                f"{path} must contain columns: id, name, lon, lat"
            )
        records = list(reader)
    if len(records) != EXPECTED_HOTSPOTS:
        raise ValueError(
            f"Expected {EXPECTED_HOTSPOTS} hotspots, found {len(records)}"
        )

    identifiers: set[str] = set()
    hotspots: list[dict[str, Any]] = []
    for record in records:
        identifier = record["id"].strip()
        name = record["name"].strip()
        if not identifier or not name:
            raise ValueError("Hotspot ids and names must not be blank")
        if identifier in identifiers:
            raise ValueError(f"Duplicate hotspot id: {identifier!r}")
        identifiers.add(identifier)
        try:
            lon, lat = float(record["lon"]), float(record["lat"])
        except (TypeError, ValueError) as error:
            raise ValueError(
                f"Invalid WGS84 coordinate for hotspot {identifier!r}"
            ) from error
        if not math.isfinite(lon) or not math.isfinite(lat):
            raise ValueError(f"Non-finite coordinate for hotspot {identifier!r}")
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise ValueError(f"Coordinate outside WGS84 range for {identifier!r}")
        x, y = transformer.transform(lon, lat)
        row, col = rasterio.transform.rowcol(transform, x, y)
        if row < 0 or col < 0 or row >= height or col >= width:
            raise ValueError(
                f"Hotspot {identifier!r} is outside the cost-surface extent"
            )
        nearest = nearest_valid_cell(
            valid_cells, row, col, resolution, max_snap_m, identifier
        )
        snapped_row, snapped_col, snap_distance = nearest
        hotspots.append(
            {
                "id": identifier,
                "name": name,
                "role": (record.get("role") or "node").strip().lower(),
                "site_type": (record.get("site_type") or "").strip(),
                "project_status": (record.get("project_status") or "").strip(),
                "location_basis": (record.get("location_basis") or "").strip(),
                "source_url": (record.get("source_url") or "").strip(),
                "project_source_url": (
                    record.get("project_source_url") or ""
                ).strip(),
                "lon": lon,
                "lat": lat,
                "x": x,
                "y": y,
                "row": snapped_row,
                "col": snapped_col,
                "snap_distance_m": snap_distance,
            }
        )
        if snap_distance:
            LOG.warning(
                "Hotspot %s snapped %.1f m to the nearest traversable cell",
                identifier,
                snap_distance,
            )
    snapped_cells = [(point["row"], point["col"]) for point in hotspots]
    if len(set(snapped_cells)) != len(snapped_cells):
        raise ValueError(
            "Two or more hotspots snap to the same traversable grid cell; "
            "review hotspot locations or increase grid resolution."
        )
    return hotspots


def make_route_pairs(
    hotspots: list[dict[str, Any]],
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    roles = {point["role"] for point in hotspots}
    if roles == {"node"}:
        return [
            (start, end)
            for index, start in enumerate(hotspots[:-1])
            for end in hotspots[index + 1 :]
        ]
    if roles != {"source", "storage"}:
        raise ValueError(
            "Set role=source or role=storage on every hotspot, or leave all "
            "roles blank to route all unordered pairs."
        )
    sources = [point for point in hotspots if point["role"] == "source"]
    storage = [point for point in hotspots if point["role"] == "storage"]
    return [(source, sink) for source in sources for sink in storage]


def nearest_valid_cell(
    valid_cells: np.ndarray,
    row: int,
    col: int,
    resolution: int,
    max_snap_m: float,
    identifier: str,
) -> tuple[int, int, float]:
    radius = int(math.ceil(max_snap_m / resolution))
    row_min = max(0, row - radius)
    row_max = min(valid_cells.shape[0], row + radius + 1)
    col_min = max(0, col - radius)
    col_max = min(valid_cells.shape[1], col + radius + 1)
    local = valid_cells[row_min:row_max, col_min:col_max]
    valid_rows, valid_cols = np.nonzero(local)
    if valid_rows.size == 0:
        raise ValueError(
            f"No traversable cell within {max_snap_m:g} m of hotspot {identifier!r}"
        )
    valid_rows += row_min
    valid_cols += col_min
    distance_squared = (valid_rows - row) ** 2 + (valid_cols - col) ** 2
    nearest_index = int(np.argmin(distance_squared))
    distance = math.sqrt(float(distance_squared[nearest_index])) * resolution
    if distance > max_snap_m:
        raise ValueError(
            f"Nearest traversable cell for hotspot {identifier!r} is "
            f"{distance:.1f} m away; maximum allowed is {max_snap_m:g} m"
        )
    return (
        int(valid_rows[nearest_index]),
        int(valid_cols[nearest_index]),
        distance,
    )


def cell_center(
    transform: rasterio.Affine, row: int, col: int
) -> tuple[float, float]:
    return rasterio.transform.xy(transform, row, col, offset="center")


def build_route_feature(
    start: dict[str, Any],
    end: dict[str, Any],
    path: list[tuple[int, int]],
    accumulated_cost: float,
    class_mask: np.ndarray,
    transform: rasterio.Affine,
    resolution: int,
    class_bits: dict[str, int],
    route_classes: dict[str, list[str]],
) -> dict[str, Any]:
    coordinates = [cell_center(transform, row, col) for row, col in path]
    line = LineString(coordinates)
    class_km = {name: 0.0 for name in CLASS_PROPERTIES}
    for (row_a, col_a), (row_b, col_b) in zip(path, path[1:]):
        segment_length_m = resolution * math.hypot(row_b - row_a, col_b - col_a)
        bits = int(class_mask[row_b, col_b])
        for class_name, property_name in CLASS_PROPERTIES.items():
            bit_names = route_classes.get(class_name, [class_name])
            if any(bits & int(class_bits[bit_name]) for bit_name in bit_names):
                class_km[class_name] += segment_length_m / 1000
    properties: dict[str, Any] = {
        "from": start["name"],
        "to": end["name"],
        "from_id": start["id"],
        "from_name": start["name"],
        "to_id": end["id"],
        "to_name": end["name"],
        "length_km": round(line.length / 1000, 3),
        "accumulated_cost": round(float(accumulated_cost), 3),
        "from_snap_m": round(float(start["snap_distance_m"]), 1),
        "to_snap_m": round(float(end["snap_distance_m"]), 1),
        "from_role": start.get("role", "node"),
        "to_role": end.get("role", "node"),
        "from_site_type": start.get("site_type", ""),
        "to_site_type": end.get("site_type", ""),
        "from_project_status": start.get("project_status", ""),
        "to_project_status": end.get("project_status", ""),
    }
    properties.update(
        {
            property_name: round(class_km[class_name], 3)
            for class_name, property_name in CLASS_PROPERTIES.items()
        }
    )
    return {"geometry": line, "properties": properties}


def minimum_spanning_tree(
    routes: list[dict[str, Any]], hotspot_count: int
) -> list[dict[str, Any]]:
    parent = list(range(hotspot_count))
    rank = [0] * hotspot_count

    def find(node: int) -> int:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    selected: list[dict[str, Any]] = []
    vertices = list(
        dict.fromkeys(
            identifier
            for route in routes
            for identifier in (
                route["properties"]["from_id"],
                route["properties"]["to_id"],
            )
        )
    )
    if len(vertices) != hotspot_count:
        raise ValueError(
            f"Route graph contains {len(vertices)} hotspots, expected {hotspot_count}"
        )
    index_by_id = {identifier: index for index, identifier in enumerate(vertices)}
    edges = sorted(
        routes,
        key=lambda route: (
            route["properties"]["accumulated_cost"],
            route["properties"]["from_id"],
            route["properties"]["to_id"],
        ),
    )
    for route in edges:
        properties = route["properties"]
        left = index_by_id[properties["from_id"]]
        right = index_by_id[properties["to_id"]]
        root_left, root_right = find(left), find(right)
        if root_left == root_right:
            continue
        if rank[root_left] < rank[root_right]:
            root_left, root_right = root_right, root_left
        parent[root_right] = root_left
        if rank[root_left] == rank[root_right]:
            rank[root_left] += 1
        selected.append(route)
        if len(selected) == hotspot_count - 1:
            break
    if len(selected) != hotspot_count - 1:
        raise ValueError(
            "The pairwise route graph is disconnected; no spanning tree exists"
        )
    return selected


def save_geojson(
    features: list[dict[str, Any]], path: Path, crs: str
) -> None:
    if not features:
        raise ValueError(f"Refusing to write empty route output: {path}")
    frame = gpd.GeoDataFrame(
        [feature["properties"] for feature in features],
        geometry=[feature["geometry"] for feature in features],
        crs=crs,
    ).to_crs("EPSG:4326")
    frame.to_file(path, driver="GeoJSON", index=False)


def route_hotspots(
    hotspots_path: Path = HOTSPOTS_FILE,
    cost_path: Path | None = None,
    config_path: Path = CONFIG_FILE,
) -> tuple[Path, Path, Path]:
    config = load_config(config_path)
    resolution = int(config["grid"]["resolution_m"])
    cost_path = cost_path or PROCESSED / f"cost_surface_{resolution}m.tif"
    class_path = PROCESSED / f"cost_class_mask_{resolution}m.tif"
    if not class_path.exists():
        raise FileNotFoundError(
            f"Route-class raster is missing: {class_path}. "
            "Rebuild the cost surface first."
        )
    max_snap_m = float(config.get("routing", {}).get("max_snap_distance_m", 2000))
    with rasterio.open(cost_path) as source:
        if source.count != 1 or source.crs is None:
            raise ValueError(f"Expected a single-band projected cost raster: {cost_path}")
        nodata = source.nodata
        if nodata is None:
            raise ValueError(f"Cost raster has no NoData value: {cost_path}")
        cost = source.read(1)
        transform = source.transform
        crs = source.crs
        valid = np.isfinite(cost) & (cost != nodata) & (cost > 0)
        resolution_x, resolution_y = source.res
        if not math.isclose(resolution_x, resolution_y):
            raise ValueError("Routing requires square grid cells")
        if not math.isclose(resolution_x, resolution):
            raise ValueError("Cost raster resolution does not match the config")
        class_mask = np.zeros(cost.shape, dtype=np.uint16)
        with rasterio.open(class_path) as class_source:
            if (
                class_source.shape != source.shape
                or class_source.transform != source.transform
                or class_source.crs != source.crs
            ):
                raise ValueError("Cost and route-class rasters do not align")
            saved_bits = json.loads(class_source.tags().get("class_bits", "{}"))
            configured_bits = {
                name: int(value) for name, value in config["class_bits"].items()
            }
            if saved_bits != configured_bits:
                raise ValueError(
                    "Cost-class bit assignments differ from config; "
                    "rebuild the cost surface before routing."
                )
            class_mask = class_source.read(1)
    hotspots = load_hotspots(
        hotspots_path,
        Transformer.from_crs("EPSG:4326", crs, always_xy=True),
        cost.shape[1],
        cost.shape[0],
        transform,
        valid,
        resolution,
        max_snap_m,
    )
    route_pairs = make_route_pairs(hotspots)
    pairs_by_source: dict[str, list[dict[str, Any]]] = {}
    for start, end in route_pairs:
        pairs_by_source.setdefault(start["id"], []).append(end)
    class_bits = {name: int(value) for name, value in config["class_bits"].items()}
    masked_cost = np.ma.MaskedArray(cost, mask=~valid)
    routes: list[dict[str, Any]] = []
    pair_count = len(route_pairs)
    pair_processed = 0
    starts = [point for point in hotspots if point["id"] in pairs_by_source]
    for source_index, start in enumerate(starts):
        LOG.info(
            "Running cost distance from hotspot %s (%s/%s)",
            start["id"],
            source_index + 1,
            len(starts),
        )
        mcp = MCP_Geometric(masked_cost, fully_connected=True)
        cumulative, _ = mcp.find_costs([(start["row"], start["col"])])
        for end in pairs_by_source[start["id"]]:
            pair_processed += 1
            destination = (end["row"], end["col"])
            total_cost = float(cumulative[destination])
            if not math.isfinite(total_cost):
                LOG.error(
                    "No traversable route between %s and %s",
                    start["id"],
                    end["id"],
                )
                continue
            path = mcp.traceback(destination)
            route = build_route_feature(
                start,
                end,
                path,
                total_cost,
                class_mask,
                transform,
                resolution,
                class_bits,
                config.get("route_classes", {}),
            )
            routes.append(route)
            LOG.info(
                "Routed pair %s/%s: %s to %s",
                pair_processed,
                pair_count,
                start["id"],
                end["id"],
            )
        del mcp, cumulative

    if not routes:
        raise ValueError("No hotspot pairs could be routed")
    mst_error: ValueError | None = None
    try:
        mst = minimum_spanning_tree(routes, len(hotspots))
    except ValueError as error:
        mst = []
        mst_error = error
    PROCESSED.mkdir(parents=True, exist_ok=True)
    routes_path = PROCESSED / "routes.geojson"
    network_path = PROCESSED / "minimum_spanning_network.geojson"
    save_geojson(routes, routes_path, crs.to_string())

    route_by_pair = {
        (route["properties"]["from_id"], route["properties"]["to_id"]): route
        for route in routes
    }
    pairwise_path = PROCESSED / "pairwise_route_costs.csv"
    with pairwise_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            ["from_id", "from_name", "to_id", "to_name", "status", "length_km", "accumulated_cost"]
        )
        for start, end in route_pairs:
            route = route_by_pair.get((start["id"], end["id"]))
            properties = route["properties"] if route else {}
            writer.writerow(
                [
                    start["id"],
                    start["name"],
                    end["id"],
                    end["name"],
                    "routed" if route else "unreachable",
                    properties.get("length_km", ""),
                    properties.get("accumulated_cost", ""),
                ]
            )

    hotspot_frame = gpd.GeoDataFrame(
        [
            {
                "id": point["id"],
                "name": point["name"],
                "lon": point["lon"],
                "lat": point["lat"],
                "role": point["role"],
                "site_type": point["site_type"],
                "project_status": point["project_status"],
                "location_basis": point["location_basis"],
                "source_url": point["source_url"],
                "project_source_url": point["project_source_url"],
                "snap_m": round(point["snap_distance_m"], 1),
            }
            for point in hotspots
        ],
        geometry=[Point(point["x"], point["y"]) for point in hotspots],
        crs=crs,
    ).to_crs("EPSG:4326")
    hotspot_frame.to_file(
        PROCESSED / "hotspots.geojson", driver="GeoJSON", index=False
    )
    if mst_error is not None:
        raise ValueError(
            "No connected minimum spanning tree exists. Pairwise reachable "
            "routes and pairwise_route_costs.csv were saved for diagnosis."
        ) from mst_error
    save_geojson(mst, network_path, crs.to_string())
    if len(routes) != pair_count:
        raise ValueError(
            f"Only {len(routes)} of {pair_count} hotspot pairs were routed. "
            "See pairwise_route_costs.csv for unreachable pairs."
        )
    LOG.info(
        "Wrote %s pair routes, %s minimum-spanning edges",
        len(routes),
        len(mst),
    )
    return routes_path, network_path, pairwise_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Route source-to-storage pairs across the configured cost surface."
    )
    parser.add_argument("--hotspots", type=Path, default=HOTSPOTS_FILE)
    parser.add_argument("--cost-surface", type=Path)
    parser.add_argument("--config", type=Path, default=CONFIG_FILE)
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    route_hotspots(args.hotspots, args.cost_surface, args.config)


if __name__ == "__main__":
    main()
