# Build the model in ArcGIS Pro ModelBuilder

This guide builds the whole routing model as **five ModelBuilder models**,
click by click, from the **ArcGIS starter kit**. The kit contains every
layer already prepared as 100 m rasters, so the heavy data work is done
and you can concentrate on the method.

At the end, every weight is a **model parameter**. Rerunning a scenario
is then like pressing Run in the web app: change numbers in the model's
dialog box and run it.

| Model | Does | Main tools |
|---|---|---|
| 1. Cost Surface | weights → cost raster | Raster Calculator, Cell Statistics, Euclidean Distance, Focal Statistics, Slice, Set Null |
| 2. Delivery Routes | one route from every source to every storage site | Iterate Feature Selection, Distance Accumulation, Optimal Path As Line, Merge |
| 3. Network | the cheapest network joining all sites | Optimal Region Connections |
| 4. Corridor | the 1% / 3% near-optimal corridor for one route | Distance Accumulation ×2, Cost Corridor, Raster Calculator |
| 5. Baltic Pipe check | compare a model route with the real pipeline | Optimal Path As Line, Generate Points Along Lines, Near |

**You need:** ArcGIS Pro 3.x with the **Spatial Analyst** extension
(normally included in a university licence), and the starter kit (about
100 MB).

---

## 0. The starter kit

