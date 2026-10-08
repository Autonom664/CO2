# Disclaimer, and back up before you import

## What this project is, and is not

This project is a **research and teaching tool**. It was built to support
a master's thesis on CO₂ capture and transport at the University of
Copenhagen, and to show how least-cost pipeline routing works.

It is **not** engineering design, a feasibility study, an environmental
assessment, permitting advice or investment advice. Do not use its
routes, corridors, costs or rankings as the basis for decisions about
real infrastructure, land, permits or money.

- **Provided as is**, without warranty of any kind (see [LICENSE](LICENSE)).
  The authors accept no liability for any use of the code, data, results,
  the website or the ArcGIS starter kit.
- **Weights are assumptions,** not costs. They follow published
  multipliers where these exist and judgement elsewhere
  ([docs/wiki/weights.md](docs/wiki/weights.md)). Different, equally
  defensible weights give different routes
  ([sensitivity](docs/wiki/validation.md)).
- **Data may be incomplete, outdated or inaccurate.**
  - OpenStreetMap is volunteer-mapped.
  - Public registers change.
  - Datasets were downloaded on 7–8 October 2026 and are not updated
    automatically.
  - Site locations are representative points, not engineering
    coordinates.
  - **Always check against the authoritative source** listed in
    [data/SOURCES.md](data/SOURCES.md) before relying on any layer.
- **Storage sites, capture volumes and project statuses** come from public
  announcements and the Danish Energy Agency, and say nothing about
  whether a site is licensed, suitable or available.
- **Licences:**
  - The code is MIT.
  - Each dataset keeps its own licence; OpenStreetMap-derived data is
    under the ODbL, © OpenStreetMap contributors.
  - You are responsible for meeting these terms when you reuse anything.

## Back up before you import anything from here

Several things you can take from this project **write or overwrite
files**. Make a backup first, every time.

| If you… | …first back up | Why |
|---|---|---|
| Add the **ArcGIS starter kit** to an existing ArcGIS Pro project | the whole project folder (`.aprx`, its home folder and geodatabases), e.g. a zipped copy | Unzipping into an existing folder can replace files with the same names (`co2_routing.gdb`, `rasters\`). Unzip into a **new, empty folder** |
| Build or run the **ModelBuilder models** | the project and the output geodatabase | With "Allow geoprocessing tools to overwrite existing datasets" on (Options → Geoprocessing), reruns replace outputs silently. Write each scenario to its own output geodatabase or a scenario-named output |
| Load a **scenario file** in the web app, reset it, or try an experiment | nothing extra: the app keeps your previous settings and offers **Restore previous settings** in Scenarios. Use **Save to file** for anything you want to keep | browser storage can be cleared by the browser |
| Run the **Python pipeline** (`src.acquire_data`, `src.cost_surface`, `src.routing`, …) | `data/raw/`, `data/processed/` and `config/` | The pipeline overwrites its outputs in place. Downloading again can take hours |
| Change **`config/costs.yaml`** | a copy of the file, or a git commit | the active weights live only there |
| Use **`tools/publish_public.py`** | the target repository | it rewrites history into a separate copy and pushes it; it only deletes folders it created itself |

Keep at least one copy of your backups **off the same disk**, e.g. on a
cloud drive or a USB disk. For a thesis, also keep the exact scenario file
(weights) and data download date next to every figure, so your results
can be reproduced.

## Contact

Questions or corrections: open an issue at
<https://github.com/Autonom664/CO2/issues>.
