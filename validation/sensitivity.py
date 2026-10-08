"""Weight sensitivity: do the routes depend on the exact cost scores?

For each group of related scores, builds a cost surface with the group
multiplied by each factor (default ×0.5 and ×1.5), routes every source to
every storage site, and compares with the unmodified baseline:

- does each source's cheapest storage site change?
- how much of each baseline best route stays within 1 km of the new route?

Scenario surfaces are written under build/sensitivity/ (git-ignored) and
deleted after evaluation unless --keep is given. The published surface in
data/processed/ is never touched. Expect roughly 7 minutes per scenario:

    python -m validation.sensitivity                    # all groups, ×0.5 and ×1.5
    python -m validation.sensitivity --groups roads_rail,forest --factors 0.5,2

The 1–10 score validation in src.cost_surface is relaxed to 0.5–15 inside
this tool only, because "what if this class mattered more than 10" is the
question being asked.
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import shutil
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import numpy as np
import rasterio
import shapely
import yaml
from pyproj import Transformer
from shapely.geometry import LineString
from skimage.graph import MCP_Geometric

from src import cost_surface, routing

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "build" / "sensitivity"
LOG = logging.getLogger("sensitivity")

# Score keys in config/costs.yaml grouped by what a planner would vary together.
# Keys missing from the config are ignored, so the groups survive config edits.
GROUPS: dict[str, list[str]] = {
    "sea": ["open_sea"],
    "roads_rail": ["road_major", "road_minor", "railway_crossing"],
    "water": ["watercourse_crossing", "lake", "wetland", "water_protection"],
    "protected_nature": ["natura2000", "protected_nature"],
    "forest": ["forest", "fredskov"],
    "urban_population": ["urban_area", "population.maximum", "dwelling_proximity.max_score"],
    "groundwater": ["drinking_water_osd", "drinking_water_od", "groundwater_catchment"],
    "heritage_soil_coast": [
        "ancient_monument_protection", "contaminated_v1", "contaminated_v2", "beach_protection",
    ],
    "marine": [
        "marine_shipping", "marine_renewables", "marine_materials",
        "offshore_wind_planned", "munitions_points", "subsea_pipelines", "subsea_cables",
    ],
}
SCORE_RANGE = (0.5, 15.0)


def perturb(config: dict[str, Any], keys: list[str], factor: float) -> tuple[dict[str, Any], list[str]]:
    """Return a copy of config with the given score keys multiplied by factor.

    Keys may be dotted (population.maximum). Results are clipped to
    SCORE_RANGE. Returns the new config and the keys actually changed.
    """
    new = copy.deepcopy(config)
    changed = []
    for key in keys:
        node, *rest = key.split(".")
        target = new["costs"]
        if node not in target:
            continue
        if rest:
            if not isinstance(target[node], dict) or rest[0] not in target[node]:
                continue
            target, node = target[node], rest[0]
        value = float(target[node])
        target[node] = float(np.clip(value * factor, *SCORE_RANGE))
        changed.append(key)
    # Population minimum must not exceed its maximum after scaling down.
    population = new["costs"].get("population")
    if isinstance(population, dict) and population.get("minimum", 0) > population.get("maximum", 99):
        population["minimum"] = population["maximum"]
    return new, changed


@contextmanager
def relaxed_score_validation() -> Iterator[None]:
    original = cost_surface.validate_cost_scores

    def validate(costs: dict[str, Any], layers: dict[str, Any], barriers: list[str]) -> None:
        low, high = SCORE_RANGE
        scaled = copy.deepcopy(costs)
        for name, value in scaled.items():
            if isinstance(value, (int, float)):
                if not low <= float(value) <= high:
                    raise ValueError(f"Sensitivity score for {name!r} outside {SCORE_RANGE}")
                scaled[name] = min(max(float(value), 1.0), 10.0)
        population = scaled.get("population")
        if isinstance(population, dict):
            population = dict(population)
            population["minimum"] = min(max(float(population["minimum"]), 1.0), 10.0)
            population["maximum"] = min(max(float(population["maximum"]), population["minimum"]), 10.0)
            scaled["population"] = population
        original(scaled, layers, barriers)

    cost_surface.validate_cost_scores = validate
    try:
        yield
    finally:
        cost_surface.validate_cost_scores = original


def share_within(reference: LineString, candidate: LineString, distance_m: float) -> float:
    """Share of the reference line (sampled every 100 m) within distance of candidate."""
    count = max(2, int(reference.length // 100) + 1)
    points = shapely.line_interpolate_point(reference, np.linspace(0, 1, count), normalized=True)
    return float(np.mean(shapely.distance(points, candidate) <= distance_m))


def best_routes(cost_path: Path, config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Cheapest storage site and its route for every source on one surface."""
    resolution = int(config["grid"]["resolution_m"])
    max_snap_m = float(config.get("routing", {}).get("max_snap_distance_m", 2000))
    with rasterio.open(cost_path) as source:
        cost = source.read(1)
        transform, crs, nodata = source.transform, source.crs, source.nodata
    valid = np.isfinite(cost) & (cost != nodata) & (cost > 0)
    hotspots = routing.load_hotspots(
        routing.HOTSPOTS_FILE,
        Transformer.from_crs("EPSG:4326", crs, always_xy=True),
        cost.shape[1], cost.shape[0], transform, valid, resolution, max_snap_m,
    )
    mcp_cost = routing.make_mcp_cost_array(cost, valid)
    del cost
    storage = [h for h in hotspots if h["role"] == "storage"]
    results = {}
    for start in (h for h in hotspots if h["role"] == "source"):
        graph = MCP_Geometric(mcp_cost, fully_connected=True)
        costs, _ = graph.find_costs([(start["row"], start["col"])])
        options = {s["id"]: float(costs[s["row"], s["col"]]) for s in storage}
        best_id = min(options, key=options.get)
        best = next(s for s in storage if s["id"] == best_id)
        path = graph.traceback((best["row"], best["col"]))
        line = LineString([routing.cell_center(transform, r, c) for r, c in path])
        results[start["id"]] = {
            "best": best_id, "cost": options[best_id], "line": line,
            "ranking": sorted(options, key=options.get),
        }
    return results


