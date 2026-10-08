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

Every group of weights was varied by −50% and +50%, plus extra runs for
the "alongside lines" discount. For each change, the test records:
- how many sources change their best storage site
- how much of each route stays within 1 km of its baseline

The report is in `build/sensitivity/report.md`, and its summary will be
added here.
