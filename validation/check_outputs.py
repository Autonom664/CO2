"""Sanity checks for the routing outputs, run after cost_surface → routing.

    python -m validation.check_outputs

Prints PASS/FAIL per check and exits with status 1 if any check fails.
"""

from __future__ import annotations

import csv
import json
import math
import sys
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import rasterize
from shapely.geometry import Point

from src import routing


def check_route_set(
    hotspots: list[dict[str, Any]], routes: list[dict[str, Any]]
) -> list[str]:
    """Delivery routes must be exactly every source → storage pair, once."""
    problems = []
    roles = {h["id"]: h["role"] for h in hotspots}
    sources = [h["id"] for h in hotspots if h["role"] == "source"]
    storage = [h["id"] for h in hotspots if h["role"] == "storage"]
    expected = {(s, t) for s in sources for t in storage}
    seen = [(r["from_id"], r["to_id"]) for r in routes]
    if len(seen) != len(set(seen)):
        problems.append(f"{len(seen) - len(set(seen))} duplicate routes")
    missing = expected - set(seen)
    extra = set(seen) - expected
    if missing:
        problems.append(f"{len(missing)} source→storage pairs missing, e.g. {sorted(missing)[:3]}")
    if extra:
        problems.append(f"{len(extra)} unexpected routes, e.g. {sorted(extra)[:3]}")
    for route in routes:
        name = f"{route['from_id']}→{route['to_id']}"
        if roles.get(route["from_id"]) != "source" or roles.get(route["to_id"]) != "storage":
            problems.append(f"{name}: wrong direction or unknown hotspot")
        cost = route.get("accumulated_cost")
        if cost is None or not math.isfinite(float(cost)) or float(cost) <= 0:
            problems.append(f"{name}: accumulated_cost {cost!r} is not positive")
        length = float(route.get("length_km") or 0)
        for key, value in route.items():
            if key.startswith("km_") and value is not None:
                if float(value) < 0 or float(value) > length + 0.5:
                    problems.append(f"{name}: {key}={value} outside 0..length_km ({length})")
    return problems


def check_tree(hotspot_ids: list[str], edges: list[tuple[str, str]]) -> list[str]:
    """The network must have n − 1 edges and connect every hotspot."""
    problems = []
    if len(edges) != len(hotspot_ids) - 1:
        problems.append(f"{len(edges)} edges, expected {len(hotspot_ids) - 1}")
    parent = {h: h for h in hotspot_ids}

    def find(node: str) -> str:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for a, b in edges:
        if a not in parent or b not in parent:
            problems.append(f"edge {a}–{b} uses an unknown hotspot")
            continue
        root_a, root_b = find(a), find(b)
        if root_a == root_b:
            problems.append(f"edge {a}–{b} closes a cycle")
        parent[root_a] = root_b
    components = {find(h) for h in hotspot_ids}
    if len(components) > 1:
        problems.append(f"network has {len(components)} disconnected parts")
    return problems


def check_lengths(
    hotspots: dict[str, Point], routes: list[dict[str, Any]], tolerance_km: float
) -> list[str]:
    """A route cannot be shorter than the straight line between its ends."""
    problems = []
    for route in routes:
        a, b = hotspots[route["from_id"]], hotspots[route["to_id"]]
        straight = a.distance(b) / 1000
        if float(route["length_km"]) + tolerance_km < straight:
            problems.append(
                f"{route['from_id']}→{route['to_id']}: {route['length_km']} km is shorter "
                f"than the straight line {straight:.1f} km"
            )
    return problems


def detour_factors(
    hotspots: dict[str, Point], routes: list[dict[str, Any]]
) -> dict[str, float]:
    """Route length ÷ straight-line distance, per route.

    Built oil and gas lines typically fall between 1.05 and 1.35
    (docs/routing_practice.md).
    """
    factors = {}
    for route in routes:
        straight = hotspots[route["from_id"]].distance(hotspots[route["to_id"]]) / 1000
        if straight > 0:
            factors[f"{route['from_id']}→{route['to_id']}"] = float(route["length_km"]) / straight
    return factors


def report(name: str, problems: list[str]) -> bool:
    print(f"{'PASS' if not problems else 'FAIL'}  {name}")
    for problem in problems[:10]:
        print(f"      - {problem}")
    if len(problems) > 10:
        print(f"      … and {len(problems) - 10} more")
    return not problems