def compare(baseline: dict[str, dict[str, Any]], scenario: dict[str, dict[str, Any]]) -> dict[str, Any]:
    rows = {}
    for source, base in baseline.items():
        new = scenario[source]
        rows[source] = {
            "baseline_best": base["best"],
            "scenario_best": new["best"],
            "best_changed": base["best"] != new["best"],
            "route_within_1km": round(share_within(base["line"], new["line"], 1000), 3),
            "length_change": round(new["line"].length / base["line"].length - 1, 3),
        }
    return {
        "best_changed": sum(r["best_changed"] for r in rows.values()),
        "mean_route_within_1km": round(float(np.mean([r["route_within_1km"] for r in rows.values()])), 3),
        "sources": rows,
    }


def run_scenario(name: str, config: dict[str, Any], keep: bool) -> dict[str, dict[str, Any]]:
    folder = WORK / name
    folder.mkdir(parents=True, exist_ok=True)
    config_path = folder / "costs.yaml"
    config_path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    resolution = int(config["grid"]["resolution_m"])
    output = folder / f"cost_surface_{resolution}m.tif"
    started = time.time()
    with relaxed_score_validation():
        cost_surface.build_cost_surface(config_path=config_path, output_path=output)
    results = best_routes(output, config)
    LOG.info("Scenario %s took %.1f min", name, (time.time() - started) / 60)
    if not keep:
        shutil.rmtree(folder, ignore_errors=True)
    return results


def write_report(report: dict[str, Any], path: Path) -> None:
    lines = [
        "# Weight sensitivity",
        "",
        "Each row multiplies one group of scores by a factor and compares each",
        "source's cheapest storage site and route with the baseline.",
        "",
        "| Scenario | Changed keys | Sources whose best storage changed | Mean share of route within 1 km |",
        "|---|---|---:|---:|",
    ]
    for name, result in report["scenarios"].items():
        lines.append(
            f"| {name} | {', '.join(result['changed_keys'])} | "
            f"{result['best_changed']} / {len(result['sources'])} | {result['mean_route_within_1km']:.0%} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--groups", default=",".join(GROUPS))
    parser.add_argument("--factors", default="0.5,1.5")
    parser.add_argument("--parallel-factors", default="1.0,0.6",
                        help="Extra scenarios for parallel_corridor.factor (empty to skip)")
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    config = routing.load_config(routing.CONFIG_FILE)
    WORK.mkdir(parents=True, exist_ok=True)
    baseline = run_scenario("baseline", config, args.keep)
    report: dict[str, Any] = {
        "baseline": {s: {"best": r["best"], "ranking": r["ranking"]} for s, r in baseline.items()},
        "scenarios": {},
    }
    plans = []
    for group in filter(None, args.groups.split(",")):
        for factor in (float(f) for f in args.factors.split(",")):
            scenario, changed = perturb(config, GROUPS[group], factor)
            if changed:
                plans.append((f"{group} ×{factor:g}", scenario, changed))
    for factor in (float(f) for f in args.parallel_factors.split(",") if f):
        scenario = copy.deepcopy(config)
        if "parallel_corridor" in scenario:
            scenario["parallel_corridor"]["factor"] = factor
            plans.append((f"parallel discount ×{factor:g}", scenario, ["parallel_corridor.factor"]))
    for index, (name, scenario, changed) in enumerate(plans, 1):
        LOG.info("Scenario %d/%d: %s", index, len(plans), name)
        result = compare(baseline, run_scenario(f"s{index:02d}", scenario, args.keep))
        result["changed_keys"] = changed
        report["scenarios"][name] = result
        (WORK / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        write_report(report, WORK / "report.md")
    print((WORK / "report.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
