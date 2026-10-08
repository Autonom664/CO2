# References

The literature behind the method and the weights. Datasets are listed
separately in [sources.md](sources.md). Each entry says what it was used
for. Items marked *unverified* could not be checked against the primary
text.

## CO₂ pipeline cost and routing practice

| Reference | Used for |
|---|---|
| IEAGHG (2014). *CO₂ Pipeline Infrastructure*, report 2013/18. [PDF](https://ieaghg.org/publications/2013-18%20CO2%20Pipeline%20Infrastructure.pdf) | Route-selection principles (§7.2.3); Kinder Morgan cost multipliers in Table 19: flat dry land 1.0, mountainous 1.7, marsh/wetland 2.0, high population 2.0, river crossing 6.0 per mile of river. The source of the wetland, urban and population weights |
| IPCC (2005). *Special Report on Carbon Dioxide Capture and Storage*, chapter 4: Transport. [PDF](https://www.ipcc.ch/site/assets/uploads/2018/03/srccs_chapter4-1.pdf) | Offshore pipelines cost 1.4–1.7× onshore; supports the sea base cost of 2 |
| European Commission JRC (2024). *EU CO₂ transport network study*, Table 2. [PDF](https://publications.jrc.ec.europa.eu/repository/bitstream/JRC136709/JRC136709_01.pdf) | Terrain factors: onshore 1 (rising with altitude), offshore 2. Supports the sea base cost |
| Weißenburger et al. (2025). Least-cost CO₂ network routing. [arXiv:2505.01124](https://arxiv.org/abs/2505.01124) | Edge weight = distance × (1 + Σ(fᵢ − 1)), the additive form used here; land use 1–5, slope 1–4, excluded classes at 99; detour factors of built oil and gas lines (IQR 1.05–1.35) |
| Middleton et al., SimCCS 2.0. [OSTI](https://www.osti.gov/pages/servlets/purl/1623282); Hoover et al., CostMAP. [arXiv:1906.08872](https://arxiv.org/abs/1906.08872) | Cost surfaces from slope, land use, ownership, crossings and population; linear features as **edge costs** (crossing charged, running alongside not). Why roads are charged per crossing cell and why the alongside-lines discount exists |
| Knoope et al. (2013), quoting van den Broek. [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S175058361300011X) | About 9% saving when following an existing corridor (× 0.91). *Unverified*: a secondary citation |

## CO₂ safety distances

| Reference | Used for |
|---|---|
| Cooper et al. Routeing of dense-phase CO₂ pipelines in the UK. IChemE Hazards 26. [PDF](https://www.icheme.org/media/11823/hazards-26-poster-18-routeing-of-dense-phase-co2-pipelines-in-the-uk.pdf) | UK PD 8010-1 puts dense-phase CO₂ in hazard category E; risk falls slowly with distance (doubling separation from 200 to 400 m cuts expected casualties to only about 70%). Why there is a 1 km safety term and not just 200 m |
| Pipeline Safety Trust (2022). Denbury Satartia failure report. [PDF](https://pstrust.org/wp-content/uploads/2022/05/PR-5.26.22-Denbury-Failure-Report-FINAL.pdf) | Satartia, Mississippi, 2020: a rupture about 1 mile from the village led to about 200 evacuated and at least 45 hospitalised |
| Energies (2021), dispersion of CO₂ from large releases. [doi:10.3390/en14154601](https://doi.org/10.3390/en14154601) | The 5% CO₂ envelope from a large rupture can exceed 1.5 km |
| PHMSA (2025). Proposed CO₂ pipeline rule | A 2-mile default for emergency planning; context for the safety term |
| Evida (2025). *Pas på gasledningerne*. [PDF](https://evida.dk/media/3fdb3r1j/uk_pas_paa_gasledningerne2025_lowres.pdf) | Danish gas-transmission easement, risk and safety zones. *Unverified*: the 2 × 20 m figure was not found in the text |

## Danish practice

| Reference | Used for |
|---|---|
| Danish Environmental Protection Agency. Baltic Pipe §25 permit (draft). [PDF](https://sgavmst.dk/media/toudoeuy/baltic-pipe_udkast-25-tilladelse.pdf) | Work strip 20–42 m; minor roads and small streams open-cut; motorways, railways, large watercourses and sensitive nature crossed by HDD; several Natura 2000 sites **crossed by HDD**, not avoided; fredskov avoided; parallel to the E20 and the existing gas line rejected. Behind the HDD-based crossing weights and the "Natura 2000 as a cost, not a barrier" choice |
| OpenStreetMap: Baltic Pipe ways (10 ways, 299.6 km) | The as-built benchmark route; see [validation.md](validation.md) |

## Algorithms

| Reference | Used for |
|---|---|
| van der Walt et al. (2014). scikit-image: image processing in Python. *PeerJ* 2:e453. `skimage.graph.MCP_Geometric` | Least-cost paths: 8-connected, a step costs the mean of the two cells × the step length |
| Dijkstra, E. W. (1959). A note on two problems in connexion with graphs. *Numerische Mathematik* 1, 269–271 | The shortest-path algorithm behind MCP and the browser engine |
| Prim, R. C. (1957). Shortest connection networks and some generalizations. *Bell System Technical Journal* 36(6) | The minimum spanning tree that joins all sites |
| Esri. *How Cost Distance works* (ArcGIS Pro documentation) | The same cell-to-cell cost rule, for rebuilding in ArcGIS Pro ([arcgis_recipe.md](arcgis_recipe.md)) |
| Karney, C. F. F. (2011). Transverse Mercator with an accuracy of a few nanometers. *J. Geodesy* 85, 475–485 | The UTM conversion in the browser engine |
