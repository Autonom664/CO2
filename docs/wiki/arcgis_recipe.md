# Rebuild this model in ArcGIS Pro

A tool-by-tool recipe. Build it once in **ModelBuilder**, with every
weight as a model parameter, and you can rerun scenarios the same way the
app does.

## 0. Environment settings (do this first)

| Setting | Value | Why |
|---|---|---|
| Output coordinate system | ETRS89 / UTM zone 32N (EPSG:25832) | metric, the Danish standard |
| Cell size | 100 | matches the population data |
| Snap raster | your base grid raster | every layer lines up cell for cell |
| Extent | your analysis area | |
| Mask | your analysis area raster | everything outside is NoData |

Forgetting the snap raster is the most common cause of half-cell shifts
between layers.

## 1. Analysis area

1. Danish land polygon → **Pairwise Buffer** 20 km.
2. **Pairwise Erase** foreign land (Germany, Sweden).
3. Add corridors to offshore storage sites. A buffered line from the coast
   to each site, 10 km either side, is enough.
4. **Polygon to Raster** → `area` (1 inside, NoData outside).

## 2. Base surface

- Land/sea raster from the land polygon: land = 1, sea = 2 (the base
  costs).
- Raster Calculator:
  `base = Con("land" == 1, 1, 2)`

## 3. One raster per layer

- **Polygons:** **Polygon to Raster**, cell centre, value 1, then
  `Con(IsNull(r), 0, 1)` so that absence is 0, not NoData.
- **Lines (roads, railways, streams):** **Polyline to Raster**. To charge
  every cell a line touches, as this model does, first buffer the lines by
  about half a cell (50 m) and rasterise the buffer as a polygon.

## 4. Combine the weights

**Additive layers:**
- `cost = base + 5*"roads_major" + 0.5*"roads_minor" + 5*"railways" + …`
- Or use **Weighted Sum** with weight = the layer weight, plus the base.

**Groups take the highest value instead of the sum:**

```
wet_nature = CellStatistics([1*"wetland", 8*"s3", 9*"natura2000"], "MAXIMUM")
```

Then add `wet_nature` once. Do the same for forest_group (forest,
fredskov) and people.

**Distance-based terms:**

| Term | Tools |
|---|---|
| Near buildings | **Euclidean Distance** from buildings, then `Con(d < 200, 6 * (1 - d/200), 0)` |
| CO₂ safety | **Focal Statistics** on population, *Circle* radius 1000 m, *SUM*; then **Slice** (equal area, 5 zones) above 50 people, scaled 0–5 |
| Population density | **Slice** (equal area) of people per cell above 1, scaled 0–1 |
| Landfall | **Expand** the sea by 1 cell, then `Con(land & expanded_sea, 10, 0)` |
| Alongside lines | **Euclidean Distance** from power lines and gas pipelines, then `Con((d >= 50) & (d <= 300), cost * 0.9, cost)`, and never below 1 |

**Barriers:** `cost = SetNull(barriers == 1, cost)`, where barriers are
buildings, BNBO, monuments, wind farms and munitions.

## 5. Routes

1. **Distance Accumulation**, with sources = one emitter and the cost
   surface = `cost`. Output: an accumulation raster and a back-direction
   raster.
2. **Optimal Path As Line**, with destinations = the storage sites. One
   line per storage site, with its cost.
3. Repeat for each emitter (ModelBuilder: **Iterate Feature Selection**).

ArcGIS charges a step as the average of the two cells × the distance,
×√2 diagonally, exactly as this model does. With the same cost raster,
your routes should match the published ones.

## 6. Network

**Optimal Region Connections**, with all sites as regions and the cost
surface. Output: the minimum spanning tree of least-cost links.

## 7. Corridors

1. **Cost Corridor** from two accumulation rasters (source and
   destination).
2. `Con(corridor <= min * 1.01, 1)` for the 1% corridor; use 1.03 for 3%.

## 8. Check against Baltic Pipe

- Route between the real endpoints (Blåbjerg landfall and Faxe) and
  compare with the as-built line.
- Measure the median distance between the two lines with **Generate Near
  Table** on points every 100 m.
- Leave out the "alongside existing lines" discount for the real pipeline
  itself. Otherwise the model is rewarded for following the answer.

## Time on a normal laptop (rough)

| Step | 100 m, all of Denmark |
|---|---|
| Rasterising buildings (3.75 million) | 5–15 min |
| One Distance Accumulation | 1–3 min |
| 8 sources × routes | 10–25 min |
| Optimal Region Connections, 18 sites | 10–30 min |

A 250 m grid for exploring, then 100 m for the final figures, is the same
trade-off this app makes.
