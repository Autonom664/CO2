# Model validation

## Baltic Pipe

`baltic_pipe_osm.geojson` is the Danish part of the as-built Baltic Pipe gas
pipeline: from the North Sea landfall near Blåbjerg (8.17321 E, 55.76001 N) to
the Baltic landfall near Faxe (12.11993 E, 55.18851 N), including the Little
Belt and Great Belt crossings. It is 299.6 km long.

**What the reference contains:**
- Five OSM ways tagged "Baltic Pipe" (relation 14592851), 193.7 km in total.
- Untagged Energinet / 1000 mm gas ways that connect to them end to end. These
  fill the west Jutland section (landfall → Nybro → Egtved) and the Great
  Belt crossing, which OSM does not tag.

The filled sections were matched by shared endpoints and pipe diameter, not
by an explicit tag. Short gaps of up to about 380 m at compressor and metering
stations are not bridged. The OSM way IDs are stored on the feature.

Source: © OpenStreetMap contributors, available under the Open Database
License (ODbL) 1.0. Extracted on 2026-10-07 from Geofabrik's
`denmark-latest.osm.pbf`. This file is a derived database and is shared
under the same licence.

Run after the cost surface exists:

```powershell
python -m validation.baltic_pipe
```

It routes a least-cost path between the two landfalls with the current cost
surface and writes:
- `baltic_pipe_report.json`: offsets in km, length ratio, and the share of the
  real pipeline inside the 5% corridor
- `baltic_pipe_model.geojson`: the modelled route

Re-run it after changing the cost weights to see whether the change moved the
model closer to how this pipeline was actually built.

## Adjustable browser model

After the 250 m browser model pack exists, run:

```powershell
python -m validation.model_parity --verbose
```

This validates the model-pack hashes, writes the default and two perturbed
250 m cost grids under `validation/model_parity/`, and records source-to-
storage route lengths and accumulated costs in `model_parity.json`. The
formula and the browser comparison tolerance are specified in
[`docs/model_formula.md`](../docs/model_formula.md). Browser parity is not
considered verified until all cells and route costs meet the documented
0.5% tolerance with identical traversability.
