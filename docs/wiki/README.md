# CO₂ pipeline routing in Denmark: the wiki

Built to support a master's thesis on CO₂ capture and transport at the
University of Copenhagen (KU).

This wiki explains **what** the map shows, **why** each choice was made,
and **how to rebuild it yourself**, for example in ArcGIS Pro. Every
weight and layer in the app can be changed in **Model settings**. Change
things, run, and see what moves. That is the fastest way to learn what
drives a route.

## Pages

| Page | What you find there |
|---|---|
| [method.md](method.md) | How least-cost routing works, and why it was set up this way |
| [weights.md](weights.md) | Every layer and weight: what it means, why this value, what practice says |
| [sources.md](sources.md) | Every dataset: publisher, licence, link, and known quirks |
| [data_preparation.md](data_preparation.md) | How the raw data was turned into the cost surface |
| [arcgis_recipe.md](arcgis_recipe.md) | Rebuild this in ArcGIS Pro, tool by tool |
| [experiments.md](experiments.md) | Things to try in the app, and what to look for |
| [decisions.md](decisions.md) | Every design decision (D1–D25) with its reason |
| [validation.md](validation.md) | How the model was checked against the real Baltic Pipe |
| [history.md](history.md) | How the model evolved through five versions, and what each change did |
| [references.md](references.md) | The literature behind every weight and method choice |
| [faq.md](faq.md) | Common questions: sea detours, snapping, browser vs published routes |
| [glossary.md](glossary.md) | Terms, with their ArcGIS Pro equivalents |

## Five things worth knowing first

1. **The weights are assumptions, not prices.** A weight says "crossing
   this is so many times harder than open land". The published defaults
   follow industry multipliers where they exist (`weights.md`), but they
   are a starting point for your own judgement.
2. **Routes are sensitive to what covers most of the country.** A small
   weight on a layer that covers 87% of the land (drinking-water areas)
   changed the routes more than a large weight on a rare layer. Look at
   coverage, not only at the weight.
3. **Barriers and costs behave differently.** A barrier forces a detour
   at any price. A high cost lets the route cross when the detour would
   be even more expensive. Real projects cross Natura 2000 by drilling,
   so modelling it as a barrier is stricter than practice.
4. **Sea against land is the biggest single choice.** The ratio of the
   sea base cost to the land base cost decides whether routes hug the
   coast or cross the country.
5. **The model was checked against a real pipeline.** Baltic Pipe's
   as-built route is the benchmark (`validation.md`). After calibration,
   the model is 3.5% longer than the real line, and its median distance
   from it is 13 km.
