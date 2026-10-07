# Analysis method and software equivalents

## Cost surface

The current grid is EPSG:25832, aligned to whole 100 m coordinates. The area
is the OSM coastline-derived Denmark land polygon buffered by 20 km. Any
storage hotspot outside that buffer is connected to the nearest coast by a
configurable corridor (10 km half-width by default). Foreign land (German
and Swedish OSM land polygons inside the buffer) is removed from the extent,
so it is NoData rather than cheap sea. The extent excludes the parts of
unclipped OSM land that fall outside Geofabrik's `denmark.poly`, and the
removed area is kept as the `foreign_land` layer in `coast_land_water.gpkg`
for checking. The
100 m cell size matches the nominal GHSL population source resolution. A
50 m grid would have about four times as many cells and was not chosen because
it would raise routing time and memory without improving the input data's
nominal population detail.

`config/costs.yaml` is the authoritative configuration for scores, resolution,
barrier value, class bits, rasterization rules, and display scale. Initial
scores are subjective relative assumptions, not monetary cost estimates.
They use the requested placeholder classes:

| Class | Initial score (1–10, per 250 m reference traversal) | Treatment |
|---|---:|---|
| Open land | 1 | Base cost |
| Open sea | 2 | Base cost; coastal water is open sea |
| Major road (motorway, trunk, primary + links) | 4 | Additive linear-feature cost |
| Minor road (secondary, tertiary + links) | 2 | Additive linear-feature cost |
| Railway crossing | 5 | Additive linear-feature cost |
| Urban area | 8 | Additive polygon cost |
| Buildings | 10 | Impassable NoData barrier |
| Natura 2000 | 9 | Additive protected-area cost |
| Other protected nature / reserves | 8 | Additive protected-area cost |
| Watercourse crossing | 4 | Additive linear-feature cost |
| Lake / mapped water | 7 | Additive polygon cost |
| Wetland | 7 | Additive polygon cost |
| Forest (OSM `landuse=forest`) | 6 | Additive polygon cost, land only |
| Near buildings | 0–6, falling linearly to 0 at 200 m | Additive on land; see the rules below |
| Alongside existing infrastructure | ×0.8 | Discount; see the rules below |
| Population | 0 below threshold; 1–10 by quantile above it | Additive on land only; see the population rule below |

Scores are scaled linearly by `grid.resolution_m /
grid.cost_reference_resolution_m` when the grid changes. The `additive` rule
adds costs for distinct classes where they overlap. The exception is the
`protected_areas` combine group: Natura 2000 and other protected nature
take the **higher** of the two scores (9, not 9 + 8) where they overlap.
Source layers representing the same class are unioned into one class,
avoiding double charging within Natura 2000 or protected-area subsets. Buildings override all scores as
barriers; areas outside the study extent are NoData. Lakes, wetlands and
watercourses add their cost only on land cells (`surface: land` in the
layer configuration). Roads and railways also count over sea, so bridges
add a crossing cost.
All configured area scores, including buildings and the population quantile
range, are validated to remain within 1–10. The building score documents its
relative severity; buildings remain explicitly impassable under `barriers`.

Roads, railways, and watercourses are rasterized with `all_touched: true`.
Polygon classes use the pixel-center rule by default.

**Roads.** Only major and minor roads are costed. Residential, service and
unclassified roads, tracks, paths and cycleways are excluded. When every
OSM way was included, road cells covered 39% of land and acted as a
background charge that pushed routes *away* from existing infrastructure.

**Near buildings (CO2 safety distance).** For land cells within
`costs.dwelling_proximity.max_distance_m` (200 m) of a building cell, the
model adds `max_score × (1 − d / 200 m)`, where `d` is the distance between
cell centres. Buildings themselves stay impassable barriers. At 100 m
resolution this works out as follows:
- An adjacent cell (`d` = 100 m) adds 3.
- A diagonal neighbour (`d` ≈ 141 m) adds about 1.8.
- Cells 200 m or more away add nothing.

This approximates the safety distances that apply to dense-phase CO2
pipelines.

**Alongside existing infrastructure.** Pipelines are normally laid next to
existing linear infrastructure.
- **The infrastructure counted:**
  - major roads and railways
  - OSM `power=line` at 132 kV or more
  - OSM gas pipelines (`man_made=pipeline`, `substance=gas`)
- **The band:** cells 50–300 m from one of these assets, excluding the asset
  cells themselves.
- **The discount:** the cost of a cell in the band is multiplied by
  `parallel_corridor.factor` (0.8), but never goes below the open-land base
  cost.
