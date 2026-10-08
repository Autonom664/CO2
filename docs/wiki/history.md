# How the model evolved, and what each change did

The model went through five versions in two days. Each change was made for
a stated reason and, from version 3 on, measured. This page is meant as
raw material for a method chapter: it shows which choices mattered.

## Version 1: first working model (7 October)

**What:** a 100 m cost surface with expert weights on a 1–10 scale (wetland
7, urban 8, Natura 2000 9, every OSM road and path charged), 12 sites, and
routes from every site to every other.

**What went wrong:**
- **Roads covered 39% of the land.** Including every OSM way (tracks,
  paths, cycleways) made roads a background charge almost everywhere, so
  routes were pushed *away* from infrastructure, the opposite of practice.
- **Foreign land was treated as cheap sea.** German and Swedish land inside
  the buffer had no layers, so routes could shortcut through it. Fixed by
  removing foreign land from the analysis area.
- **Overlapping protection was charged twice.** A bog that is Natura 2000
  and §3 nature cost 9 + 8.

## Version 2: phase A optimisation, no new data (decision D7)

| Change | Reason |
|---|---|
| Only major and minor roads, weighted by class (4 and 2) | Remove the background charge; minor roads are open-cut, major roads drilled |
| Forest layer (weight 6) | Clearing cost was missing |
| Near buildings: up to 6, falling to 0 at 200 m | A CO₂-specific safety distance; buildings alone are only barriers |
| Natura 2000 and other protection by highest, not sum | One piece of land, one charge |
| ×0.8 alongside power lines (132 kV and up) and gas pipelines | Real pipelines share corridors |

## Version 3: phase B, new open datasets (decisions D8, D10, D11)

| Added | Treatment |
|---|---|
| Drinking water (OSD 4, OD 2), groundwater catchments 3 | cost |
| BNBO, protected monuments, operating wind farms, munitions dumps | barriers |
| Monument zones, contaminated land, beach protection, fredskov | cost |
| Marine spatial plan, planned wind, munitions finds, subsea cables and pipelines | cost |
| Cable corridors | discount |
| Inez, Lisa and Jammerbugt storage areas; DEA licence polygons | 18 sites in total |

**Measured (first unbiased Baltic Pipe test):** the model route was 10%
longer than the real one, with a median distance of 19.8 km. It took about
100 km of sea north of Zealand, where the real line crosses Zealand over
land.

## Version 4: recalibration to published practice (decision D12)

**Reason:** a literature review ([references.md](references.md)) showed
that the construction-cost weights were 3–4× higher than industry
multipliers. Wetland was 8× open land; Kinder Morgan uses 2×.

| Change | Before → after |
|---|---|
| Score range | 1–10 → 0–10 (0 = no extra cost) |
| Wetland, urban | 7, 8 → 1, 1 |
| Forest | 6 → 0.5 |
| Roads major / minor | 4 / 2 → 5 / 0.5 |
| Streams | 4 → 1 |
| Population density | 1–10 → 0–1 |
| Alongside lines | ×0.8 → ×0.9 |
| New: landfall | 10 on coastal land cells |
| New: CO₂ safety | 0–5 from people within 1 km |
| New overlap groups | wet nature, forest, people (highest only) |

**Measured:** the median distance only improved from 19.8 to 18.8 km. The
recalibration alone did not fix the sea detour.

## Version 5: drinking water (decision D14), the published model

**Diagnosis:** the drinking-water layers covered **87.5% of passable
land**. Even with lower construction weights, land cost at least
1 + 2 = 3 while sea cost 2, so sea won.

**Change:** drinking water OD 2 → 0, OSD 4 → 0.5, groundwater catchments
3 → 0.5. BNBO stays a barrier. Drinking-water areas are a permitting
consideration, not a reason to route around; CO₂ doesn't contaminate
groundwater.

**Measured:**

| | v3 | v4 | **v5** |
|---|---|---|---|
| Length vs real Baltic Pipe | +10% | +9% | **+3.5%** |
| Median distance from the real line | 19.8 km | 18.8 km | **13.1 km** |
| Real route inside the 3% corridor | 37% | 42% | **45%** |
| Detour factor, median / max (all 80 routes) | 1.31 / 1.69 | — | **1.27 / 1.55** |

## Lessons worth carrying into any least-cost study

1. **Check layer coverage before weights.** The two biggest distortions
   (roads at 39%, drinking water at 87.5% of land) came from layers that
   covered most of the country, not from extreme weights.
2. **Benchmark early against a real route,** and remove the benchmark's
   own influence: the alongside-lines discount had to ignore Baltic Pipe
   itself.
3. **Measure each change.** Version 4 looked right on paper and barely
   moved the result; version 5's single change mattered most.
4. **Run a sensitivity analysis.** It showed that the choice of storage
   site is robust, while the exact route depends on the sea cost and the
   safety term ([validation.md](validation.md)).
