# Adjustable browser model: 250 m cost formula

This document is the formula contract for the browser model pack in
`web/data/model/`. It describes the **recomputed 250 m model**; it is not a
resampling of the published 100 m cost raster. The active flattened
`config/costs.yaml` is exported as `config.json` and is the source of all
weights and switches. No cost weight is embedded in the exporter or browser
formula.

## Grid and inputs

- CRS: EPSG:25832.
- Cell size: `browser_model.resolution_m` (currently 250 m); bounds are
  snapped outward to whole-cell coordinates from the configured analysis
  extent. The source mask grid is `browser_model.source_resolution_m`
  (currently 100 m).
- Arrays are north-to-south, west-to-east, C-order row-major. The six-value
  GDAL transform and output bounds are recorded in `grid.json`. A smoke export
  may request an EPSG:25832 bounding box; the target grid expands it outward
  to whole 250 m cells, and the source grid covers those target cells.
- Input features are rasterized on the aligned
  `browser_model.source_resolution_m` analysis grid first.
  Linear layers use `linear_all_touched`; polygon layers use
  `polygon_all_touched`. The 250 m pack mask for a linear layer is true if
  any source-grid cell is true. A polygon layer is true at source-cell
  coverage `>= browser_model.area_presence_threshold` after average
  resampling.
- Land and sea are derived from average source-grid coverage within the
  analysis extent. The configured `browser_model.land_sea_tie_break`
  determines ties. The analysis extent itself is rasterized directly on
  the browser grid.
- Building coverage is the mean of the source-grid building mask in each
  browser cell, rounded to `uint8` using
  `browser_model.building_share_scale`. The configured default barrier
  threshold is `browser_model.building_barrier_share_threshold`
  (currently `128/255`). `building_distance.bin.gz`
  contains Euclidean distance in metres to cells meeting that threshold;
  `65535` is NoData.
- Optional source layers that are absent have `available: false` and an
  empty bit. Missing required source layers stop export.
- `population.bin.gz` is people per browser cell, resampled as an average
  and scaled by cell-area ratio. `population_1km.bin.gz` is the population sum
  in `costs.population_risk.radius_m`, using the configured circular kernel
  and the same cell-centred rule as the Python population-risk function.
  The radius and kernel are precomputed and marked non-adjustable in the
  browser; changing either requires re-exporting the pack. Both use `-9999`
  as NoData.

`grid.json → precomputed` lists each precomputed parameter, its value, why the browser
cannot change it without rebuilding the pack, and all parameter paths that
require re-export. Configured costs, grouping/barrier rules, population
thresholds and quantiles, dwelling-proximity thresholds, and the parallel
corridor factor can be adjusted using the exported masks and arrays. The
parallel corridor's assets and inner/outer distance band are precomputed.
In particular, `building_distance.bin.gz` is based on the configured building
share threshold (currently `128/255`), `population_1km.bin.gz` uses the
configured population-risk radius (currently 1,000 m), and `parallel.bin.gz`
uses the configured 50–300 m band.

## Presence and barriers

`presence_lo.bin.gz` and `presence_hi.bin.gz` are little-endian `uint32`
planes. Bit assignments are enumerated in `layers.json`: source layers are
sorted by name, followed by derived bits for land, sea, buildings, landfall,
and the parallel corridor. Each source-layer entry separately records its
cost key, surface, geometry, availability, and default action. The
single-byte `landfall.bin.gz` and `parallel.bin.gz` files duplicate their
corresponding bits for consumers that prefer byte masks.

The traversable mask is the union of the land and sea bits, less building
cells when `building_barrier` is configured and less all configured barrier
layer masks. Barrier cells and cells outside the analysis extent are
NoData (`-9999` in a cost-grid reference), not finite high-cost cells.
Building presence and its share remain in the pack even where a barrier
applies.

The landfall bit is computed with `landfall.connectivity` (4- or
8-neighbourhood). The pack also records `routing.path_method`,
`routing.fully_connected`, and `routing.snap_distance_metric`; this project
requires `MCP_Geometric`, 8-neighbour routing, and Euclidean snapping.

## Ordered cost calculation

Let `s = resolution_m / cost_reference_resolution_m` (currently 250/250),
`L` be traversable land, `S` traversable sea, and `V = L union S`. A layer
mask is included only when that layer is available. Let `C[k]` be the
configured numeric cost for cost key `k`.

1. **Base:** `cost = C[open_land] * s` on `L` and
   `C[open_sea] * s` on `S`; cells outside `V` remain NoData.
2. **Static max groups:** for each `combine_groups` entry whose members
   are all static, take the maximum `C[k] * s` among the member masks at
   each cell and add it once. Overlapping members in a max group are not
   summed.
3. **Other static layers:** union presence masks that share a cost key and
   add `C[k] * s` once per cell. Classes in `discount_classes` instead
   subtract `C[k] * s`, with a floor of `C[open_land] * s`.
4. **Landfall:** when enabled, add `C[landfall] * s` once to landfall cells
   that remain traversable land. Sea cells never receive this contribution.
5. **Dwelling proximity:** when enabled, on traversable land and at
   `0 < distance < max_distance_m`, add
   `max_score * (1 - distance / max_distance_m) * s`.
6. **Parallel corridor:** when enabled, use the exported browser-grid corridor
   mask, excluding asset cells and barriers. Multiply the current cost by
   `factor`, with a floor of `C[open_land] * s`. The corridor is derived
   from the configured assets, Euclidean inner/outer distance, and default
   barrier mask; changing those inputs requires re-export.
7. **Population:** when enabled, eligible land cells have positive
   population at least
   `min_per_cell * (resolution_m / reference_cell_resolution_m)^2`.
   `reference_cell_resolution_m` is in `costs.population`. Quantile thresholds use linear
   interpolation (`numpy.quantile` semantics); duplicate thresholds map
   to the mean of their score levels, then scores are linearly interpolated
   from `minimum` to `maximum`. Add the resulting score multiplied by `s`.
8. **Population risk:** when enabled, cells on traversable land with the
   circular population sum strictly greater than `threshold_people` are
   quantile-scored from zero to `maximum`, using the same quantile and
   duplicate-threshold rules, then multiplied by `s`.
9. **Deferred max groups:** groups containing population, population risk,
   or dwelling proximity are added after those dynamic scores are built.
   Their per-cell contribution is the maximum score among present members,
   including any static member, not the sum. The parity reference uses the
   default `max` group rule; the app may let Lauge switch a group's rule to
   additive for interactive scenarios.

The final finite costs must be positive. The browser routing engine uses
8-neighbour movement and the MCP Geometric edge convention: for adjacent
cells `a` and `b`, the transition cost is
`(cost[a] + cost[b]) / 2 * (1 for orthogonal, sqrt(2) for diagonal)`.

## Reference generation and acceptance

After the model pack is exported, run:

```powershell
python -m validation.model_parity --verbose
```

The command verifies manifest hashes, builds the default surface plus
`protection_low` and `protection_high` weight perturbations, computes every
source-to-storage route using one `MCP_Geometric` cost-distance run per
source, and writes cost-grid binaries plus `model_parity.json` under
`validation/model_parity/`. `model_parity.json` includes snapped endpoints,
route lengths and accumulated costs, grid metadata, input hashes, and the
acceptance criteria.

Browser parity is accepted only when all scenarios have identical
traversability and both the maximum cellwise relative cost error and each
route accumulated-cost relative error are at most **0.5%**. This tolerance
is a test threshold, not a claim that browser parity has already passed.
