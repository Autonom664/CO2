"""Compute near-optimal least-cost corridors for each delivery route.

A cell belongs to the corridor of route s → t when the cheapest path from s to
t through that cell costs at most (1 + tolerance) times the optimal route
cost. With MCP_Geometric the cost of the best path through a cell equals the
sum of the two accumulated-cost surfaces from s and from t, so each hotspot
needs only one cost-distance run.
"""

from __future__ import annotations

import argparse
import logging
import math
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.features import shapes
from rasterio.windows import Window
from shapely.geometry import MultiPolygon, Polygon, shape
from shapely.ops import unary_union
from skimage.graph import MCP_Geometric

from src import routing


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "web" / "data" / "corridors.geojson"
LOG = logging.getLogger("corridors")


def accumulated_cost(mcp_cost: np.ndarray, cell: tuple[int, int]) -> np.ndarray:
    graph = MCP_Geometric(mcp_cost, fully_connected=True)
    costs, _ = graph.find_costs([cell])
    return costs


def corridor_polygon(
    through_cost: np.ndarray,
    optimum: float,
    tolerance: float,
    transform: rasterio.Affine,
    simplify_m: float,
    min_hole_m2: float = 0,
) -> tuple[Any, int]:
    mask = through_cost <= optimum * (1 + tolerance)
    rows = np.flatnonzero(mask.any(axis=1))
    cols = np.flatnonzero(mask.any(axis=0))
    if rows.size == 0:
        return None, 0
    window = Window(
        cols[0], rows[0], cols[-1] - cols[0] + 1, rows[-1] - rows[0] + 1
    )
    sub = mask[rows[0] : rows[-1] + 1, cols[0] : cols[-1] + 1]
    sub_transform = rasterio.windows.transform(window, transform)
    parts = [
        shape(geometry)
        for geometry, value in shapes(
            sub.astype(np.uint8), mask=sub, transform=sub_transform
        )
        if value
    ]
    polygon = drop_small_holes(unary_union(parts), min_hole_m2)
    if simplify_m > 0:
        polygon = polygon.simplify(simplify_m, preserve_topology=True)
    return polygon, int(np.count_nonzero(sub))


def drop_small_holes(geometry: Any, min_area_m2: float) -> Any:
    """Remove interior rings smaller than min_area_m2 (towns, lakes, farms).

    They carry little meaning at corridor scale but dominate the file size.
    """
    if min_area_m2 <= 0:
        return geometry
    polygons = geometry.geoms if isinstance(geometry, MultiPolygon) else [geometry]
    kept = [
        Polygon(
            polygon.exterior,
            [ring for ring in polygon.interiors if Polygon(ring).area >= min_area_m2],
        )
        for polygon in polygons
    ]
    return kept[0] if len(kept) == 1 else MultiPolygon(kept)


def compute_corridors(
    hotspots_path: Path = routing.HOTSPOTS_FILE,
    config_path: Path = routing.CONFIG_FILE,
    output: Path = OUTPUT,
    tolerances: tuple[float, ...] = (0.01, 0.03),
    simplify_m: float = 150.0,
    min_hole_km2: float = 2.0,
) -> Path:
    if not tolerances or min(tolerances) <= 0:
        raise ValueError("Corridor tolerances must be positive")
    config = routing.load_config(config_path)
    resolution = int(config["grid"]["resolution_m"])
    cost_path = routing.PROCESSED / f"cost_surface_{resolution}m.tif"
    max_snap_m = float(config.get("routing", {}).get("max_snap_distance_m", 2000))
    with rasterio.open(cost_path) as source:
        nodata = source.nodata
        if nodata is None or source.crs is None:
            raise ValueError(f"Cost raster needs a CRS and NoData value: {cost_path}")
        cost = source.read(1)
        transform = source.transform
        crs = source.crs
    valid = np.isfinite(cost) & (cost != nodata) & (cost > 0)
    hotspots = routing.load_hotspots(
        hotspots_path,
        Transformer.from_crs("EPSG:4326", crs, always_xy=True),
        cost.shape[1],
        cost.shape[0],
        transform,
        valid,
        resolution,
        max_snap_m,
    )
    pairs = routing.make_route_pairs(hotspots)
    mcp_cost = routing.make_mcp_cost_array(cost, valid)
    del cost

    targets = list({end["id"]: end for _, end in pairs}.values())
    target_costs: dict[str, np.ndarray] = {}
    for end in targets:
        LOG.info("Cost distance from %s", end["name"])
        target_costs[end["id"]] = accumulated_cost(
            mcp_cost, (end["row"], end["col"])
        ).astype(np.float32)

    records: list[dict[str, Any]] = []
    geometries = []
    cell_area_km2 = resolution * resolution / 1_000_000
    for start in list({start["id"]: start for start, _ in pairs}.values()):
        LOG.info("Cost distance from %s", start["name"])
        from_start = accumulated_cost(mcp_cost, (start["row"], start["col"]))
        for pair_start, end in pairs:
            if pair_start["id"] != start["id"]:
                continue
            optimum = float(from_start[end["row"], end["col"]])
            if not math.isfinite(optimum):
                LOG.warning("%s → %s is unreachable", start["name"], end["name"])
                continue
            through = from_start + target_costs[end["id"]]
            # Widest band first so narrower bands draw on top of it.
            for tolerance in sorted(tolerances, reverse=True):
                polygon, cells = corridor_polygon(
                    through, optimum, tolerance, transform, simplify_m,
                    min_hole_km2 * 1_000_000,
                )
                if polygon is None or polygon.is_empty:
                    continue
                records.append(
                    {
                        "from_id": start["id"],
                        "from_name": start["name"],
                        "to_id": end["id"],
                        "to_name": end["name"],
                        "tolerance": tolerance,
                        "optimal_cost": round(optimum, 3),
                        "area_km2": round(cells * cell_area_km2, 1),
                    }
                )
                geometries.append(polygon)
        del from_start
    if not records:
        raise ValueError("No corridors could be computed")
    frame = gpd.GeoDataFrame(records, geometry=geometries, crs=crs).to_crs(
        "EPSG:4326"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    frame.to_file(output, driver="GeoJSON", COORDINATE_PRECISION=4)
    LOG.info("Wrote %d corridors to %s", len(frame), output)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compute near-optimal corridors for each delivery route."
    )
    parser.add_argument(
        "--tolerances", default="0.01,0.03",
        help="Comma-separated extra-cost bands, for example 0.01,0.03",
    )
    parser.add_argument("--min-hole-km2", type=float, default=2.0)
    parser.add_argument("--simplify-m", type=float, default=150.0)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    compute_corridors(
        output=args.output,
        tolerances=tuple(float(v) for v in args.tolerances.split(",")),
        simplify_m=args.simplify_m,
        min_hole_km2=args.min_hole_km2,
    )


if __name__ == "__main__":
    main()