Download it from the app (**Model settings → Learn → ArcGIS starter
kit**) and unzip it to a short path, for example `C:\co2kit\`.

| Item | Contents |
|---|---|
| `co2_routing.gdb` | `sites` (18 points: `id`, `name`, `role` = source / storage), `analysis_area`, `published_routes`, `published_network`, `published_corridors`, `storage_areas`, `baltic_pipe_osm` |
| `rasters\land.tif`, `sea.tif` | 1 where the cell is land / sea in the analysis area, else 0 |
| `rasters\l_<layer>.tif` | one raster per layer: 1 where present, 0 elsewhere. All 35 layers, for example `l_wetlands.tif`, `l_natura2000_habitats.tif`, `l_roads_major.tif` |
| `rasters\buildings.tif` | 1 where a 100 m cell contains a building |
| `rasters\population.tif` | people per 100 m cell (GHSL 2020) |
| `rasters\parallel_assets.tif` | 1 on power lines (132 kV and up) and gas pipelines |
| `rasters\published_cost_100m.tif` | the published cost surface, to compare with your own |
| `weights.csv` | every layer: weight, treatment (cost / barrier), group, source, reason |

All rasters share the same grid: **EPSG:25832, 100 m cells, identical
extent**. Lines (roads, streams) are already rasterised so that every cell
they touch counts.

---

## 1. Project set-up (once)

1. **New project** → Map. Add `co2_routing.gdb\sites` and `land.tif`.
2. **Analysis → Environments** (these apply to every model):

   | Environment | Value |
   |---|---|
   | Output Coordinate System | ETRS 1989 UTM Zone 32N (EPSG:25832) |
   | Processing Extent | Same as layer `land.tif` |
   | Snap Raster | `land.tif` |
   | Cell Size | Same as layer `land.tif` (100) |
   | Mask | `land.tif` *(not for sea; see the note below)* |
   | Parallel Processing Factor | 100% |

   Leave **Mask** empty if the routes must be able to cross the sea, as
   they should here. The analysis area is already built into `land.tif` +
   `sea.tif`.
3. **Catalog → Toolboxes → New Toolbox (.atbx)**: `CO2Routing.atbx`.
   Right-click it → **New → Model** for each of the five models below.

**Weights per cell:** in the web app, weights are defined per 250 m and
multiplied by 0.4 at 100 m. In ArcGIS you can use the weights directly
(open land = 1). **The routes are identical**, because every cell is
scaled by the same factor; only the accumulated-cost numbers are 2.5×
larger.

---

## 2. Model 1: Cost Surface

### 2.1 Model parameters

In the model, right-click empty canvas → **Create Variable → Double** for
each weight, rename it, set its value, then right-click it → **Parameter**
(a **P** appears). Start with the published values from `weights.csv`:

| Variable | Value | | Variable | Value |
|---|---|---|---|---|
| `W_sea` | 2 | | `W_landfall` | 10 |
| `W_road_major` | 5 | | `W_road_minor` | 0.5 |
| `W_rail` | 5 | | `W_stream` | 1 |
| `W_lake` | 7 | | `W_wetland` | 1 |
| `W_water_protect` | 5 | | `W_natura` | 9 |
| `W_s3` | 8 | | `W_forest` | 0.5 |
| `W_fredskov` | 7 | | `W_urban` | 1 |
| `W_osd` | 0.5 | | `W_od` | 0 |
| `W_catchment` | 0.5 | | `W_monument_zone` | 5 |
| `W_contam_v2` | 6 | | `W_contam_v1` | 3 |
| `W_beach` | 7 | | `W_shipping` | 6 |
| `W_renewables` | 8 | | `W_materials` | 6 |
| `W_wind_planned` | 7 | | `W_munitions` | 8 |
| `W_subsea_pipe` | 4 | | `W_subsea_cable` | 5 |
| `W_cable_corridor` | 1 | | `F_parallel` | 0.9 |
| `W_near_buildings` | 6 | | `D_near_buildings` | 200 |
| `W_pop_max` | 1 | | `W_risk_max` | 5 |
| `N_risk_threshold` | 50 | | | |

In expressions, refer to a variable as `%W_sea%` (inline variable
substitution). ModelBuilder replaces it with the value at run time.

### 2.2 The steps

Add each tool from the **Geoprocessing** pane by dragging it onto the
canvas. Connect inputs by dragging from a variable to the tool. Name every
output clearly; the names below are the ones the next steps use.

**Step A: base surface.** *Raster Calculator* → `base`

```
Con("land.tif" == 1, 1, Con("sea.tif" == 1, %W_sea%))
```

Cells that are neither land nor sea become NoData, so they are outside the
model.

**Step B: wet nature, highest only.** *Cell Statistics*, statistic
**Maximum**, "Ignore NoData" ticked → `wet_nature`. Inputs: five *Raster
Calculator* outputs:

```
%W_wetland% * "l_wetlands.tif"
%W_s3% * "l_protected_nature_s3.tif"
%W_s3% * "l_protected_reserves.tif"
%W_natura% * "l_natura2000_habitats.tif"
%W_natura% * "l_natura2000_birds.tif"
```

Why "maximum": a bog that is wetland, §3 nature and Natura 2000 is one
obstacle and should be charged once, by its strictest status.

**Step C: forest, highest only.** *Cell Statistics* (Maximum) of
`%W_forest% * "l_forest.tif"` and `%W_fredskov% * "l_fredskov.tif"` →
`forest_group`.

**Step D: the other layers, added.** *Raster Calculator* → `others`

```
%W_road_major% * "l_roads_major.tif" + %W_road_minor% * "l_roads_minor.tif"
+ %W_rail% * "l_railways.tif" + %W_stream% * "l_watercourses.tif"
+ %W_lake% * "l_lakes.tif" + %W_water_protect% * "l_water_protection_lines.tif"
+ %W_osd% * "l_drinking_water_osd.tif" + %W_od% * "l_drinking_water_od.tif"
+ %W_catchment% * "l_groundwater_catchments.tif"
+ %W_monument_zone% * "l_ancient_monument_protection.tif"
+ %W_contam_v2% * "l_contaminated_v2.tif" + %W_contam_v1% * "l_contaminated_v1.tif"
+ %W_beach% * "l_beach_protection.tif"
+ %W_shipping% * "l_marine_shipping.tif" + %W_renewables% * "l_marine_renewables.tif"
+ %W_materials% * "l_marine_materials.tif" + %W_wind_planned% * "l_offshore_wind_planned.tif"
+ %W_munitions% * "l_munitions_points.tif"
+ %W_subsea_pipe% * "l_subsea_pipelines.tif" + %W_subsea_cable% * "l_subsea_cables.tif"
```

**Step E: landfall.** *Expand* `sea.tif`, zone value 1, 1 cell →
`sea_plus1`. Then *Raster Calculator* → `landfall`:

```
Con(("land.tif" == 1) & ("sea_plus1" == 1), %W_landfall%, 0)
```

**Step F: sum, then the cable-corridor discount.** *Raster Calculator* →
`static_cost`:

```
Con("l_marine_cable_corridor.tif" == 1,
    Max(1, "base" + "wet_nature" + "forest_group" + "others" + "landfall" - %W_cable_corridor%),
    "base" + "wet_nature" + "forest_group" + "others" + "landfall")
