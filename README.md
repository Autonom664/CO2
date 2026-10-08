# Open-source CO2 pipeline routing in Denmark

An open, reproducible demo of least-cost pipeline corridors from Danish CO2
emitters and receiving hubs to potential storage sites. It includes a static
interactive map with source layers, a cost surface, source-to-storage routes,
and a minimum spanning network.

## Project status

The base open datasets and processing pipeline are present. A curated set of
15 illustrative candidate locations is in `data/input/hotspots.csv`: eight
emitters/CO2 hubs and seven potential storage sites. Several storage points
are explicitly labelled as area or field proxies, not confirmed well
locations. Rebuild the extent and cost surface before routing so the Nini West
offshore corridor is included.

## Planned project layout

- `src/` — Python analysis and data-acquisition code
- `config/` — cost values and analysis settings
- `data/input/` — supplied inputs, including `hotspots.csv`
- `data/raw/` — downloaded source data (git-ignored)
- `data/processed/` — reprojected and analysis-ready data
- `data/SOURCES.md` — source, licence, CRS, and download-date register
- `docs/` — method and data documentation
- `web/` — static MapLibre site and generated map assets

## Environment

Create the Conda environment from the repository root:

```powershell
conda env create -f environment.yml
conda activate co2-routing
```

The environment uses conda-forge packages, including GeoPandas, Pyogrio,
Shapely 2, Rasterio, NumPy, PyArrow, scikit-image, and PyYAML. Python 3.11 or
newer is required; Pillow is used for map image rendering. No WSL-only tools
are planned for the initial implementation.

## Data acquisition

After approving the source register, download the approved raw sources and
prepare clipped, reprojected data with:

```powershell
python -m src.acquire_data
```

The first run downloads the source archives into `data/raw/`, queries the
EEA's Denmark Natura 2000 service and the Phase B WFS sources, then writes
the prepared datasets to `data/processed/`. Datafordeler sources require
`DATAFORDELER_API_KEY` in the current PowerShell session; the downloader
skips those optional layers with a warning if it is unset. Load the Windows
user variable without displaying it:

```powershell
$env:DATAFORDELER_API_KEY = [Environment]::GetEnvironmentVariable("DATAFORDELER_API_KEY", "User")
```

OSM features are read from Geofabrik's Denmark GeoPackage
export in spatially filtered batches; the earlier PBF download is not needed
for preparation. The global GHSL 100 m archive is large. To separate the
steps, use `--download-only` and `--prepare-only`; use `--force` with the
download command to replace existing raw files. The script uses the
Geofabrik Denmark boundary and OSM coastline polygons to define Denmark land
plus a 20 km coastal buffer. When the hotspot CSV includes an offshore
storage point, it adds a configurable 10 km half-width corridor between the
nearest coast and that point.

## Analysis design

The analysis grid uses EPSG:25832 at 100 m resolution, snapped to whole 100 m
coordinates over Denmark plus the surrounding sea. This matches the source
population raster's 100 m resolution; 50 m would create about 78 million grid
cells and substantially increase the future routing workload. The grid
resolution is adjustable in `config/costs.yaml`. Class scores are relative
costs per 250 m reference traversal and are scaled to the selected cell size,
so route accumulation remains comparable when resolution changes.

Initial cost scores in `config/costs.yaml` use a validated 1–10 scale and are
subjective, editable assumptions, not monetary estimates. Buildings remain
impassable barriers. Overlapping non-barrier classes add their scores;
configured barrier classes are impassable, and cells outside the buffered
study extent are NoData. Marine cable-corridor zones reduce the combined cell
cost by their configured score, with a floor at the open-land base cost.
Linear features are rasterized with `all_touched: true`; polygon
classes use the pixel-center rule by default. Population values are averaged
onto the analysis grid and positive land-cell values are scaled by quantile.
The script writes a GeoTIFF, per-class coverage/cost statistics, and metadata.
Build the current surface with:

```powershell
python -m src.cost_surface
```

The Baltic Pipe validation surface can be built separately after preparation.
It excludes the reference pipeline ways from the parallel-corridor discount
and writes its raster and sidecars only under `data/processed/validation/`:

```powershell
python -m src.cost_surface --exclude-osm-ids-from validation/baltic_pipe_osm.geojson --output-dir data/processed/validation
```

Least-cost routing will use
`skimage.graph.MCP_Geometric`: one cost-distance run per emitter/hub, with
traceback to each storage candidate. The 8-by-4 source-to-storage matrix
contains 56 directed candidate routes (eight sources × seven storage
candidates). A minimum spanning tree connects all 15 hotspots using the
costs of all 105 hotspot pairs.

With the candidate hotspot input in place, run:

```powershell
python -m src.routing
python -m src.build_web
```

The router validates 15 unique hotspots with `id,name,lon,lat,role` columns,
snaps points only to traversable cells within the configured maximum, computes
the source-to-storage routes, and writes the minimum-spanning network and
route-class lengths. Existing untyped hotspot CSVs retain the all-pairs mode.

`python -m src.build_web` creates a static MapLibre site in `web/`. The cost
surface and each cost/input class are exported as aligned image overlays on a
shared EPSG:3857 display grid; this keeps browser memory and download size bounded
for the multi-million-feature source data while preserving the analysis grid
and original source GeoPackages separately. Overlays are fetched when enabled
and do not refetch on zoom. Routes and hotspots are GeoJSON when available.
Attribution is shown on the map and in `web/SOURCES.md`.

The app is packaged as a static Nginx container:

```powershell
docker compose up -d --build
```

The demo deployment binds to `127.0.0.1:18080`, for use behind an existing
OVH host reverse proxy. See [deploy/README.md](./deploy/README.md) for build,
temporary deployment, HTTPS, DNS prerequisites, and teardown. No DNS or server
changes are made by the build.

Method and ArcGIS tool mapping: [docs/method.md](./docs/method.md).

## Project milestones

- Setup, source acquisition, and the 100 m cost surface are complete.
- Routing code and the static interactive map are implemented.
- The 12 illustrative emitter, hub, and storage candidates are documented in
  `data/input/hotspots.csv`; route outputs are generated after rebuilding the
  extended cost surface. Review the uncertainty notes in `data/SOURCES.md`.
- OVH deployment instructions are in `deploy/README.md`; no OVH server or DNS
  records have been changed.
