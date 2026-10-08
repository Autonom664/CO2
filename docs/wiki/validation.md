# Validation: does the model find realistic routes?

## Benchmark: Baltic Pipe

Baltic Pipe is a gas pipeline built across Denmark in 2020–2022, from the
North Sea landfall at Blåbjerg to Faxe on Zealand. It is the best
available real example of a modern Danish transmission pipeline route.
Its as-built route comes from OpenStreetMap (10 ways, 299.6 km).

**The test:**
1. Route the model between the real endpoints.
2. Compare the result with the real line: length, distance between the
   lines, and how much of the real line lies inside the model's
   near-optimal corridors.
3. For this test, the "alongside existing lines" discount ignores Baltic
   Pipe itself. Otherwise the model would be rewarded for following the
   answer.

## Results

| Measure | Initial weights | Recalibrated, without D14 | Recalibrated (in use) |
|---|---|---|---|
| Model length vs 299.6 km | +10% | +9% | **+3.5%** |
| Median distance between the lines | 19.8 km | 18.8 km | **13.1 km** |
| 90th percentile distance | 39.8 km | 36.9 km | **32.0 km** |
| Real route inside the 3% corridor | 37% | 42% | **45%** |

**How to read it:**
- The length is now realistic.
- The model still crosses Jutland and Funen 20–30 km further north than
  the real line. The CO₂ safety term (1 km from people) avoids villages
  that the real gas pipeline passed. A CO₂ pipeline would probably be
  routed more cautiously than a gas pipeline, so part of this difference
  is intended.
- Real routes also depend on landowners, existing easements and
  construction logistics, which no open dataset captures.

## Other checks

| Check | Result |
|---|---|
| Every source has a route to every storage site | 80 / 80 |
| The network joins all 18 sites | 17 links, no cycles |
| No route crosses a barrier or foreign land | pass |
| Detour factor (route length ÷ straight line) | median 1.27, max 1.55; built pipelines are typically 1.05–1.35 |
| Browser engine vs the Python routing | identical to 9 decimal places on test grids |

## Sensitivity

Every group of weights was multiplied by 0.5 and by 1.5 (24 runs of the
full 100 m model, about 2.5 hours). For each run, two things were
compared with the published model:
- whether each source's **best storage site** changed
- how much of each **route** stays within 1 km of the published one

| Group changed | Best storage changed (×0.5 / ×1.5) | Route within 1 km (×0.5 / ×1.5) |
|---|---|---|
| **Sea base cost** | 1 / 0 of 8 | **80% / 57%** |
| **CO₂ safety (people within 1 km)** | 0 / 0 | **63% / 89%** |
| Water (streams, lakes, wetlands, protection lines) | 0 / 0 | 100% / 76% |
| Protected nature (Natura 2000, §3) | 1 / 0 | 77% / 98% |
| Forest and fredskov | 0 / 0 | 87% / 100% |
| Urban, population, near buildings | 0 / 0 | 92% / 100% |
| Groundwater and drinking water | 0 / 0 | 100% / 92% |
| Marine uses | 0 / 0 | 100% / 95% |
| Landfall | 0 / 0 | 98% / 100% |
| Roads and railways | 0 / 0 | 100% / 100% |
| Heritage, soil and coast | 0 / 0 | 98% / 100% |
| Alongside-lines discount (×1.0 = off / ×0.8) | 0 / 0 | 98% / 91% |

**What it means:**
- **The choice of storage site is robust.** No change of ±50% to any
  group moved more than one of the eight sources to a different storage
  site. Conclusions such as "Aalborg Portland → Gassum" don't hinge on a
  single weight.
- **The exact route depends mainly on two choices:** how expensive sea is
  compared with land, and how strongly the model keeps away from people.
  With the sea 50% more expensive, routes overlap the published ones by
  only 57%. Halving the CO₂ safety term gives 63%. These are the
  assumptions to justify most carefully in a thesis, and good candidates
  for scenarios.
- **Roads, railways, heritage and marine uses barely matter at these
  weights.** That doesn't make them unimportant; it means their crossings
  are rarely avoidable or rarely on the way.

The full table, with route-level detail per source, comes from
`validation/sensitivity.py`. You can repeat any row in the app: Model
settings → change the group's weights by the same factor → Run.
