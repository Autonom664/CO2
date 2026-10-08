"""Build and verify Python reference surfaces for the adjustable browser model."""

from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import json
import logging
import math
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from pyproj import Transformer
from skimage.graph import MCP_Geometric

from src.cost_surface import ROOT, validate_cost_scores
from src.export_model import FLOAT_NODATA
from src.routing import HOTSPOTS_FILE, load_hotspots, make_route_pairs


LOG = logging.getLogger("model_parity")
DEFAULT_MODEL_DIR = ROOT / "web" / "data" / "model"
DEFAULT_OUTPUT_DIR = ROOT / "validation" / "model_parity"
RELATIVE_TOLERANCE = 0.005
SCENARIO_OVERRIDES = {
    "protection_low": {
        "description": "Halve Natura 2000 and protected-nature weights.",
        "multipliers": {"natura2000": 0.5, "protected_nature": 0.5},
    },
    "protection_high": {
        "description": "Increase Natura 2000 and protected-nature weights by 10%.",
        "multipliers": {"natura2000": 1.1, "protected_nature": 1.1},
    },
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_manifest_array(
    model_dir: Path,
    manifest_files: dict[str, dict[str, Any]],
    filename: str,
) -> np.ndarray:
    try:
        entry = manifest_files[filename]
    except KeyError as error:
        raise ValueError(f"Array is not indexed in manifest: {filename}") from error
    path = model_dir / filename
    if _sha256_file(path) != entry.get("compressed_sha256"):
        raise ValueError(f"Compressed SHA-256 does not match manifest: {filename}")
    with gzip.open(path, "rb") as stream:
        payload = stream.read()
    if len(payload) != int(entry["uncompressed_bytes"]):
        raise ValueError(f"Uncompressed byte count does not match manifest: {filename}")
    if _sha256(payload) != entry["sha256"]:
        raise ValueError(f"Uncompressed SHA-256 does not match manifest: {filename}")
    dtype = np.dtype(entry["dtype"]).newbyteorder("<")
    values = np.frombuffer(payload, dtype=dtype)
    expected_shape = tuple(int(size) for size in entry["shape"])
    if values.size != math.prod(expected_shape):
        raise ValueError(f"Array element count does not match manifest: {filename}")
    return values.reshape(expected_shape).copy()


def load_model_pack(model_dir: Path) -> dict[str, Any]:
    """Load and integrity-check every array used by the reference calculator."""
    model_dir = model_dir.resolve()
    manifest = json.loads((model_dir / "manifest.json").read_text(encoding="utf-8"))
    manifest_files = {
        str(entry["file"]): entry for entry in manifest.get("files", [])
    }
    grid = json.loads((model_dir / "grid.json").read_text(encoding="utf-8"))
    layers = json.loads((model_dir / "layers.json").read_text(encoding="utf-8"))
    config = json.loads((model_dir / "config.json").read_text(encoding="utf-8"))

    for filename in ("grid.json", "layers.json", "config.json"):
        entry = manifest_files.get(filename)
        if entry is None:
            raise ValueError(f"Model pack manifest does not index {filename}")
        payload = (model_dir / filename).read_bytes()
        if len(payload) != int(entry["bytes"]):
            raise ValueError(f"JSON byte count does not match manifest: {filename}")
        if _sha256(payload) != entry["sha256"]:
            raise ValueError(f"JSON SHA-256 does not match manifest: {filename}")

    presence = [
        _read_manifest_array(model_dir, manifest_files, name)
        for name in ("presence_lo.bin.gz", "presence_hi.bin.gz")
    ]
    continuous = layers["continuous"]
    layer_masks: dict[str, np.ndarray] = {}
    for layer in layers["layers"]:
        bit = int(layer["bit"])
        plane = presence[bit // 32]
        layer_masks[str(layer["name"])] = (
            (plane >> np.uint32(bit % 32)) & np.uint32(1)
        ).astype(bool)
    derived_masks: dict[str, np.ndarray] = {}
    for derived in layers["derived"]:
        bit = int(derived["bit"])
        plane = presence[bit // 32]
        derived_masks[str(derived["name"])] = (
            (plane >> np.uint32(bit % 32)) & np.uint32(1)
        ).astype(bool)

    arrays = {
        name: _read_manifest_array(model_dir, manifest_files, descriptor["file"])
        for name, descriptor in continuous.items()
    }
    shape = (int(grid["height"]), int(grid["width"]))
    if any(array.shape != shape for array in (*presence, *arrays.values())):
        raise ValueError("Model pack array shapes do not match grid.json")
    return {
        "manifest": manifest,
        "grid": grid,
        "layers": layers,
        "config": config,
        "layer_masks": layer_masks,
        "derived_masks": derived_masks,
        "arrays": arrays,
    }


def _quantile_scores(
    values: np.ndarray,
    minimum: float,
    maximum: float,
    quantiles: int,
) -> tuple[np.ndarray, np.ndarray]:
    if values.size == 0:
        raise ValueError("Cannot quantile-score an empty set of values")
    if quantiles < 2 or minimum < 0 or maximum < minimum:
        raise ValueError("Invalid quantile score settings")
    thresholds = np.quantile(values, np.linspace(0, 1, quantiles + 1))
    score_levels = np.linspace(minimum, maximum, quantiles + 1)
    unique_thresholds, inverse = np.unique(thresholds, return_inverse=True)
    if unique_thresholds.size == 1:
        scores = np.array([minimum], dtype=np.float64)
    else:
        score_sums = np.bincount(inverse, weights=score_levels)
        score_counts = np.bincount(inverse)
        scores = score_sums / score_counts
    return unique_thresholds, scores


def _score_quantiles(
    values: np.ndarray,
    eligible: np.ndarray,
    minimum: float,
    maximum: float,
    quantiles: int,
) -> np.ndarray:
    thresholds, scores = _quantile_scores(
        values[eligible], minimum, maximum, quantiles
    )
    result = np.zeros(values.shape, dtype=np.float32)
    result[eligible] = np.interp(values[eligible], thresholds, scores)
    return result


def build_cost_surface(model: dict[str, Any]) -> np.ndarray:
    """Apply the ordered browser model formula to model-pack arrays."""
    config = model["config"]
    grid = model["grid"]
    costs = config["costs"]
    resolution = int(grid["resolution_m"])
    scale = resolution / float(grid["cost_reference_resolution_m"])
    derived = model["derived_masks"]
    layer_masks = model["layer_masks"]
    arrays = model["arrays"]
    layers = {entry["name"]: entry for entry in model["layers"]["layers"]}
    derived_costs = (
        {str(config["landfall"]["cost"])}
        if config.get("landfall", {}).get("enabled", False)
        else set()
    )
    validate_cost_scores(
        costs,
        config["layers"],
        [str(name) for name in config.get("barriers", [])],
        float(config.get("score_minimum", 1)),
        derived_costs,
    )

    land = derived["land"]
    sea = derived["sea"]
    extent = land | sea
    building_threshold = int(grid["building_barrier_share_threshold"])
    building_mask = arrays["buildings_share"] >= building_threshold
    barrier_names = set(str(name) for name in config.get("barriers", []))
    barrier_masks: dict[str, np.ndarray] = {}
    class_masks: dict[str, np.ndarray] = {}
    for layer_name, descriptor in layers.items():
        if not descriptor["available"]:
            continue
        mask = layer_masks[layer_name] & extent
        cost_key = str(descriptor["cost"])
        if cost_key not in barrier_names and cost_key not in costs:
            raise ValueError(
                f"Layer {layer_name!r} uses undefined cost class {cost_key!r}"
            )
        destination = barrier_masks if cost_key in barrier_names else class_masks
        if cost_key in destination:
            destination[cost_key] |= mask
        else:
            destination[cost_key] = mask.copy()

    landfall_settings = config.get("landfall", {})
    landfall_name = str(landfall_settings.get("cost", "landfall"))

    valid = extent.copy()
    if "building_barrier" in barrier_names:
        valid &= ~building_mask
    for mask in barrier_masks.values():
        valid &= ~mask
    surface = np.full(land.shape, np.nan, dtype=np.float32)
    surface[land & valid] = float(costs["open_land"]) * scale
    surface[sea & valid] = float(costs["open_sea"]) * scale
    traversable_land = land & valid

    combine_groups = config.get("combine_groups", {})
    dynamic_classes = {
        "dwelling_proximity",
        "population",
        "population_risk",
    }
    grouped: set[str] = set()
    deferred_groups: dict[str, list[str]] = {}
    for group_name, group in combine_groups.items():
        members = [str(name) for name in group["members"]]
        if group.get("rule") != "max" or len(members) < 2:
            raise ValueError(f"Invalid max group {group_name!r}")
        if grouped.intersection(members):
            raise ValueError("A class may belong to only one combine group")
        grouped.update(members)
        if dynamic_classes.intersection(members):
            deferred_groups[str(group_name)] = members
            continue
        combined = np.zeros(land.shape, dtype=bool)
        contribution = np.zeros(land.shape, dtype=np.float32)
        for member in members:
            mask = class_masks.get(member)
            if mask is None:
                continue
            combined |= mask
            score = float(costs[member]) * scale
            contribution[mask] = np.maximum(contribution[mask], score)
        surface[combined & valid] += contribution[combined & valid]

    discounts = set(str(name) for name in config.get("discount_classes", []))
    for cost_key, mask in class_masks.items():
        if cost_key in grouped:
            continue
        score = float(costs[cost_key]) * scale
        applicable = mask & valid
        if cost_key in discounts:
            floor = float(costs["open_land"]) * scale
            surface[applicable] = np.maximum(
                floor, surface[applicable] - score
            )
        else:
            surface[applicable] += score

    if landfall_settings.get("enabled", False):
        landfall_mask = derived["landfall"] & traversable_land
        surface[landfall_mask] += float(costs[landfall_name]) * scale

    dynamic_values: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    proximity = costs.get("dwelling_proximity", {})
    if proximity.get("enabled", True):
        if str(proximity.get("distance_metric", "euclidean")) != "euclidean":
            raise ValueError("Dwelling proximity supports Euclidean distance only")
        max_distance = float(proximity["max_distance_m"])
        if max_distance <= 0:
            raise ValueError("Dwelling-proximity maximum distance must be positive")
        distance = arrays["building_distance"].astype(np.float32)
        proximity_mask = (
            traversable_land
            & (distance > 0)
            & (distance < max_distance)
            & (distance != int(grid["distance_nodata"]))
        )
        proximity_scores = np.zeros(land.shape, dtype=np.float32)
        proximity_scores[proximity_mask] = (
            float(proximity["max_score"])
            * (1 - distance[proximity_mask] / max_distance)
            * scale
        )
        if "dwelling_proximity" in grouped:
            dynamic_values["dwelling_proximity"] = (
                proximity_mask,
                proximity_scores,
            )
        else:
            surface[proximity_mask] += proximity_scores[proximity_mask]

    parallel = config.get("parallel_corridor", {})
    if parallel.get("enabled", False):
        if str(parallel.get("distance_metric", "euclidean")) != "euclidean":
            raise ValueError("Parallel corridor supports Euclidean distance only")
        corridor = derived["parallel_band"] & valid
        factor = float(parallel["factor"])
        if not 0 < factor <= 1:
            raise ValueError("Parallel corridor factor must be in (0, 1]")
        floor = float(costs["open_land"]) * scale
        surface[corridor] = np.maximum(floor, surface[corridor] * factor)

    population_config = costs.get("population", {})
    if population_config.get("enabled", True):
        population = arrays["population"].astype(np.float32)
        reference_resolution = float(
            population_config["reference_cell_resolution_m"]
        )
        if not math.isfinite(reference_resolution) or reference_resolution <= 0:
            raise ValueError("Population reference-cell resolution must be positive")
        threshold = float(population_config.get("min_per_cell", 0)) * (
            resolution / reference_resolution
        ) ** 2
        eligible = (
            traversable_land
            & np.isfinite(population)
            & (population > 0)
            & (population >= threshold)
        )
        if np.any(eligible):
            score = _score_quantiles(
                population,
                eligible,
                float(population_config["minimum"]),
                float(population_config["maximum"]),
                int(population_config["quantiles"]),
            )
            population_mask = eligible & (score > 0)
            score *= scale
            if "population" in grouped:
                dynamic_values["population"] = (eligible, score)
            else:
                surface[population_mask] += score[population_mask]

    risk = costs.get("population_risk", {})
    if risk.get("enabled", False):
        if str(risk.get("kernel", "circular")) != "circular":
            raise ValueError("Population risk supports a circular kernel only")
        focal = arrays["population_1km"].astype(np.float32)
        eligible = (
            traversable_land
            & np.isfinite(focal)
            & (focal > float(risk["threshold_people"]))
        )
        if np.any(eligible):
            score = _score_quantiles(
                focal,
                eligible,
                0.0,
                float(risk["maximum"]),
                int(risk["quantiles"]),
            )
            score *= scale
            if "population_risk" in grouped:
                dynamic_values["population_risk"] = (eligible, score)
            else:
                surface[eligible] += score[eligible]

    for group_name, members in deferred_groups.items():
        combined = np.zeros(land.shape, dtype=bool)
        contribution = np.zeros(land.shape, dtype=np.float32)
        for member in members:
            if member in dynamic_values:
                member_mask, member_scores = dynamic_values[member]
            elif member in class_masks:
                member_mask = class_masks[member]
                member_scores = np.full(
                    land.shape,
                    float(costs[member]) * scale,
                    dtype=np.float32,
                )
            else:
                member_mask = np.zeros(land.shape, dtype=bool)
                member_scores = np.zeros(land.shape, dtype=np.float32)
            combined |= member_mask
            contribution[member_mask] = np.maximum(
                contribution[member_mask], member_scores[member_mask]
            )
        applicable = combined & valid
        surface[applicable] += contribution[applicable]

    if not np.any(np.isfinite(surface)):
        raise ValueError("Cost surface has no traversable cells")
    if np.any(np.isfinite(surface) & (surface <= 0)):
        raise ValueError("Traversable cell costs must be positive")
    return surface


def route_references(
    surface: np.ndarray,
    model: dict[str, Any],
    hotspots_path: Path = HOTSPOTS_FILE,
) -> list[dict[str, Any]]:
    """Return directed source-to-storage route costs from one run per source."""
    grid = model["grid"]
    transform = rasterio.Affine.from_gdal(*grid["transform_gdal"])
    crs = str(grid["crs"])
    resolution = int(grid["resolution_m"])
    routing_settings = model["config"].get("routing", {})
    fully_connected = bool(routing_settings.get("fully_connected", True))
    if (
        str(routing_settings.get("path_method", "MCP_Geometric"))
        != "MCP_Geometric"
        or not fully_connected
        or str(routing_settings.get("snap_distance_metric", "euclidean"))
        != "euclidean"
    ):
        raise ValueError(
            "References require fully-connected MCP_Geometric routing and "
            "Euclidean hotspot snapping"
        )
    valid = np.isfinite(surface) & (surface > 0)
    hotspots = load_hotspots(
        hotspots_path,
        Transformer.from_crs("EPSG:4326", crs, always_xy=True),
        int(grid["width"]),
        int(grid["height"]),
        transform,
        valid,
        resolution,
        float(model["config"].get("routing", {}).get("max_snap_distance_m", 2000)),
        expected_count=None,
        bounds=(
            float(grid["bounds"][0]),
            float(grid["bounds"][1]),
            float(grid["bounds"][2]),
            float(grid["bounds"][3]),
        ),
    )
    pairs = make_route_pairs(hotspots)
    destinations_by_source: dict[str, list[dict[str, Any]]] = {}
    for source, storage in pairs:
        destinations_by_source.setdefault(source["id"], []).append(storage)

    mcp_cost = np.where(valid, surface, np.inf).astype(np.float64)
    hotspot_by_id = {point["id"]: point for point in hotspots}
    output: list[dict[str, Any]] = []
    for source_id, destinations in destinations_by_source.items():
        source = hotspot_by_id[source_id]
        graph = MCP_Geometric(mcp_cost, fully_connected=fully_connected)
        cumulative, _ = graph.find_costs(
            [(source["row"], source["col"])],
            ends=[(point["row"], point["col"]) for point in destinations],
            find_all_ends=True,
        )
        for destination in destinations:
            endpoint = (destination["row"], destination["col"])
            total_cost = float(cumulative[endpoint])
            if not math.isfinite(total_cost):
                raise RuntimeError(
                    f"No route from {source_id} to {destination['id']} in reference grid"
                )
            path = graph.traceback(endpoint)
            length_m = resolution * sum(
                math.hypot(row_b - row_a, col_b - col_a)
                for (row_a, col_a), (row_b, col_b) in zip(path, path[1:])
            )
            output.append(
                {
                    "from": source_id,
                    "to": destination["id"],
                    "length_km": length_m / 1000,
                    "accumulated_cost": total_cost,
                    "start_cell": [int(source["row"]), int(source["col"])],
                    "end_cell": [int(destination["row"]), int(destination["col"])],
                }
            )
    return output


def compare_cost_arrays(
    expected: np.ndarray,
    actual: np.ndarray,
    relative_tolerance: float = RELATIVE_TOLERANCE,
) -> dict[str, Any]:
    if expected.shape != actual.shape:
        return {
            "passed": False,
            "reason": "shape mismatch",
            "expected_shape": list(expected.shape),
            "actual_shape": list(actual.shape),
        }
    expected_valid = np.isfinite(expected)
    actual_valid = np.isfinite(actual)
    validity_mismatch = int(np.count_nonzero(expected_valid != actual_valid))
    compared = expected_valid & actual_valid
    if not np.any(compared):
        raise ValueError("Cost arrays have no mutually valid cells")
    relative_error = np.abs(
        expected[compared].astype(np.float64) - actual[compared].astype(np.float64)
    ) / np.maximum(np.abs(expected[compared].astype(np.float64)), 1e-12)
    maximum_error = float(relative_error.max())
    mean_error = float(relative_error.mean())
    return {
        "passed": validity_mismatch == 0 and maximum_error <= relative_tolerance,
        "validity_mismatch_cells": validity_mismatch,
        "compared_cells": int(np.count_nonzero(compared)),
        "maximum_relative_error": maximum_error,
        "mean_relative_error": mean_error,
        "relative_tolerance": relative_tolerance,
    }


def compare_route_references(
    expected: list[dict[str, Any]],
    actual: list[dict[str, Any]],
    relative_tolerance: float = RELATIVE_TOLERANCE,
) -> dict[str, Any]:
    expected_by_pair = {
        (str(route["from"]), str(route["to"])): route for route in expected
    }
    actual_by_pair = {
        (str(route["from"]), str(route["to"])): route for route in actual
    }
    missing = sorted(set(expected_by_pair) - set(actual_by_pair))
    unexpected = sorted(set(actual_by_pair) - set(expected_by_pair))
    if missing or unexpected:
        return {
            "passed": False,
            "missing_routes": [list(pair) for pair in missing],
            "unexpected_routes": [list(pair) for pair in unexpected],
        }
    errors: list[float] = []
    for pair, expected_route in expected_by_pair.items():
        expected_cost = float(expected_route["accumulated_cost"])
        actual_cost = float(actual_by_pair[pair]["accumulated_cost"])
        if (
            not math.isfinite(expected_cost)
            or not math.isfinite(actual_cost)
            or expected_cost <= 0
            or actual_cost <= 0
        ):
            return {
                "passed": False,
                "invalid_cost_route": list(pair),
            }
        errors.append(
            abs(expected_cost - actual_cost) / max(abs(expected_cost), 1e-12)
        )
    maximum_error = max(errors, default=0.0)
    return {
        "passed": maximum_error <= relative_tolerance,
        "route_count": len(expected_by_pair),
        "maximum_relative_error": maximum_error,
        "mean_relative_error": float(np.mean(errors)) if errors else 0.0,
        "relative_tolerance": relative_tolerance,
    }


def _write_cost_grid(path: Path, surface: np.ndarray) -> dict[str, Any]:
    values = np.where(np.isfinite(surface), surface, FLOAT_NODATA).astype("<f4")
    digest = hashlib.sha256()
    with path.open("wb") as output:
        with gzip.GzipFile(
            filename="", mode="wb", fileobj=output, compresslevel=6, mtime=0
        ) as compressed:
            for row in values:
                chunk = row.tobytes(order="C")
                digest.update(chunk)
                compressed.write(chunk)
    return {
        "file": path.name,
        "dtype": "float32",
        "shape": list(values.shape),
        "byte_order": "little",
        "order": "C-row-major",
        "compression": "gzip",
        "nodata": FLOAT_NODATA,
        "bytes": path.stat().st_size,
        "sha256": digest.hexdigest(),
        "compressed_sha256": _sha256_file(path),
    }


def build_references(
    model_dir: Path = DEFAULT_MODEL_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    hotspots_path: Path = HOTSPOTS_FILE,
) -> dict[str, Any]:
    model_dir = model_dir.resolve()
    output_dir = output_dir.resolve()
    model = load_model_pack(model_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    scenario_docs: list[dict[str, Any]] = []
    cost_files: list[dict[str, Any]] = []
    scenarios = [("default", None), *SCENARIO_OVERRIDES.items()]
    for scenario_name, scenario_settings in scenarios:
        scenario_config = copy.deepcopy(model["config"])
        overrides: dict[str, float] = {}
        if scenario_settings:
            overrides = {
                key: float(value)
                for key, value in scenario_settings["multipliers"].items()
            }
            for cost_key, multiplier in overrides.items():
                scenario_config["costs"][cost_key] *= multiplier
        scenario_model = {**model, "config": scenario_config}
        surface = build_cost_surface(scenario_model)
        routes = route_references(surface, scenario_model, hotspots_path)
        cost_file = _write_cost_grid(
            output_dir / f"{scenario_name}_costs.bin.gz", surface
        )
        cost_files.append(cost_file)
        scenario_docs.append(
            {
                "id": scenario_name,
                "description": (
                    "Configured default model."
                    if scenario_settings is None
                    else scenario_settings["description"]
                ),
                "weight_multipliers": overrides,
                "cost_grid": cost_file["file"],
                "cost_grid_sha256": cost_file["sha256"],
                "traversable_cells": int(np.count_nonzero(np.isfinite(surface))),
                "routes": routes,
            }
        )
        LOG.info(
            "Scenario %s: %s traversable cells and %s routes",
            scenario_name,
            scenario_docs[-1]["traversable_cells"],
            len(routes),
        )

    document = {
        "format_version": 1,
        "grid": model["grid"],
        "config_sha256": model["manifest"]["effective_config_sha256"],
        "model_pack_sha256": _sha256(
            (model_dir / "manifest.json").read_bytes()
        ),
        "acceptance": {
            "cost_cell_relative_tolerance": RELATIVE_TOLERANCE,
            "route_accumulated_cost_relative_tolerance": RELATIVE_TOLERANCE,
            "invalid_or_extra_traversable_cells_allowed": 0,
        },
        "scenario_cost_files": cost_files,
        "scenarios": scenario_docs,
    }
    output_path = output_dir / "model_parity.json"
    payload = (
        json.dumps(document, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    ).encode("utf-8")
    output_path.write_bytes(payload)
    result = {
        "json": str(output_path),
        "scenarios": len(scenario_docs),
        "routes_per_scenario": len(scenario_docs[0]["routes"]),
        "cost_grid_files": len(cost_files),
        "output_bytes": len(payload),
        "acceptance_relative_tolerance": RELATIVE_TOLERANCE,
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the default and perturbed 250 m browser-parity references."
    )
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--hotspots", type=Path, default=HOTSPOTS_FILE)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(message)s",
    )
    print(
        json.dumps(
            build_references(args.model_dir, args.output_dir, args.hotspots),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
