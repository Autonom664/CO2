# Frequently asked questions

**Why does a route go out to sea and back?**
Sea costs 2 per cell and land costs 1 plus whatever layers cover it, so
the route takes the sea wherever land is busier than ×2. Hover over the
land next to the route ("Explain cost under the mouse") to see what makes
it expensive. To test it, raise the sea base cost in Model settings →
Model, or try the "Make the sea three times as expensive" experiment.

**Why was my site moved?**
A site inside a building, a barrier or outside the analysis area is moved
("snapped") to the nearest passable cell within 2 km. If none is found,
the site is left out and the results say so. The snapped position is where
the route actually starts.

**Why do my browser results differ slightly from the published routes?**
- The browser recalculates on a **250 m** grid; the published routes use
  **100 m**.
- Narrow features (a stream, a small road, one house) can disappear or
  grow when 100 m cells are combined into 250 m cells.
- The route choices and costs are close, but the lines can shift by a cell
  or two.
- Use the browser to explore, and the published 100 m model (or ArcGIS
  Pro) for final figures.

**Why is a whole area blocked?**
It is a barrier: buildings (a 250 m cell is blocked when half or more of it
is built over), wellhead protection zones (BNBO), protected monuments,
operating wind farms or munitions dumps. Hover to see which. In Layers &
weights you can turn any barrier into a cost.

**Why does a weight of 10 not stop the route?**
A high weight makes crossing expensive, but a long detour can cost even
more. That is intended, because real pipelines are drilled under obstacles
rather than routed around them at any cost. Use *Barrier* if crossing
must never happen.

**Can I change the 1 km safety radius, or the 50–300 m band along power lines?**
Not in the browser: those distances were calculated in advance, when the
model data was built. You can change their **weights** and thresholds.
Changing the distances needs the Python pipeline (`config/costs.yaml`,
then `src.cost_surface` and `src.export_model`) or your own ArcGIS model.

**Why does the network not follow the delivery routes?**
The two answer different questions:
- The **delivery routes** are the cheapest path from each source to each
  storage site.
- The **network** is the cheapest set of links that joins *all* sites,
  including source-to-source links. A source may join the network through
  a neighbouring emitter instead of going straight to storage.

**What does "best" mean in the route list?**
The storage site with the lowest accumulated cost from that source. It is
not necessarily the shortest, and it ignores storage capacity, injection
cost and licence status.

**How reliable is a route?**
- The **choice of storage site** is robust: in 24 sensitivity runs, at
  most 1 of 8 sources changed its best site.
- The **exact line** is less certain. It depends mainly on the sea cost
  and the safety distance. See [validation.md](validation.md).
- Treat a route as a corridor of possibilities. The 1% and 3% corridors on
  the map show how wide that corridor is.

**Can I use this in my thesis?**
Yes:
- The code is MIT-licensed, and the data keeps its own licences
  ([sources.md](sources.md)). Cite it using `CITATION.cff` in the
  repository.
- Routes derived from OpenStreetMap are © OpenStreetMap contributors
  (ODbL).
- The weights are assumptions. Say which ones you used, ideally as a saved
  scenario file.
