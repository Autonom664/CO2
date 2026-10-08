# How the data is prepared

This page follows the pipeline from downloaded files to the grids used by
the Python model and the browser. The preparation code is in
[`src/acquire_data.py`](../../src/acquire_data.py), and its settings are in
[`config/costs.yaml`](../../config/costs.yaml).

## 1. Download and keep the originals

The acquisition script stores source archives and paged WFS responses under
`data/raw/`, which is git-ignored. It records checksums and download metadata
in `data/raw/acquisition-manifest.json`. Re-downloads use the same verified
source definitions rather than hand-entered URLs.

```powershell
python -m src.acquire_data --download-only
python -m src.acquire_data --prepare-only
```

If the base layers already exist and only the phase-B WFS layers need
rebuilding, use `python -m src.acquire_data --prepare-only --resume phase_b`.
The prepared, reprojected outputs go in `data/processed/`.

## 2. Build the land-and-sea analysis extent

1. Read the Geofabrik Denmark boundary and OSM land polygons, then project
   them to EPSG:25832 (ETRS89 / UTM 32N).
2. Buffer the Danish land geometry by 20 km. Storage points beyond that
   buffer extend the study area through 10 km half-width offshore corridors;
   the three North Sea storage proxies also get a shared corridor envelope.
   These corridors prevent an offshore site from falling outside the raster.
   The 20 km buffer supplies nearby sea and land alternatives without
   rasterizing an unbounded region; the 10 km half-width is a practical
   analysis-window choice, not a surveyed pipeline corridor.
3. Read coastline-derived land in the expanded area. Land outside the
   Geofabrik Denmark boundary is removed from the analysis extent. Foreign
   waters are retained, so routing can cross straits and offshore waters.
   Removing foreign land prevents the study area from treating Germany or
   Sweden as traversable Danish territory, while keeping foreign water lets
   routes cross straits instead of stopping at the national boundary.
4. Intersect Denmark land with the extent. The sea geometry is the extent
   minus that land. Both masks and the extent are saved in
   `coast_land_water.gpkg`.

The boundary and coastline are open-data approximations, not surveyed legal
borders. The foreign-land layer is retained for inspection.

## 3. Project, repair and clip source features

Vector layers are reprojected to EPSG:25832 and clipped to the analysis
extent. Invalid input geometry is repaired with `make_valid` before testing
intersection and applying the clip. Empty results and unhandled
`GeometryCollection` outputs are removed; a missing required source or an
empty required layer is an explicit error.

Repairing invalid geometry before overlays avoids topology failures during
intersection and clipping. Empty and unsupported collection results cannot
be written reliably as the expected layer geometry type, so they are removed;
missing required inputs remain explicit errors rather than silently
producing incomplete model layers.

- The Geofabrik GeoPackage supplies selected roads, railways, buildings,
  water, land use and forest. Major roads are motorways, trunks and primary
  roads; minor roads are secondary and tertiary roads.
- The OSM PBF supplies `power=line` ways at 132 kV or higher and gas pipeline
  ways. Road/forest batches are clipped as they are read to limit memory use.
- The phase-B source pages are split into model layers using their documented
  attributes: drinking-water OSD/OD category, maritime-plan zone type and
  EMODnet wind-farm status. Munitions point locations are buffered by 500 m.
- The EEA Natura 2000 layers, protected-nature downloads, storage polygons,
  and WFS layers are projected and clipped with the same extent.
- Duplicate field names that differ only by case are renamed before writing
  GeoPackages, preventing fields such as `Id` and `ID` from colliding.
  Some source pages contain these case-insensitive name collisions; GeoPackage
  fields are case-insensitive too, so preserving both under distinct names
  prevents one attribute from overwriting or hiding another.

## 4. Prepare population

GHS-POP 2020 is supplied in ESRI:54009. The script reads only the source
window intersecting the study area, reprojects it to EPSG:25832 at 100 m
using area-average resampling, and writes a tiled, compressed Float32 GeoTIFF
with `-9999` NoData. The value represents people per 100 m cell.
Area-average resampling aligns the population grid with the model cells while
avoiding a nearest-neighbour assignment at the projection boundary; reading
only the intersecting window avoids processing the global raster.

## 5. Rasterize the Python model

The published Python cost surface is a 100 m EPSG:25832 raster. Grid edges
are snapped outward to whole 100 m coordinates. The baseline rasterizer
uses `polygon_all_touched: false`; configured linear features use
`linear_all_touched: true`, so crossing features are not missed between
cell centres. Linear features can be thinner than a cell, so touching-cell
rasterization prevents a route from slipping through a diagonal gap. For
area polygons, the cell-centre rule avoids expanding every boundary sliver
into a full-cost cell and keeps area coverage interpretation consistent.
The exact rasterization settings and per-class statistics
are recorded in the cost-surface metadata and statistics CSV.

The input rasters are converted to presence/class masks and combined using
the active `config/costs.yaml` rules. A barrier or a cell outside the extent
is NoData, not merely a very large finite cost. Cost groups, discounts,
population, dwelling proximity, landfall and corridors follow the ordered
formula described in [`model_formula.md`](../model_formula.md).

## 6. Prepare the browser model pack

The browser pack is a separate, explicitly aggregated 250 m model. Its
source masks are rasterized at the configured 100 m source resolution on
the aligned grid, then transferred to the 250 m browser grid:

- **Why 250 m:** the coarser grid keeps the downloadable browser pack and
  interactive recalculations manageable. It is an exploration model, so
  aggregation can change narrow features and route choices; the 100 m Python
  surface remains the higher-resolution reference.
- **Area layers:** average 100 m coverage; present at or above the configured
  `area_presence_threshold` (currently 0.5).
  This requires at least half of the target cell to be covered, rather than
  treating a small polygon sliver as full-cell presence.
- **Linear layers:** `max` resampling, meaning any hit at source resolution
  marks the 250 m cell. This preserves narrow crossings that would disappear
  if line coverage were averaged.
- **Land and sea:** compare their average source-grid coverage; ties follow
  the configured land/sea tie-break. The dominant coverage avoids classifying
  a target cell from a narrow coastline sliver.
- **Buildings:** average coverage is quantized to the configured byte scale.
  The configured threshold controls the barrier and the building-distance
  plane, retaining sub-cell coverage information without storing a full
  100 m building mask in the browser pack.
- **Population:** resample to the 250 m grid with cell-area scaling. The
  population-risk neighborhood and parallel-corridor band are precomputed;
  scaling keeps population counts aligned with target-cell area. The
  neighborhood and corridor values, and their re-export requirements, are in
  `grid.json → precomputed`.

The target grid origin is snapped to whole 250 m coordinates. For a smoke
export, `--bbox XMIN YMIN XMAX YMAX` takes EPSG:25832 coordinates and expands
the requested window outward to whole target cells. The 100 m source window
is expanded as needed to cover those target cells. The exported `grid.json`
records the actual bounds and the requested window.

The browser's 250 m results are a fast, adjustable exploration model; they
are not a replacement for the 100 m Python references. Source masks,
aggregation thresholds, and the precomputed distance/neighborhood assets
are documented in [`model_formula.md`](../model_formula.md).
