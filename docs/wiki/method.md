# How the routing works, and why

## The idea in one paragraph

Every 100 m × 100 m cell of Denmark and its surrounding sea gets a
**cost**: how hard it is to build a pipeline through it. Open land costs
1. A wetland adds 1 (it costs 2), a motorway crossing adds 5, a building
is impassable. The **least-cost route** between two sites is the path
whose summed cell costs are smallest. It is the same idea as ArcGIS
**Cost Distance** followed by **Cost Path**.

## The steps

| Step | What happens | ArcGIS Pro equivalent |
|---|---|---|
| 1. Analysis area | Danish land plus a 20 km sea buffer, plus corridors to the offshore storage sites. Foreign land (Germany, Sweden) is removed | Buffer, Erase, Polygon to Raster |
| 2. Rasterise layers | Each source layer becomes a 100 m grid of "present / not present" | Polygon to Raster, Polyline to Raster (snap raster!) |
| 3. Cost surface | Base cost (land 1, sea 2), plus the weight of every layer present, with the special rules below | Weighted Sum, Raster Calculator, Cell Statistics (MAX) |
| 4. Barriers | Buildings, wellhead zones (BNBO), monuments, wind farms and munitions dumps become NoData | Set Null |
| 5. Accumulated cost | From each source site, the cheapest cost to reach every cell | Distance Accumulation / Cost Distance |
| 6. Routes | Trace back from each storage site to the source | Optimal Path As Line / Cost Path |
| 7. Network | Join all 18 sites with the cheapest set of links (a minimum spanning tree) | Optimal Region Connections |
| 8. Corridors | Every cell whose best path is within 1% or 3% of the optimum | Cost Corridor, then Con(<= optimum × 1.01) |

## How one step between cells is charged

Moving from cell A to a neighbouring cell B costs
**(cost A + cost B) ÷ 2 × step length**, where the step length is 1 for a
side neighbour and √2 for a diagonal one. This is exactly the rule ArcGIS
Cost Distance uses, so results built in ArcGIS Pro with the same cost
raster should match closely.

The tool used here is `MCP_Geometric` from the Python library
scikit-image, and the app's browser engine reproduces it to nine decimal
places.

## Special rules in the cost surface

- **Highest only, not sum, for overlapping layers that mean the same
  thing.**
  - Wetland, §3 nature and Natura 2000 often cover the same ground. Adding
    all three would charge the same bog three times. The cell takes the
    highest of the three.
  - The same applies to forest + protected forest, and to the people
    group (urban, population, near buildings, CO₂ safety).
- **Discount alongside existing lines.** Cells 50–300 m from power lines
  (132 kV and up) and gas pipelines are multiplied by 0.9. Pipelines
  follow existing corridors where they can. The discount never goes below
  the open-land cost.
- **Landfall.** Land cells next to the sea add 10, which stands in for the
  cost of a shore-approach drilling. Without it, routes would hop between
  land and sea too freely.
- **Linear features are charged per cell.** Crossing a road at a right
  angle touches about 1–2 cells, while running along it would charge every
  cell. That is why only major and minor roads are costed, and why minor
  roads have a small weight. Otherwise the dense road network would act
  like a background charge on all land.

## Why a 100 m grid?

- It matches the resolution of the population data (GHSL, 100 m).
- 50 m would have four times as many cells (about 110 million) and much
  longer run times, without better input data.
- The browser version uses 250 m so it can recalculate in seconds. Its
  routes are slightly coarser, which is why the 100 m routes stay on the
  map as the reference.

## Sites and routes

| | |
|---|---|
| **Sources** | 8 emitters and hubs: cement works, power and waste-to-energy plants, CO₂ terminals |
| **Storage sites** | 10, from the Danish Energy Agency's licence and designation areas, onshore and offshore |
| **Delivery routes** | Every source to every storage site (8 × 10 = 80). The cheapest one per source is marked **best** |
| **Network** | All 153 pairs of the 18 sites are routed. The minimum spanning tree picks the 17 links that join everything most cheaply |
| **Snapping** | A site inside a building or barrier is moved to the nearest passable cell within 2 km |

## Why this approach, and the alternatives

| Choice | Why | Alternatives considered |
|---|---|---|
| **Least-cost path on a raster** | Standard for corridor studies: transparent, reproducible, and it reproduces in ArcGIS Pro. Every assumption is a visible weight | *Straight lines × detour factor*: fast, but says nothing about where. *Routing along existing roads or power lines only*: realistic in places, but misses greenfield routes. *Network optimisation (SimCCS)*: sizes pipes and trunk lines, but needs cost data in money and far more effort |
| **Additive weights ("multiplier − 1")** | Matches published multipliers (Kinder Morgan, JRC) and Weißenburger's formula, so weights can be traced to literature | *AHP* (pairwise expert weighting): common in academic studies, but no CO₂ operator was found using it, and the weights are hard to trace to costs. *Multiplicative factors*: they explode where many layers overlap |
| **Highest only within groups** | One piece of land charged once: a bog that is wetland, §3 and Natura 2000 is one obstacle | *Sum everything*: overlapping protection is charged two or three times. Try it with the "let overlapping layers add up" experiment |
| **Barriers only where crossing is truly excluded** | Real projects drill under Natura 2000, roads and rivers; Baltic Pipe did | *Everything protected as a barrier*: long detours, and sometimes no route at all |
| **8-connected moves, √2 diagonals** | The same as ArcGIS Cost Distance; avoids the staircase routes of 4-connected grids | *16-connected (knight's moves)*: smoother lines, slower, and not standard in ArcGIS |
| **100 m grid** | Matches the population data (GHSL 100 m); 28 million cells is feasible | *50 m*: about 4× the cells and run time, without better input data. *250 m* (the browser): fast enough to recalculate interactively |
| **Corridors at 1% and 3%** | Shows how certain a route is: a narrow corridor means one clear best path, a wide one means many near-equal options | *5%*: corridors up to 37,700 km², too wide to read |
| **Minimum spanning tree for the network** | A simple, reproducible picture of which sites naturally connect | *Steiner trees, capacity-optimised trunk lines*: closer to real network design, out of scope |
| **Validation against Baltic Pipe** | The only recent, well-documented transmission pipeline across Denmark | *Evida's planned CO₂ line from Aalborg to Purhus*: a better CO₂ match, once its route is published |

## What the model does **not** do

- No money: weights are relative difficulty, not DKK.
- No terrain slope: Denmark is flat enough that it was left out.
- No landowner negotiations, permits or timing.
- No pipeline sizing, pressure or capacity.
- The network is a single minimum spanning tree, not an optimised trunk
  line with capacities (that is what tools like SimCCS do).
