# Analysis method and software equivalents

## Cost surface

The current grid is EPSG:25832, aligned to whole 100 m coordinates. The area
is the OSM coastline-derived Denmark land polygon buffered by 20 km. Any
storage hotspot outside that buffer is connected to the nearest coast by a
configurable corridor (10 km half-width by default). The
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
| Road crossing | 3 | Additive linear-feature cost |
| Railway crossing | 5 | Additive linear-feature cost |
| Urban area | 8 | Additive polygon cost |
| Buildings | 10 | Impassable NoData barrier |
| Natura 2000 | 9 | Additive protected-area cost |
| Other protected nature / reserves | 8 | Additive protected-area cost |
| Watercourse crossing | 4 | Additive linear-feature cost |
| Lake / mapped water | 7 | Additive polygon cost |
| Wetland | 7 | Additive polygon cost |
| Population | 1–10 by quantile | Additive, derived from positive population values |

Scores are scaled linearly by `grid.resolution_m /
grid.cost_reference_resolution_m` when the grid changes. The `additive` rule
adds costs for distinct classes where they overlap. Source layers representing
the same class are unioned into one class, avoiding double charging within
Natura 2000 or protected-area subsets. Buildings override all scores as
barriers; areas outside the study extent are NoData.
All configured area scores, including buildings and the population quantile
range, are validated to remain within 1–10. The building score documents its
relative severity; buildings remain explicitly impassable under `barriers`.

Roads, railways, and watercourses are rasterized with `all_touched: true`.
Polygon classes use the pixel-center rule by default. Population is area-
averaged from 100 m data onto the analysis grid and quantile-scaled over
positive population on traversable land. Cost values are cell traversal
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
The curated demo input contains eight emitter/receiving-hub sources and four
potential storage sites. The router performs one cumulative cost run per
source/hub and traces it to each storage candidate, producing up to 32
source-to-storage routes. It selects an 11-edge minimum spanning network
from those candidate connections. Output features include endpoint IDs/names,
roles, project status, path length, accumulated cost, endpoint snap distances,
and kilometres along each cost class, including open sea.

The hotspot input contains exactly 12 rows with unique `id`, non-empty
`name`, WGS84 `lon`/`lat`, and `role=source` or `role=storage`. The code keeps
all-pairs mode for legacy files where no roles are provided. Three onshore
storage coordinates are village-centre proxies for broad exploration areas;
Nini West is an approximate offshore field/platform proxy. These anchors are
for a routing demo, not engineering endpoints or proof of storage suitability.
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
once when toggled and are not re-requested on zoom. Routes and hotspots remain
vector GeoJSON layers.

The basemap is the standard OpenStreetMap raster tile service with required
visible attribution and online-use terms. The app itself is static; there is
no API server or runtime spatial processing. The Docker/Compose setup serves
the site through Nginx on a loopback port for an existing OVH reverse proxy.
Input overlays use stronger opacity than the cost backdrop, and the map note
reminds viewers to zoom in for narrow road and watercourse features.
DNS and TLS are a separate, explicitly authorized deployment operation.

## ArcGIS Pro equivalents

| ArcGIS Pro operation | Open-source equivalent used/planned |
|---|---|
| Project / Define Projection | GeoPandas, PyProj, and Rasterio CRS-aware reprojection |
| Clip | GeoPandas/Shapely geometry intersection against the buffered study extent |
| Polygon to Raster / Feature to Raster | Rasterio `features.rasterize` on the snapped shared grid |
| Cost Distance | `skimage.graph.MCP_Geometric.find_costs` |
| Cost Path | `MCP_Geometric.traceback` |
| Optimal Region Connections | Source-to-storage MCP costs plus Kruskal minimum spanning tree |
| Raster to Polygon / map display | Cost-class mask raster and georeferenced MapLibre image overlays |
| ArcGIS Online web map | Static MapLibre GL JS site served by Nginx |

## Interpretation limits

The values are exploratory relative scores and should be reviewed by the
domain expert before they inform engineering or investment decisions.
OSM buildings and infrastructure have uneven completeness; §3 nature records
are indicative. Protected-area overlaps can increase costs substantially under
the additive rule. Coastal water, including fjords and inlets that the selected
sources do not reliably distinguish, is classed as open sea. There is no
bathymetry or slope penalty in this version.
