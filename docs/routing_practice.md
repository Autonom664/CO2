# How professionals weight pipeline routing, and what it means here

A literature review made on 2026-10-08 to calibrate `config/costs.yaml`.
Sources were opened and read. The Kinder Morgan multipliers (IEAGHG
Table 19) and the JRC terrain factors were re-checked against the source
text; items marked *unverified* or *my understanding* were not.

## Practice in brief

- **Order of work:** constraint mapping, then a cost surface, then
  least-cost paths and corridors.
  - Route-selection principles: avoid people and sensitive ecology, follow
    existing rights-of-way, and avoid difficult crossings
    ([IEAGHG 2014, §7.2.3](https://ieaghg.org/publications/2013-18%20CO2%20Pipeline%20Infrastructure.pdf)).
  - IEAGHG notes that CO2 needs no technically different separation from
    natural gas, but public perception may justify greater separation.
- **CO2 network studies use monetised or multiplicative cost factors**, not
  free 1–10 scores.
  - *SimCCS / CostMAP* builds cost surfaces from slope, land use, land
    ownership, crossings, rights-of-way and population. Linear features are
    **edge costs**: crossing a road is charged, running alongside it is not
    ([SimCCS 2.0](https://www.osti.gov/pages/servlets/purl/1623282);
    [Hoover et al.](https://arxiv.org/abs/1906.08872)).
  - *Weißenburger et al.* compute edge weight = distance × (1 + Σ(fᵢ − 1)).
    Land use is 1–5 and slope 1–4. Protected land and dense population get
    99 (excluded), and existing pipeline corridors get a discount
    ([arXiv 2505.01124](https://arxiv.org/abs/2505.01124)).
  - *JRC EU CO2 network:* onshore 1 (rising with altitude), offshore 2
    ([JRC 2024, Table 2](https://publications.jrc.ec.europa.eu/repository/bitstream/JRC136709/JRC136709_01.pdf)).
- **AHP (pairwise expert weighting)** is common in academic gas-pipeline
  studies (consistency ratio below 0.1, hard constraints as barriers), but no
  CO2 operator was found using it. Operators use cost data plus quantified
  risk assessment.

## Published multipliers

| Factor | Multiplier vs flat dry land | Source |
|---|---|---|
| Flat, dry onshore | 1.0 | Kinder Morgan via [IEAGHG 2014 Table 19](https://ieaghg.org/publications/2013-18%20CO2%20Pipeline%20Infrastructure.pdf) |
| Mountainous | 1.7 | same |
| Marsh / wetland | 2.0 | same |
| High population | 2.0 | same |
| River crossing (per mile of river) | 6.0 | same |
| Offshore vs onshore | 1.4–1.7 | [IPCC SRCCS ch. 4](https://www.ipcc.ch/site/assets/uploads/2018/03/srccs_chapter4-1.pdf) |
| Offshore | 2.0 | [JRC 2024](https://publications.jrc.ec.europa.eu/repository/bitstream/JRC136709/JRC136709_01.pdf) |
| Following an existing corridor | about 0.91 (*unverified*, secondary citation) | van den Broek via [Knoope 2013](https://www.sciencedirect.com/science/article/abs/pii/S175058361300011X) |
| Detour factor (route ÷ straight line) | literature 1.2–1.4; built oil and gas lines IQR 1.05–1.35 | [Weißenburger et al.](https://arxiv.org/abs/2505.01124) |

## CO2 safety distances

- **UK.** PD 8010-1 places dense-phase CO2 in hazard category E and
  requires societal-risk assessment. CO2 risk decays slowly with distance:
  doubling separation from 200 to 400 m only cuts expected casualties to
  about 70% ([Cooper et al., IChemE](https://www.icheme.org/media/11823/hazards-26-poster-18-routeing-of-dense-phase-co2-pipelines-in-the-uk.pdf)).
- **Satartia, US, 2020.** A rupture about 1 mile from the village led to 200
  evacuated and at least 45 hospitalised
  ([PST report](https://pstrust.org/wp-content/uploads/2022/05/PR-5.26.22-Denbury-Failure-Report-FINAL.pdf)).
  PHMSA's 2025 proposed rule uses a 2-mile default for emergency planning.
- **Hazard ranges.** The 5% CO2 envelope from a large rupture can exceed
  1.5 km ([Energies 2021](https://doi.org/10.3390/en14154601)).
- **Denmark.** Evida's gas transmission rules publish easement, risk and
  safety zones (a 2 × 20 m safety zone with no buildings for human
  occupancy, per the review) ([Evida 2025](https://evida.dk/media/3fdb3r1j/uk_pas_paa_gasledningerne2025_lowres.pdf)).
  *Unverified:* the source document has an "easement belts, risk zones and
  safety zones" section, but the 2 × 20 m figure was not found in the text
  checked. No published width was found for CO2 safety zones.

## Danish practice: Baltic Pipe onshore permit

From the [§25 permit](https://sgavmst.dk/media/toudoeuy/baltic-pipe_udkast-25-tilladelse.pdf):
- **Work strip:** 20–42 m wide.
- **Crossings:**
  - Minor roads and small streams were open-cut.
  - Motorways, railways, large watercourses and sensitive nature were
    crossed trenchless (HDD).
  - Several Natura 2000 sites were **crossed by HDD**, not avoided.
- **Avoided:** fredskov (protected forest).
- **Rejected:** running parallel to the E20 motorway and the existing gas
  line, because of development and capacity.

## Implications for this model

1. **Construction-cost classes are too high compared with published
   multipliers.** The additive rule already has the Weißenburger form if
   each score is read as "multiplier − 1". Examples:
   - Wetland is 1 + 7 = 8× here, against 2× in practice.
   - Urban is 9× here, against about 2× for cost alone; safety belongs in a
     separate term.

   Permit-risk classes can stay high: Natura 2000, fredskov, BNBO and §3.
2. **Overlaps double-charge the same land.** Examples: wetland + §3 nature,
   forest + fredskov, urban + population + dwelling proximity. Use max
   groups.
3. **Crossings should be fixed costs, not per-cell costs.** Today a
   crossing is charged on 1–3 cells, more on diagonals.
4. **Safety needs a wider reach.** The 0–200 m proximity term is far
   shorter than CO2 hazard ranges. A population-within-500–1,000 m term is
   closer to practice.
5. **Sea at 2 matches JRC and IPCC**, but there is no fixed landfall
   (shore-crossing) cost.
6. **The ×0.8 discount for following infrastructure is stronger than the
   about ×0.91 in the literature.** Test 0.8, 0.9 and 1.0 in the
   sensitivity runs.
7. **Validation:**
   - report detour factors (now in `validation.check_outputs`)
   - compare with the as-built Baltic Pipe (`validation.baltic_pipe`)
   - use the sensitivity tool (`validation.sensitivity`)
   - add Evida's Aalborg–Purhus CO2 line once its alignment is published