def main() -> int:
    processed = routing.PROCESSED
    config = routing.load_config(routing.CONFIG_FILE)
    resolution = int(config["grid"]["resolution_m"])
    cost_path = processed / f"cost_surface_{resolution}m.tif"
    with rasterio.open(cost_path) as source:
        crs, transform, nodata = source.crs, source.transform, source.nodata
        cost = source.read(1)
    rows = list(csv.DictReader(routing.HOTSPOTS_FILE.open(encoding="utf-8")))
    hotspot_frame = gpd.read_file(processed / "hotspots.geojson").to_crs(crs)
    routes = gpd.read_file(processed / "routes.geojson").to_crs(crs)
    network = gpd.read_file(processed / "minimum_spanning_network.geojson")
    hotspot_props = hotspot_frame.drop(columns="geometry").to_dict("records")
    route_props = routes.drop(columns="geometry").to_dict("records")
    ok = True

    ok &= report(
        f"hotspots: {len(hotspot_frame)} published, {len(rows)} in hotspots.csv",
        [] if len(hotspot_frame) == len(rows) else ["count differs from hotspots.csv"],
    )
    ok &= report(f"delivery routes: {len(routes)}", check_route_set(hotspot_props, route_props))
    ok &= report(
        f"spanning network: {len(network)} edges",
        check_tree(
            [h["id"] for h in hotspot_props],
            list(zip(network["from_id"], network["to_id"])),
        ),
    )
    points = dict(zip(hotspot_frame["id"], hotspot_frame.geometry))
    snap_km = float(config.get("routing", {}).get("max_snap_distance_m", 2000)) / 1000
    ok &= report(
        "route lengths ≥ straight-line distance",
        check_lengths(points, route_props, tolerance_km=2 * snap_km),
    )

    factors = detour_factors(points, route_props)
    values = np.array(list(factors.values()))
    high = sorted((f for f in factors.items() if f[1] > 1.6), key=lambda f: -f[1])
    print(
        f"INFO  detour factor (route ÷ straight line): min {values.min():.2f}, "
        f"median {np.median(values):.2f}, max {values.max():.2f}; built pipelines "
        f"typically 1.05–1.35"
    )
    for name, value in high[:5]:
        print(f"      - {name}: {value:.2f} (above 1.6, check)")

    valid = np.isfinite(cost) & (cost != nodata) & (cost > 0)
    blocked = []
    for frame in (routes, network.to_crs(crs)):
        for _, route in frame.iterrows():
            xs, ys = np.asarray(route.geometry.coords).T
            r, c = rasterio.transform.rowcol(transform, xs, ys)
            bad = int(np.count_nonzero(~valid[np.asarray(r), np.asarray(c)]))
            if bad:
                blocked.append(f"{route['from_id']}→{route['to_id']}: {bad} vertices on impassable cells")
    ok &= report("routes avoid barriers and NoData", blocked)

    extent_file = processed / "coast_land_water.gpkg"
    try:
        foreign = gpd.read_file(extent_file, layer="foreign_land").to_crs(crs)
    except Exception as error:  # layer absent in older preparations
        ok &= report("foreign land excluded", [f"cannot read foreign_land layer: {error}"])
    else:
        mask = rasterize(
            ((g, 1) for g in foreign.geometry if g is not None and not g.is_empty),
            out_shape=cost.shape, transform=transform, fill=0, dtype="uint8",
        ).astype(bool)
        costed = int(np.count_nonzero(mask & valid))
        ok &= report(
            f"foreign land excluded ({int(mask.sum())} foreign cells)",
            [] if costed == 0 else [f"{costed} foreign-land cells still have a cost"],
        )

    stamps = {
        "hotspots.csv": routing.HOTSPOTS_FILE.stat().st_mtime,
        "costs.yaml": routing.CONFIG_FILE.stat().st_mtime,
        cost_path.name: cost_path.stat().st_mtime,
        "routes.geojson": (processed / "routes.geojson").stat().st_mtime,
    }
    stale = [
        f"routes.geojson is older than {name}"
        for name, stamp in stamps.items()
        if name != "routes.geojson" and stamp > stamps["routes.geojson"]
    ]
    ok &= report("outputs are newer than their inputs", stale)
    print("\nAll checks passed." if ok else "\nSome checks failed.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