- **Order:** the discount is applied after the additive classes and before
  the population cost.

Specific OSM ways can be left out with `parallel_corridor.exclude_osm_ids`,
which the Baltic Pipe validation uses (see `validation/README.md`) so the
check does not reuse the pipeline it is checking against.

**Population rule:**
- The 100 m GHSL population is area-averaged onto the analysis grid and
  converted to people per analysis cell.
- Cells below `costs.population.min_per_cell` add no cost. The default
  threshold is 1.0 person per 100 m source cell, roughly 100 inhabitants
  per km², and it scales with cell area if the resolution changes.
- Land cells at or above the threshold are quantile-scaled to the configured
  `minimum`–`maximum` range (1–10), with quantiles computed over those
  qualifying cells only.
- The effect is that population cost marks villages and towns. Sparse rural
  areas (about 0.3 people per 100 m cell on average) cost the same as open
  land. Cost values are cell traversal
weights; repeated presence of a linear feature in consecutive cells adds the
configured score in each such cell, rather than modeling one fixed, point-like
crossing fee.

The builder outputs:

- `data/processed/cost_surface_100m.tif` — positive float32 cell costs and
  `-9999` barrier/outside NoData.
- `data/processed/cost_class_mask_100m.tif` — uint16 bitmask for area/crossing
  classes, used to measure class distance on each route.
- `data/processed/cost_surface_class_statistics.csv` — class coverage and
  configured cost contribution.
- `data/processed/cost_surface_metadata.json` — CRS, alignment, coverage, and
  cost range.

## Hotspot model and routing

`src/routing.py` uses `skimage.graph.MCP_Geometric` with fully connected
8-neighbour movement, so diagonal moves account for their longer distance.
The curated demo input contains eight emitter/receiving-hub sources and seven
potential storage sites. Delivery routes run from every source to every
storage site: 8 × 7 = 56 routes in `routes.geojson`. The minimum spanning
network is built separately from least-cost paths between all
15 × 14 / 2 = 105 hotspot pairs. Its 14 edges can therefore link two emitters,
or an emitter to a hub, directly. The router runs one cumulative cost
calculation per hotspot and traces each run to the hotspots it needs. Output features include endpoint IDs/names,
roles, project status, path length, accumulated cost, endpoint snap distances,
and kilometres along each cost class, including open sea.

The hotspot input contains exactly 15 rows with unique `id`, non-empty
`name`, WGS84 `lon`/`lat`, and `role=source` or `role=storage`. The code keeps
all-pairs mode for legacy files where no roles are provided.

How the storage anchors were placed:
- **Onshore (Gassum, Havnsø, Rødby, Stenlille, Thorning):** the centroid of
  the Danish Energy Agency's licence or designation polygon. These polygons
  cover 150–590 km², so the point is not an injection site.
- **Nini West and Bifrost:** the Nini A and Harald platform positions.

Optional columns carry EU ETS 2024 verified emissions
(`ets_verified_2024_t`), which are fossil only and exclude biogenic CO2,
together with planned capture volumes and their sources. The map shows them
in hotspot popups. These anchors are for a routing demo, not engineering
endpoints or proof of storage suitability.
A hotspot can snap only to the nearest traversable cell within
`routing.max_snap_distance_m`; it errors when outside the cost raster or
farther away. Deliverable routes are written as
`routes.geojson`, `minimum_spanning_network.geojson`, and
`pairwise_route_costs.csv`.

## Interactive map and deployment

`src/build_web.py` produces a static MapLibre application in `web/`. The
100 m analysis surface and each independently toggleable input/class layer
are displayed as georeferenced PNG image sources on a common EPSG:3857 display
grid. This makes their raster pixels line up with the Web Mercator basemap.
The default display grid is 100 m; this is a deliberate web-performance compromise: the
processed GeoPackages preserve the original features, while the browser avoids
loading millions of building/road GeoJSON features. Image sources are loaded
once when toggled and are not re-requested on zoom. Each overlay is cut into PNG tiles of
at most `web.max_image_px` (default 4096) pixels per side, and fully
transparent tiles are skipped. A single country-wide 100 m image (about
9,200 × 7,400 px) exceeds the WebGL texture limit of most phones and many
laptops, and then renders as a blank rectangle. Routes and hotspots remain
vector GeoJSON layers; route lines are simplified to `web.route_simplify_m`
(default 25 m) for display only, and their attributes come unchanged from
`routing.py`. The sidebar lists routes by accumulated cost, filterable by
source. It marks each source's cheapest storage option and the edges in the
minimum spanning network, and highlights and zooms to the selected route.
Each layer toggle shows the class's configured score.