```

The discount is floored at 1, the cost of open land.

**Step G: discount alongside existing lines.**
1. *Euclidean Distance* from `parallel_assets.tif` (set 0 to NoData first
   with *Set Null*: `SetNull("parallel_assets.tif" == 0, 1)`) →
   `dist_assets`.
2. *Raster Calculator* → `cost_parallel`:

   ```
   Con(("dist_assets" >= 50) & ("dist_assets" <= 300),
       Max(1, "static_cost" * %F_parallel%), "static_cost")
   ```

**Step H: people and safety, highest only.**
1. **Near buildings.** *Set Null* `buildings.tif` where 0 →
   `buildings_only`. *Euclidean Distance* → `dist_buildings`. *Raster
   Calculator* → `near_buildings`:

   ```
   Con(("land.tif" == 1) & ("dist_buildings" > 0) & ("dist_buildings" < %D_near_buildings%),
       %W_near_buildings% * (1 - "dist_buildings" / %D_near_buildings%), 0)
   ```
2. **Population density** (quantile-scaled 0 to `W_pop_max`). *Set Null*
   `population.tif` where `< 1` → `pop_eligible`. *Slice*, method
   **Equal area**, 100 zones → `pop_zones`. *Raster Calculator* →
   `pop_score`:

   ```
   Con(IsNull("pop_zones"), 0, ("pop_zones" - 1) / 99.0 * %W_pop_max%)
   ```
3. **CO₂ safety: people within 1 km.** *Focal Statistics* on
   `population.tif`, neighbourhood **Circle, radius 10 cells**, statistic
   **Sum** → `pop_1km`. *Set Null* where `<= %N_risk_threshold%` →
   `risk_eligible`. *Slice*, Equal area, 5 zones → `risk_zones`. *Raster
   Calculator* → `risk_score`:

   ```
   Con(IsNull("risk_zones"), 0, "risk_zones" / 5.0 * %W_risk_max%)
   ```
4. *Cell Statistics* (Maximum) of `%W_urban% * "l_urban_areas.tif"`,
   `near_buildings`, `pop_score` and `risk_score` → `people`.

**Step I: final cost with barriers.** *Raster Calculator* → `cost_surface`
(make it a **parameter** so it shows as the model's output):

```
SetNull(("buildings.tif" == 1) | ("l_bnbo.tif" == 1)
        | ("l_ancient_monuments_area.tif" == 1) | ("l_ancient_monuments_line.tif" == 1)
        | ("l_ancient_monuments_point.tif" == 1) | ("l_offshore_wind_barriers.tif" == 1)
        | ("l_munitions_barriers.tif" == 1),
        "cost_parallel" + "people")
