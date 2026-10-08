# Design decisions and why

These were decided by the project lead on 7–8 October 2026, mostly
following a recommendation from the two AI agents that built the model.
Each entry gives the reason and the alternative that was rejected.

| # | Decision | Why | Alternative not chosen |
|---|---|---|---|
| D1 | Greensand storage is placed at the **Nini A** platform | it is the injection platform named in the project sources | another Nini West coordinate |
| D2 | **Stenlille, Thorning and Bifrost/Harald** added as storage sites | they are official designation and licence areas; leaving them out biased choices towards the rest | the original 4 storage sites only |
| D3 | The network is built from **all pairs** of sites, not only source→storage | emitters can join a nearby hub, which is how real networks grow | links only from sources to storage |
| D4 | Sites show **ETS 2024 emissions and planned capture** | lets you weigh routes by the CO₂ they would carry | location only |
| D6 | Population counts only from **1 person per 100 m cell** (about 100 per km²) | stops sparse countryside acting as a background charge | a cost on every populated cell |
| D7 | Phase A optimisation: **major roads only**, crossing weights by road class, a **discount alongside existing lines**, a **forest** layer, **near buildings** as a safety distance, and protected layers combined by **highest, not sum** | each fixed a distortion seen in the first routes | the first expert weights |
| D8 | Phase B: **open public data** from Danish and EU registers, plus Datafordeler for beach protection and fredskov; **OSM instead of Energinet** for gas and power lines | Energinet's terms forbid redistributing its vector data | Energinet data |
| D10 | **Inez, Lisa and Jammerbugt** added as storage sites (18 sites in total) | they are on the Danish Energy Agency's map of licence and designation areas | 15 sites |
| D11 | The DEA **licence polygons** are shown, not only centre points | storage is an area, and the route ends at its centre | points only |
| D12 | **Recalibrate** the weights to published practice, measured against Baltic Pipe before and after | the first weights were 3–4× higher than industry multipliers | keep the expert weights |
| D13 | Host the app at **co2.michaelbinger.dk** | a stable link for presenting | run it locally |
| D14 | **Drinking-water areas** at 0–0.5 instead of 2–4 | they cover 87% of the land and pushed routes out to sea; the Baltic Pipe fit improved from 19.8 to 13.1 km | P12 without this change |
| D15 | Lauge's changes are calculated **in the browser** at 250 m | instant feedback, no server, works offline | a server running the 100 m Python model (exact, but 5–10 min per run) |
| D16 | A separate **Model settings** panel with tabs and help | ArcGIS-like wording, everything in one place | settings in the layer sidebar, or a wizard |
| D17 | Generic credit to "a master's thesis at KU" | no names or logo without permission | named credit |
| D18 | **English** interface | academic presentation | Danish, or both |
| D19–D20 | Publish the adjustable app when it passes its checks; one AI agent may stand in for the other if it stalls | keep the release moving without the lead relaying messages | waiting for manual prompts |
| D21 | Code under the **MIT** licence | lets students and others reuse and adapt it | GPL (copyleft), no licence |
| D22–D23 | The public repository leaves out internal coordination notes and uses a private author address | server details and work e-mail stay private | publishing everything |
| D24 | Every checked revision goes **live immediately** | the app has one main user who tests each version | batched releases |
| D25 | Source code at **github.com/Autonom664/CO2** | open and citable | private repository |
