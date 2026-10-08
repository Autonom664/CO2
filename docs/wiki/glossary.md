# Glossary

| Term | Meaning | ArcGIS Pro term |
|---|---|---|
| Accumulated cost | Total cost of the cheapest path from a start cell to each cell | Distance Accumulation / Cost Distance output |
| Analysis area (extent) | Danish land, a 20 km sea buffer and corridors to offshore storage, without foreign land | Mask / processing extent |
| Barrier | Cell that a route may never enter (NoData in the cost raster) | Barriers input; NoData in the cost raster |
| Base cost | Cost of open land (1) or open sea (2) before any layer is added | — |
| BNBO | *Boringsnære beskyttelsesområder*: protection zones close to drinking-water wells | — |
| CCS / CCUS | Carbon capture and storage (and utilisation) | — |
| Corridor (1% / 3%) | All cells whose cheapest path between the two ends costs at most 1% / 3% more than the optimum | Cost Corridor + Con |
| Cost surface | Raster where each cell holds the cost of crossing it | Cost raster (Weighted Sum / Raster Calculator) |
| Dense-phase CO₂ | CO₂ transported as a liquid-like fluid at high pressure; the normal state in pipelines | — |
| Detour factor | Route length ÷ straight-line distance | — |
| Fredskov | Forest protected under the Danish Forest Act | — |
| HDD | Horizontal directional drilling: crossing under a road, river or nature area without digging | — |
| Landfall | Where an offshore pipeline comes ashore | — |
| Least-cost path | The path with the lowest summed cost | Cost Path / Optimal Path As Line |
| MCP | Minimum cost path; here `MCP_Geometric` from scikit-image | Cost Distance |
| Minimum spanning tree (network) | Cheapest set of links that joins all sites without loops | Optimal Region Connections |
| Natura 2000 | EU network of protected habitat and bird sites | — |
| OD / OSD | *Områder med drikkevandsinteresser* / *særlige drikkevandsinteresser*: areas with (special) drinking-water interests | — |
| Open-cut | Laying a pipe in a dug trench | — |
| Snapping | Moving a site to the nearest passable cell | Snap Pour Point (similar idea) |
| §3 nature | Habitats protected under §3 of the Danish Nature Protection Act | — |
| Weight | Extra cost a layer adds on top of the base cost; weight 1 = twice as expensive as open land | Cost raster value − 1 |
| 8-connected | Each cell has 8 neighbours (diagonals included); diagonal steps count √2 | Default in Cost Distance |