```

Validate (✓), then Run. Compare `cost_surface` with
`published_cost_100m.tif` (multiply theirs by 2.5): roads, protected areas
and towns should line up.

**About differences from the app:**
- *Slice* (equal area) is close to, but not exactly, the app's
  interpolated quantiles.
- The app blocks a 250 m cell only when half of it is built over; here,
  every 100 m cell with a building is blocked.
- So expect very similar, not identical, routes.

---

## 3. Model 2: Delivery Routes (one route per source → storage pair)

1. Drag `sites` in twice. Add **Make Feature Layer** for each, with
   expressions `role = 'source'` → `sources` and `role = 'storage'` →
   `storage`.
2. **Insert → Iterators → Iterate Feature Selection**: input `sources`,
   group by `id`. This outputs one selected source per iteration and its
   `Value` (the id).
3. **Distance Accumulation**:
   - input sources: the iterator output
   - input cost raster: `cost_surface` (from Model 1, or browse to it)
   - out back direction raster: `back_%Value%`
   - output: `acc_%Value%`
4. **Optimal Path As Line**:
   - destinations: `storage`, destination field `id`
   - distance accumulation raster: `acc_%Value%`
   - back direction raster: `back_%Value%`
   - path type: **Each zone** (one line per storage site)
   - output: `routes_%Value%`
5. **Add Field** `from_id` (Text) and **Calculate Field**
   `from_id = "%Value%"`, so every line knows its source.
6. **Collect Values** (Insert → Utilities) on `routes_%Value%`. Outside the
   iteration, run **Merge** on the collected values → `all_routes`.

Iterators only work in their own model, so run Model 2 as a separate model
that takes `cost_surface` as a parameter. Then **Summary Statistics** on
`all_routes` grouped by `from_id` (minimum cost) gives the **best storage
site** per source.

---

## 4. Model 3: Network

**Optimal Region Connections**:
- input regions: `sites`
- input cost raster: `cost_surface`
- output: `network`

The tool always builds a minimum spanning tree, so there is no option to
set. The output is the cheapest set of links joining all 18 sites, with no
loops. The optional "neighbor paths" output also gives the links between
every pair of nearby sites, which is useful for seeing alternatives. Compare it with `published_network`.

---

## 5. Model 4: Corridor for one route

1. Parameters: `from_site` and `to_site` (two **Make Feature Layer**
   outputs from `sites`, with a SQL parameter such as `id = 'aalborg_portland'`).
2. **Distance Accumulation** from `from_site` → `acc_a`; again from
   `to_site` → `acc_b`.
3. **Cost Corridor** with `acc_a` and `acc_b` → `corridor_cost`.
4. **Get Raster Properties**, property **MINIMUM**, on `corridor_cost` →
   `optimum`.
5. *Raster Calculator* → `corridor`:

   ```
   Con("corridor_cost" <= %optimum% * 1.01, 1, Con("corridor_cost" <= %optimum% * 1.03, 2))
   ```

   1 = within 1% of the optimum, 2 = within 3%.
6. **Raster to Polygon** for display.

A narrow corridor means one clearly best route; a wide one means many
almost equally good options.

---

## 6. Model 5: Baltic Pipe check

1. A copy of Model 1 with **F_parallel = 1** (no discount). Otherwise the
   model would be rewarded for following the real pipeline, which is in
   the power-and-gas assets.
2. Two points: the start and end of `baltic_pipe_osm`.
   - With an **Advanced** licence: **Feature Vertices To Points**, Start
     and End.
   - With any licence: **Generate Points Along Lines** on
     `baltic_pipe_osm`, by percentage, 100%, with **"Include end points"**
     ticked. Keep the first and the last point.
3. **Distance Accumulation** from the start, then **Optimal Path As Line**
   to the end → `model_route`.
4. **Generate Points Along Lines** on `baltic_pipe_osm`, every 100 m →
   `ref_points`.
5. **Near**, `ref_points` to `model_route`. **Summary Statistics** of
   `NEAR_DIST` (median, mean) gives the distance between the lines. The
   published model scores a 13.1 km median.

---

## 7. Making it your own

- **Experiments as parameter sets:** run Model 1 with different values
  and name the outputs `cost_<scenario>`. The experiments page lists ideas
  ([experiments.md](experiments.md)).
- **A batch run:** right-click the model → **Batch** runs several weight
  sets in one go, which is a sensitivity analysis like
  [validation.md](validation.md).
- **New layers:** rasterise them with *Polygon to Raster* or *Polyline to
  Raster* (Snap Raster set!), then add one term to Step D, or to a group in
  Step B, C or H.
- **Export the model as Python:** **Export → Export To Python File**
  shows the arcpy code behind your model, a good bridge to scripting.
- **Document the model:** right-click each tool → **Properties** → a
  label and description. ModelBuilder diagrams make good thesis figures
  (**Export → Export as Graphic**).

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Rasters are shifted by half a cell | Snap Raster not set before running |
| `%W_sea%` appears literally in an error | The variable is not connected or not named exactly; inline names are case-sensitive |
| Routes stop at the coast | Mask was set to `land.tif`; clear it |
| All costs NoData | A barrier raster is NoData instead of 0; use `Con(IsNull(r), 0, r)` |
| Distance Accumulation is slow | Normal for all of Denmark (minutes). Test on a smaller Processing Extent first |
| "Spatial Analyst license not available" | Project → Licensing → enable Spatial Analyst |