The basemap is the standard OpenStreetMap raster tile service with required
visible attribution and online-use terms. The app itself is static; there is
no API server or runtime spatial processing. The Docker/Compose setup serves
the site through Nginx on a loopback port for an existing OVH reverse proxy.
Input overlays use stronger opacity than the cost backdrop, and the map note
reminds viewers to zoom in for narrow road and watercourse features.
DNS and TLS are a separate, explicitly authorized deployment operation.

## ArcGIS Pro equivalents

Status: **Implemented** means the open workflow runs in this repository;
**Partial** means it covers the ArcGIS tool's role with stated differences;
**Not implemented** means there is no equivalent yet.

| ArcGIS Pro tool | Open-source equivalent | Where | Status |
|---|---|---|---|
| Project / Project Raster | GeoPandas `to_crs`; Rasterio `warp.reproject` | `acquire_data.py`, `cost_surface.py` | Implemented |
| Buffer | Shapely `buffer` (20 km land buffer; offshore corridor half-width) | `acquire_data.py` | Implemented |
| Dissolve / Merge | Shapely `union_all` | `acquire_data.py` | Implemented |
| Clip / Extract by Mask | Geometry intersection with the study extent; cells outside the extent are NoData | `acquire_data.py`, `cost_surface.py` | Implemented |
| Polygon to Raster / Polyline to Raster | Rasterio `features.rasterize` on the snapped 100 m grid (`all_touched` for lines, cell centre for polygons) | `cost_surface.py` | Implemented |
| Resample (population) | Rasterio `reproject` with `Resampling.average` | `cost_surface.py` | Implemented |
| Reclassify / Slice (quantile) | Scores from `config/costs.yaml`; NumPy quantile scaling for population | `cost_surface.py` | Implemented |
| Weighted Sum / Raster Calculator | NumPy addition of class scores (`combine_rule: additive`), with barriers set to NoData | `cost_surface.py` | Implemented |
| Snap Pour Point (snap endpoints) | Nearest traversable cell within `routing.max_snap_distance_m` | `routing.py` | Implemented |
| Cost Distance / Distance Accumulation | `skimage.graph.MCP_Geometric.find_costs`, one run per source | `routing.py` | Implemented |
| Cost Back Link / Cost Path / Optimal Path As Line | `MCP_Geometric.traceback` to each storage cell, written as GeoJSON lines | `routing.py` | Implemented |
| Tabulate Area / Zonal Statistics along routes | Per-step walk of the cost-class bitmask giving `km_*` per class | `routing.py` | Implemented |
| Optimal Region Connections / Cost Connectivity | Kruskal minimum spanning tree over least-cost paths between all 105 hotspot pairs | `routing.py` | Partial: see below |
| Path Distance (slope/vertical factor) | — | — | Not implemented: no terrain model or bathymetry yet |
| Cost Corridor | Sum of two cost-distance rasters | — | Not implemented: would show near-optimal alternative corridors |
| Simplify Line (web display) | Shapely `simplify` (`web.route_simplify_m`, default 25 m) before publishing | `build_web.py` | Implemented |
| Web map / ArcGIS Online | Static MapLibre GL JS site, Nginx container | `build_web.py`, `web/` | Implemented |

**Optimal Region Connections versus this network.** Like ArcGIS, the network
considers connections between every pair of inputs (105 pairs for 15
hotspots), so emitters can link to nearby hubs directly. It differs in three
ways:
- The inputs are points, not regions.
- Each candidate edge is an independent least-cost path, so two edges can run
  side by side without sharing a corridor.
- Pipeline capacity, flow volumes and shared-corridor discounts are not
  modelled.

The result is a minimum spanning tree of independent least-cost paths, not
an engineered trunk-line design.

## Interpretation limits

The values are exploratory relative scores and should be reviewed by the
domain expert before they inform engineering or investment decisions.
OSM buildings and infrastructure have uneven completeness; §3 nature records
are indicative. Protected-area overlaps can increase costs substantially under
the additive rule. Coastal water, including fjords and inlets that the selected
sources do not reliably distinguish, is classed as open sea. There is no
bathymetry or slope penalty in this version.

The Geofabrik `denmark.poly` boundary runs slightly outside the legal border,
so a thin strip of German land just south of it may be treated as Danish land
and costed normally. Nearby German and Swedish *waters* remain traversable
sea.

The per-class route distances (`km_*`) overlap: every step through a cell is
counted in each class present in that cell, and open land is present on all
land cells. They do not add up to `length_km`. Read each value as "km of
route passing through this class".
