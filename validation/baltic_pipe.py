"""Validate the cost model against the as-built Baltic Pipe route in Denmark.

Routes a least-cost path between the two onshore ends of the real pipeline
(OSM geometry in validation/baltic_pipe_osm.geojson) and reports how far the
modelled route lies from the built one. Run after the cost surface exists:

    python -m validation.baltic_pipe
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import rasterio
from shapely.geometry import LineString, MultiLineString
from shapely.ops import linemerge
from skimage.graph import MCP_Geometric

from src import corridors, routing


HERE = Path(__file__).resolve().parent
REFERENCE = HERE / "baltic_pipe_osm.geojson"
REPORT = HERE / "baltic_pipe_report.json"
MODEL_ROUTE = HERE / "baltic_pipe_model.geojson"
LOG = logging.getLogger("validation")


def sample_points(line: LineString, step_m: float) -> list:
    count = max(2, int(line.length // step_m) + 1)
    return [line.interpolate(i / (count - 1), normalized=True) for i in range(count)]


def compare_lines(
    model: LineString, reference: LineString | MultiLineString, step_m: float = 100
) -> dict[str, float]:
    """Distance statistics of the model route from the reference, in km."""
    offsets = np.array(
        [reference.distance(point) for point in sample_points(model, step_m)]
    )
    parts = reference.geoms if isinstance(reference, MultiLineString) else [reference]
    reverse = np.array(
        [model.distance(point) for part in parts for point in sample_points(part, step_m)]
    )
    stats = {
        "model_km": round(model.length / 1000, 1),
        "reference_km": round(reference.length / 1000, 1),
        "length_ratio": round(model.length / reference.length, 3),
        "mean_offset_km": round(float(offsets.mean()) / 1000, 2),
        "median_offset_km": round(float(np.median(offsets)) / 1000, 2),
        "p90_offset_km": round(float(np.percentile(offsets, 90)) / 1000, 2),
        "max_offset_km": round(float(offsets.max()) / 1000, 2),
        "share_model_within_1km": round(float((offsets <= 1000).mean()), 3),
        "share_model_within_5km": round(float((offsets <= 5000).mean()), 3),
        "share_reference_within_5km_of_model": round(
            float((reverse <= 5000).mean()), 3
        ),
    }
    return stats


def load_reference(crs: Any) -> LineString | MultiLineString:
    frame = gpd.read_file(REFERENCE).to_crs(crs)
    merged = linemerge(frame.union_all())
    if merged.is_empty:
        raise ValueError(f"No reference geometry in {REFERENCE}")
    return merged


def endpoints(reference: LineString | MultiLineString) -> tuple[tuple, tuple]:
    if isinstance(reference, LineString):
        return reference.coords[0], reference.coords[-1]
    ends = [part.coords[i] for part in reference.geoms for i in (0, -1)]
    # Furthest-apart pair of loose ends spans the whole pipeline.
    best = max(
        ((a, b) for a in ends for b in ends),
        key=lambda pair: (pair[0][0] - pair[1][0]) ** 2 + (pair[0][1] - pair[1][1]) ** 2,
    )
    return best


def choose_cost_surface(resolution: int, explicit: Path | None) -> tuple[Path, bool]:
    """Prefer the validation surface that excludes Baltic Pipe's own OSM ways.

    Returns the path and whether the result is biased (published surface,
    whose parallel-corridor discount includes the pipeline being checked).
    """
    name = f"cost_surface_{resolution}m.tif"
    if explicit is not None:
        return explicit, explicit.resolve() == (routing.PROCESSED / name).resolve()
    validation = routing.PROCESSED / "validation" / name
    if validation.exists():
        return validation, False
    return routing.PROCESSED / name, True


def run(
    tolerances: tuple[float, ...] = (0.01, 0.03),
    cost_path: Path | None = None,
) -> dict[str, Any]:
    config = routing.load_config(routing.CONFIG_FILE)
    resolution = int(config["grid"]["resolution_m"])
    max_snap_m = float(config.get("routing", {}).get("max_snap_distance_m", 2000))
    cost_path, biased = choose_cost_surface(resolution, cost_path)
    if biased:
        LOG.warning(
            "Using the published cost surface: its infrastructure discount "
            "includes Baltic Pipe itself, so the result is biased."
        )
    with rasterio.open(cost_path) as source:
        cost = source.read(1)
        transform, crs, nodata = source.transform, source.crs, source.nodata
    valid = np.isfinite(cost) & (cost != nodata) & (cost > 0)
    reference = load_reference(crs)
    cells = []
    for label, (x, y) in zip(("west", "east"), endpoints(reference)):
        row, col = rasterio.transform.rowcol(transform, x, y)
        cells.append(routing.nearest_valid_cell(
            valid, row, col, x, y, transform, resolution, max_snap_m, label
        )[:2])
    mcp_cost = routing.make_mcp_cost_array(cost, valid)
    del cost
    graph = MCP_Geometric(mcp_cost, fully_connected=True)
    from_start, _ = graph.find_costs([cells[0]])
    path = graph.traceback(cells[1])
    optimum = float(from_start[cells[1]])
    model = LineString(
        [routing.cell_center(transform, row, col) for row, col in path]
    )
    report = compare_lines(model, reference)
    report["model_cost"] = round(optimum, 1)
    report["cost_surface"] = (
        cost_path.relative_to(routing.ROOT).as_posix()
        if cost_path.is_relative_to(routing.ROOT)
        else str(cost_path)
    )
    report["biased"] = biased
    through = from_start + corridors.accumulated_cost(mcp_cost, cells[1])
    for tolerance in tolerances:
        corridor, _ = corridors.corridor_polygon(
            through, optimum, tolerance, transform, 0
        )
        report[f"share_reference_inside_{tolerance:.0%}_corridor"] = round(
            reference.intersection(corridor).length / reference.length, 3
        )
    gpd.GeoDataFrame(
        [{"name": "Modelled least-cost route"}], geometry=[model], crs=crs
    ).to_crs("EPSG:4326").to_file(MODEL_ROUTE, driver="GeoJSON")
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    LOG.info("Baltic Pipe validation: %s", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tolerances", default="0.01,0.03")
    parser.add_argument(
        "--cost-surface", type=Path,
        help="Default: data/processed/validation/ if present, else the published surface (biased)",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print(json.dumps(run(
        tuple(float(v) for v in args.tolerances.split(",")), args.cost_surface
    ), indent=2))


if __name__ == "__main__":
    main()
