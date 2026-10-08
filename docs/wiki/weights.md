# Weights: what each layer costs, and why

A weight is the extra cost a cell adds on top of open land. Open land
costs 1, so:

| Weight | The cell costs | Meaning |
|---|---|---|
| 0 | 1× | no extra difficulty |
| 1 | 2× | twice as hard as open land |
| 4 | 5× | five times as hard |
| 10 | 11× | strongly avoided, but still crossable |
| Barrier | — | never crossed, whatever the detour |

"Published practice" below comes from cost multipliers used in industry
and research:
- IEAGHG 2014, quoting Kinder Morgan's CO₂ pipeline costs
- the IPCC report on CO₂ capture and storage
- the EU JRC CO₂ network study
- Weißenburger et al. 2025

A multiplier of ×2 corresponds to a weight of 1. Full references are in
`docs/routing_practice.md` in the repository.

## The two calibration rounds

1. **Initial weights (7 October)** were expert guesses on a 1–10 scale.
   They made many things 7–9× harder than open land.
2. **Recalibration (8 October, decisions D12 and D14).** Construction-cost
   layers were set to published multipliers, and overlapping layers stopped
   adding up. Permit-risk layers (Natura 2000, §3, fredskov, monuments) were
   kept high, because they are about permits rather than construction cost.

| Measure against the real Baltic Pipe | Before | After |
|---|---|---|
| Median distance from the real route | 19.8 km | 13.1 km |
| Model length compared with the real 299.6 km | +10% | +3.5% |

## Base costs

| Setting | Weight | Why |
|---|---|---|
| Open land | 1 (base) | the reference everything else is compared with |
| Open sea | 2 (base) | offshore pipelines cost 1.4–2× onshore (IPCC, JRC) |
| Landfall | +10 | stands in for a shore-approach drilling (HDD), about 1.5 km of open land |
| Alongside existing lines | ×0.9 | sharing a corridor saves about 9% (van den Broek, via Knoope 2013) |

## Infrastructure

| Layer | Weight | Why |
|---|---|---|
| Major roads | 5 | crossed by drilling (HDD); one crossing costs about as much as 0.75 km of open land |
| Minor roads | 0.5 | open-cut; small. Higher values made the dense road network a background charge |
| Railways | 5 | crossed by drilling |

## Water

| Layer | Weight | Why |
|---|---|---|
| Streams and rivers | 1 | small streams are open-cut; large rivers would deserve more |
| Lakes | 7 | avoided in practice |
| Wetlands | 1 | soft ground: marsh ×2 (Kinder Morgan) |
| Lake and stream protection lines | 5 | statutory zones; permits needed |

## Protected nature (permit risk)

| Layer | Weight | Why |
|---|---|---|
| Natura 2000 (habitat and bird sites) | 9 | EU protection; crossed only by drilling, with an impact assessment |
| §3 nature and reserves | 8 | protected habitats and conservation orders |

Wetland, §3 and Natura 2000 are in the **wet_nature** group, so a cell
takes the highest of the three, not their sum.

## Land use and forest

| Layer | Weight | Why |
|---|---|---|
| Forest (OSM) | 0.5 | clearing cost; ×1.3–2 in the literature |
| Protected forest (fredskov) | 7 | avoided in the Baltic Pipe permit |
| Urban areas | 1 | construction cost only; safety is a separate term |

Forest and fredskov are in the **forest_group** (highest only).

## People and CO₂ safety

| Setting | Value | Why |
|---|---|---|
| Near buildings | up to 6, falling to 0 at 200 m | near-field safety and construction space |
| Population density | 0–1, by quantile, above 1 person per cell | populated areas about ×2 (Kinder Morgan) |
| CO₂ safety: people within 1 km | 0–5, by quantile, above 50 people | dense-phase CO₂ releases can reach well over 1 km (Satartia, USA, 2020); UK practice assesses societal risk |
| Buildings | barrier | no pipeline through houses |

All four are in the **people** group (highest only). The CO₂ safety term
is the main reason the model avoids villages that the real Baltic Pipe
passed. See `experiments.md` for how to test that.

## Groundwater (decision D14)

| Layer | Weight | Why |
|---|---|---|
| Drinking-water areas (OD) | 0 | they cover most of Denmark; any weight made land dearer than sea |
| Special drinking-water areas (OSD) | 0.5 | crossed in practice; CO₂ doesn't pollute groundwater |
| Groundwater catchments | 0.5 | as above |
| Wellhead protection zones (BNBO) | barrier | close to drinking-water wells |

## Heritage, soil and coast

| Layer | Weight | Why |
|---|---|---|
| Ancient monuments | barrier | scheduled monuments must not be disturbed |
| Monument protection zones (100 m) | 5 | statutory zones |
| Contaminated land V2 / V1 | 6 / 3 | soil handling and disposal |
| Beach protection zone | 7 | strict coastal restrictions |

## Sea use

| Layer | Weight | Why |
|---|---|---|
| Shipping zones | 6 | anchoring and fishing risk, burial depth |
| Renewable-energy zones | 8 | reserved for offshore energy |
| Raw-material and nature zones | 6 | extraction and marine nature |
| Cable corridors | −1 | a discount: planned corridors suit linear infrastructure |
| Planned offshore wind | 7 | conflicts with future turbines and cables |
| Operating or approved wind farms | barrier | |
| Munitions dump areas | barrier | |
| Munitions finds (500 m) | 8 | survey and clearance needed |
| Subsea pipelines / cables | 4 / 5 | each crossing needs a crossing design |

## Questions worth asking about any weight

1. **How much of the area does the layer cover?** A weight on a layer that
   covers half the country changes everything. On a rare layer it changes
   only local detours. The legend shows each layer; the Layers tab lets
   you switch it off.
2. **Is it a construction cost or a permit risk?** Construction costs have
   published multipliers. Permit risks are judgement calls, and good
   candidates for sensitivity tests.
3. **Would a real project cross it, or go around?** If it would cross
   (by drilling), use a high cost, not a barrier.
