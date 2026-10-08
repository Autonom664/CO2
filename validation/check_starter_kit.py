"""Check the ArcGIS starter kit against the ModelBuilder guide and the model.

    python -m validation.check_starter_kit [path/to/co2_arcgis_starter_kit.zip]

The guide (docs/wiki/modelbuilder.md) names every raster, geodatabase
layer and table it uses. This checks that the kit contains exactly those,
that every raster shares the 100 m analysis grid of the published cost
surface, that masks are 0/1, and that every configured layer has a
raster. Prints PASS/FAIL per check and exits 1 if anything fails.
"""

from __future__ import annotations

import csv
import io
import re
import sys
import tempfile
import zipfile
from pathlib import Path

import numpy as np
import pyogrio
import rasterio

from src import cost_surface

ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "docs" / "wiki" / "modelbuilder.md"
DEFAULT_KIT = ROOT / "web" / "downloads" / "co2_arcgis_starter_kit.zip"
REFERENCE = ROOT / "data" / "processed" / "cost_surface_100m.tif"
MAX_BYTES = 150_000_000
CONTINUOUS = {"population.tif", "published_cost_100m.tif"}
GDB_LAYERS = [
    "sites", "analysis_area", "published_routes", "published_network",
    "published_corridors", "storage_areas", "baltic_pipe_osm",
]
WEIGHT_COLUMNS = {"layer", "raster", "cost_key", "weight", "treatment", "group", "surface"}


def guide_rasters(text: str) -> set[str]:
    return set(re.findall(r'"?([a-z][a-z0-9_]*\.tif)"?', text))


def report(name: str, problems: list[str]) -> bool:
    print(f"{'PASS' if not problems else 'FAIL'}  {name}")
    for problem in problems[:12]:
        print(f"      - {problem}")
    if len(problems) > 12:
        print(f"      … and {len(problems) - 12} more")
    return not problems


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    kit = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_KIT
    if not kit.exists():
        print(f"FAIL  starter kit not found: {kit}")
        return 1
    ok = True
    size = kit.stat().st_size
    ok &= report(f"zip size {size / 1e6:.1f} MB (limit {MAX_BYTES / 1e6:.0f} MB)",
                 [] if size <= MAX_BYTES else ["too large for a web download"])

    config = cost_surface.load_config(cost_surface.CONFIG)
    wanted = guide_rasters(GUIDE.read_text(encoding="utf-8"))
    layer_rasters = {f"l_{name}.tif" for name in config["layers"]}

    with tempfile.TemporaryDirectory() as folder, zipfile.ZipFile(kit) as archive:
        names = archive.namelist()
        archive.extractall(folder)
        base = Path(folder)
        # Allow the kit to sit in a top-level folder inside the zip.
        roots = {Path(n).parts[0] for n in names if len(Path(n).parts) > 1}
        if len(roots) == 1 and not (base / "rasters").exists():
            base = base / roots.pop()
        rasters = {p.name: p for p in (base / "rasters").glob("*.tif")}

        ok &= report("README present", [] if any(Path(n).name.lower().startswith("readme") for n in names)
                     else ["no README in the kit"])
        missing = sorted(wanted - rasters.keys())
        ok &= report(f"every raster named in the guide is in the kit ({len(wanted)})", missing)
        unconfigured = sorted(layer_rasters - rasters.keys())
        ok &= report(f"every configured layer has a raster ({len(layer_rasters)})", unconfigured)
        not_in_guide = sorted(layer_rasters - wanted)
        ok &= report("every configured layer is used in the guide", not_in_guide)

        with rasterio.open(REFERENCE) as ref:
            grid = (ref.crs, ref.transform, ref.width, ref.height)
        grid_problems, value_problems = [], []
        for name, path in sorted(rasters.items()):
            with rasterio.open(path) as src:
                if (src.crs, src.transform, src.width, src.height) != grid:
                    grid_problems.append(f"{name}: {src.width}×{src.height}, {src.crs}, origin "
                                         f"({src.transform.c:.0f}, {src.transform.f:.0f})")
                    continue
                if name in CONTINUOUS:
                    continue
                values = np.unique(src.read(1))
                if not set(values.tolist()) <= {0, 1}:
                    value_problems.append(f"{name}: values {values[:6].tolist()}")
        ok &= report("all rasters on the 100 m analysis grid of the cost surface", grid_problems)
        ok &= report("mask rasters contain only 0 and 1", value_problems)

        gdbs = [p for p in base.rglob("*.gdb") if p.is_dir()]
        if not gdbs:
            ok &= report("co2_routing.gdb present", ["no .gdb folder"])
        else:
            layers = {row[0] for row in pyogrio.list_layers(gdbs[0])}
            ok &= report(f"geodatabase layers ({gdbs[0].name})",
                         [f"missing {layer}" for layer in GDB_LAYERS if layer not in layers])
            if "sites" in layers:
                sites = pyogrio.read_dataframe(gdbs[0], layer="sites")
                problems = [f"missing column {c}" for c in ("id", "name", "role") if c not in sites.columns]
                if not problems:
                    roles = sites["role"].value_counts().to_dict()
                    if set(roles) - {"source", "storage"}:
                        problems.append(f"unexpected roles {roles}")
                if sites.crs is None or sites.crs.to_epsg() != 25832:
                    problems.append(f"CRS {sites.crs}")
                ok &= report(f"sites layer ({len(sites)} sites)", problems)

        weights_path = next(base.rglob("weights.csv"), None)
        if weights_path is None:
            ok &= report("weights.csv present", ["missing"])
        else:
            rows = list(csv.DictReader(io.StringIO(weights_path.read_text(encoding="utf-8-sig"))))
            problems = [f"missing column {c}" for c in sorted(WEIGHT_COLUMNS - set(rows[0] if rows else []))]
            listed = {row.get("layer") for row in rows}
            problems += [f"no row for layer {name}" for name in sorted(set(config["layers"]) - listed)]
            for row in rows:
                if row.get("raster") and row["raster"] not in rasters:
                    problems.append(f"{row['layer']}: raster {row['raster']} not in the kit")
            ok &= report(f"weights.csv ({len(rows)} rows)", problems)

    print("\nStarter kit OK." if ok else "\nStarter kit has problems.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
