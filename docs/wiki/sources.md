# Data sources

This page inventories the datasets prepared for the routing model. The
authoritative project register is [`data/SOURCES.md`](../../data/SOURCES.md);
it also records the exact service URL for each DEA storage polygon, the
hotspot/project-metadata references, and the acquisition manifest location.
Raw downloads are kept in the git-ignored `data/raw/` folder.

## Spatial datasets

| Dataset | Publisher | Source | Licence / terms | CRS: source → prepared | Fetched |
|---|---|---|---|---|---|
| Denmark extract boundary (`denmark.poly`) | OpenStreetMap contributors; Geofabrik | [Geofabrik boundary](https://download.geofabrik.de/europe/denmark.poly) | ODbL 1.0; attribution required | EPSG:4326 → used to define the boundary | 2026-10-07 |
| OSM roads, railways, buildings, land use, water and forest (Denmark GeoPackage) | OpenStreetMap contributors; Geofabrik | [Denmark GeoPackage archive](https://download.geofabrik.de/europe/denmark-latest-free.gpkg.zip) | ODbL 1.0; attribution required | EPSG:4326 → EPSG:25832 | 2026-10-07 |
| OSM high-voltage power lines and gas pipelines (PBF) | OpenStreetMap contributors; Geofabrik | [Denmark PBF](https://download.geofabrik.de/europe/denmark-latest.osm.pbf) | ODbL 1.0; attribution required | EPSG:4326 → EPSG:25832 | 2026-10-07 |
| Coastline-derived land polygons | OpenStreetMap contributors; osmdata.openstreetmap.de | [Split land polygons](https://osmdata.openstreetmap.de/download/land-polygons-split-4326.zip) | ODbL 1.0; attribution required | EPSG:4326 → EPSG:25832 | 2026-10-07 |
| Natura 2000, Habitats Directive (end-2024 version) | European Environment Agency | [Layer 0 query](https://bio.discomap.eea.europa.eu/arcgis/rest/services/ProtectedSites/Natura2000Sites/MapServer/0/query); [dataset metadata](https://sdi.eea.europa.eu/catalogue/datahub/api/records/91357f39-7866-41ce-b447-43905c364ec8) | EEA reuse terms; attribution required; see metadata | EPSG:3035 product → EPSG:25832 query output | 2026-10-07 |
| Natura 2000, Birds Directive (end-2024 version) | European Environment Agency | [Layer 1 query](https://bio.discomap.eea.europa.eu/arcgis/rest/services/ProtectedSites/Natura2000Sites/MapServer/1/query); [dataset metadata](https://sdi.eea.europa.eu/catalogue/datahub/api/records/91357f39-7866-41ce-b447-43905c364ec8) | EEA reuse terms; attribution required; see metadata | EPSG:3035 product → EPSG:25832 query output | 2026-10-07 |
| Protected nature types (§3) | Danmarks Miljøportal | [Dataset page](https://arealdata-api.miljoeportal.dk/datasets/urn:dmp:ds:beskyttede-naturtyper) | CC0 1.0 | EPSG:25832 → EPSG:25832 | 2026-10-07 |
| Protected reserves (fredede områder) | Danmarks Miljøportal | [Dataset page](https://arealdata-api.miljoeportal.dk/datasets/urn:dmp:ds:fredede-omraader) | CC0 1.0 | EPSG:25832 → EPSG:25832 | 2026-10-07 |
| GHS-POP R2023A, epoch 2020, 100 m | European Commission Joint Research Centre | [GHS-POP archive](https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/GHS_POP_GLOBE_R2023A/GHS_POP_E2020_GLOBE_R2023A_54009_100/V1-0/GHS_POP_E2020_GLOBE_R2023A_54009_100_V1_0.zip) | European Commission reuse notice; source acknowledgement required | ESRI:54009 → EPSG:25832, 100 m | 2026-10-07 |
| Drinking-water interests (OSD and OD; `grukos:drikkevandsinteresser`) | Danish Environmental Protection Agency | [GRUKOS WFS capabilities](https://wfs2-miljoegis.mim.dk/grukos/ows?service=WFS&request=GetCapabilities) | CC0 1.0 | EPSG:25832 → EPSG:25832 | 2026-10-08 |
| BNBO groundwater protection areas (`grukos:bnbo`) | Danish Environmental Protection Agency | [GRUKOS WFS capabilities](https://wfs2-miljoegis.mim.dk/grukos/ows?service=WFS&request=GetCapabilities) | CC0 1.0 | EPSG:25832 → EPSG:25832 | 2026-10-08 |
| Groundwater abstraction catchments (`grukos:indvindingsoplande_alle`) | Danish Environmental Protection Agency | [GRUKOS WFS capabilities](https://wfs2-miljoegis.mim.dk/grukos/ows?service=WFS&request=GetCapabilities) | CC0 1.0 | EPSG:25832 → EPSG:25832 | 2026-10-08 |
| Protected ancient monuments (area, line and point layers) | Danish Agency for Culture and Palaces | [Agency WFS capabilities](https://www.kulturarv.dk/ffgeoserver/public/wfs?service=WFS&request=GetCapabilities) | CC0 1.0 | EPSG:25832 → EPSG:25832 | 2026-10-08 |
| Ancient-monument protection zones | Danish Agency for Culture and Palaces | [Agency WFS capabilities](https://www.kulturarv.dk/ffgeoserver/public/wfs?service=WFS&request=GetCapabilities) | CC0 1.0 | EPSG:25832 → EPSG:25832 | 2026-10-08 |
| Lake and stream protection lines | Danmarks Miljøportal | [Miljøportal WFS capabilities](https://arealeditering-dist-geo.miljoeportal.dk/geoserver/wfs?service=WFS&request=GetCapabilities) | CC0 1.0 | EPSG:25832 → EPSG:25832 | 2026-10-08 |
| Contaminated land, V1 and V2 | Danmarks Miljøportal (DKJord) | [DKJord WFS capabilities](https://jord.miljoeportal.dk/geo/wfs?service=WFS&request=GetCapabilities) | CC0 1.0 | EPSG:25832 → EPSG:25832 | 2026-10-08 |
| Denmark's maritime spatial-plan zones (2024-06-28) | Danish Maritime Authority | [Havplan WFS capabilities](https://havplan.dk/geoserver/havplan/wfs?service=WFS&request=GetCapabilities) | CC BY 4.0 | EPSG:25832 → EPSG:25832 | 2026-10-08 |
| Offshore wind farms | EMODnet Human Activities | [EMODnet WFS capabilities](https://ows.emodnet-humanactivities.eu/wfs?service=WFS&request=GetCapabilities) | CC BY 4.0 | EPSG:4326 → EPSG:25832 | 2026-10-08 |
| Dumped-munitions areas and points | EMODnet Human Activities | [EMODnet WFS capabilities](https://ows.emodnet-humanactivities.eu/wfs?service=WFS&request=GetCapabilities) | CC BY 4.0 | EPSG:4326 → EPSG:25832; point locations buffered 500 m | 2026-10-08 |
| Subsea pipelines and cables | EMODnet Human Activities | [EMODnet WFS capabilities](https://ows.emodnet-humanactivities.eu/wfs?service=WFS&request=GetCapabilities) | CC BY 4.0 | EPSG:4326 → EPSG:25832 | 2026-10-08 |
| Beach-protection areas and protected forest (`fredskov`) | Klimadatastyrelsen, Datafordeler | [MATRIKLEN WFS capabilities](https://wfs.datafordeler.dk/MATRIKLEN2/MatGaeldendeOgForeloebigWFS/1.0.0/WFS?service=WFS&request=GetCapabilities) | CC BY 4.0 | EPSG:25832 → EPSG:25832 | 2026-10-08 |
| DEA storage area: Gassum | Danish Energy Agency | [FeatureServer](https://services3.arcgis.com/VfNcCOxfWppwD8Xh/arcgis/rest/services/C2024_01/FeatureServer/0) | No licence stated; attribute to the Danish Energy Agency's CO₂ storage licensing map | EPSG:4326 → EPSG:4326 | 2026-10-08 |
| DEA storage area: Havnsø | Danish Energy Agency | [FeatureServer](https://services3.arcgis.com/VfNcCOxfWppwD8Xh/arcgis/rest/services/C2024_03/FeatureServer/0) | No licence stated; attribute to the Danish Energy Agency's CO₂ storage licensing map | EPSG:4326 → EPSG:4326 | 2026-10-08 |
| DEA storage area: Rødby | Danish Energy Agency | [FeatureServer](https://services3.arcgis.com/VfNcCOxfWppwD8Xh/arcgis/rest/services/C2024_02/FeatureServer/0) | No licence stated; attribute to the Danish Energy Agency's CO₂ storage licensing map | EPSG:4326 → EPSG:4326 | 2026-10-08 |
| DEA storage area: Stenlille | Danish Energy Agency | [FeatureServer](https://services3.arcgis.com/VfNcCOxfWppwD8Xh/arcgis/rest/services/Stenlille_UU/FeatureServer/0) | No licence stated; attribute to the Danish Energy Agency's CO₂ storage licensing map | EPSG:4326 → EPSG:4326 | 2026-10-08 |
| DEA storage area: Thorning | Danish Energy Agency | [ArcGIS item data](https://www.arcgis.com/sharing/rest/content/items/0590b16f4105478ab34dbd136e0b25e2/data) | No licence stated; attribute to the Danish Energy Agency's CO₂ storage licensing map | EPSG:4326 → EPSG:4326 | 2026-10-08 |
| DEA storage area: Nini West | Danish Energy Agency | [FeatureServer](https://services3.arcgis.com/VfNcCOxfWppwD8Xh/arcgis/rest/services/Nini_West_storage_permit/FeatureServer/0) | No licence stated; attribute to the Danish Energy Agency's CO₂ storage licensing map | EPSG:4326 → EPSG:4326 | 2026-10-08 |
| DEA storage area: Bifrost | Danish Energy Agency | [FeatureServer](https://services3.arcgis.com/VfNcCOxfWppwD8Xh/arcgis/rest/services/TotalEnergiesED50UTM32/FeatureServer/0) | No licence stated; attribute to the Danish Energy Agency's CO₂ storage licensing map | EPSG:4326 → EPSG:4326 | 2026-10-08 |
| DEA storage area: Inez | Danish Energy Agency | [FeatureServer](https://services3.arcgis.com/VfNcCOxfWppwD8Xh/arcgis/rest/services/inez_subsurface_designation/FeatureServer/0) | No licence stated; attribute to the Danish Energy Agency's CO₂ storage licensing map | EPSG:4326 → EPSG:4326 | 2026-10-08 |
| DEA storage area: Lisa | Danish Energy Agency | [FeatureServer](https://services3.arcgis.com/VfNcCOxfWppwD8Xh/arcgis/rest/services/Lisa_subsurface_designation/FeatureServer/0) | No licence stated; attribute to the Danish Energy Agency's CO₂ storage licensing map | EPSG:4326 → EPSG:4326 | 2026-10-08 |
| DEA storage area: Jammerbugt | Danish Energy Agency | [FeatureServer](https://services3.arcgis.com/VfNcCOxfWppwD8Xh/arcgis/rest/services/Jammerbugt_subsurface_designation/FeatureServer/0) | No licence stated; attribute to the Danish Energy Agency's CO₂ storage licensing map | EPSG:4326 → EPSG:4326 | 2026-10-08 |
| OSM standard-tile basemap (runtime only) | OpenStreetMap contributors | [Tile service](https://tile.openstreetmap.org/{z}/{x}/{y}.png) | OSM tile policy; visible attribution, caching rules, no bulk download | EPSG:3857 | Not downloaded |

## Hotspot and project metadata

The 18 locations in [`data/input/hotspots.csv`](../../data/input/hotspots.csv)
are candidate routing anchors, not surveyed endpoints or confirmation of a
commercial storage permit. They are in WGS84 (EPSG:4326). The project sources,
licence caveats, and URLs for storage-area polygons and project information
are itemized in [`data/SOURCES.md`](../../data/SOURCES.md).

## Known quirks and rejected alternatives

- A Datafordeler `fredskov` request once returned HTTP 401; retrying five
  seconds later succeeded. The downloader uses paged requests and retry logic.
- The available Datafordeler key returned HTTP 401 for the
  GeoDanmark WFS. That vector service was therefore not used; OSM sources were
  used for the current roads, buildings, land-use and infrastructure layers.
- Some downloaded geometries are invalid. Preparation repairs them with
  `make_valid` before clipping and intersection; failures are surfaced rather
  than silently retained.
- A phase-B WFS page contained case-insensitive duplicate field names (for
  example `Id` and `ID`). The GeoPackage writer renames collisions before
  writing (`Id_2`, etc.). This avoids losing or overwriting attributes.
- The current §3 and fredede inputs are the Miljøportal dataset downloads;
  the project did not substitute an unverified WFS response for them.
- OSM coastline data and the Geofabrik country boundary are approximations,
  not legal maritime or national borders. A narrow strip can remain near the
  Denmark boundary; foreign waters are intentionally available for routing.

## Source choices, limits, and ArcGIS Pro access

The source register above remains the authoritative list of download dates,
licences, and exact URLs. Use it alongside this summary when reproducing the
model. The project uses these sources because they provide open, documented
coverage for the study area; a source not selected here should not be assumed
to be unavailable.
Alternatives named below are those recorded in the source decisions; for the
other WFS themes, the named official publisher layer was selected and no
competing dataset was evaluated.

### OSM infrastructure and coastline

- **Why selected:** Geofabrik provides a ready-to-use Denmark extract for
  roads, railways, buildings, land use, water, and forest. OpenStreetMap land
  polygons provide the land/sea geometry used with the Geofabrik Denmark
  extract boundary.
- **Alternatives and limits:** The current Datafordeler key returned HTTP 401
  for the GeoDanmark WFS, so the project uses OSM for these layers. This is an
  access result for that key, not a claim that GeoDanmark is generally
  unavailable. Energinet gas and power-line vectors were not used because
  their terms do not permit redistribution in the published map. OSM tagging
  is community-maintained and may be incomplete, particularly for pipelines
  and high-voltage lines; the model only selects `power=line` ways tagged at
  132 kV or higher and gas pipeline ways tagged `man_made=pipeline` and
  `substance=gas`. The OSM coastline and Geofabrik boundary are approximate,
  not surveyed legal borders. DAGI coastline data were not acquired or
  validated in this workflow.
- **ArcGIS Pro:** These are downloads, not WFS layers. Download the Geofabrik
  GeoPackage/PBF and the OSM land-polygon archive from the links above, or add
  the prepared GeoPackages from `data/processed/`. The source data use
  EPSG:4326; prepared vector layers use EPSG:25832. For the PBF-derived
  pipeline and power-line layers, use the prepared GeoPackage or convert
  them with the project acquisition script before adding them to ArcGIS Pro.

### Protected areas and population

- **Natura 2000 — EEA:** The EEA Habitats and Birds Directive layers provide
  one documented EU-wide source for the protected-site polygons. The selected
  product is the end-2024 version; it can lag later designations or boundary
  updates. In ArcGIS Pro, add MapServer layer 0 (Habitats) or layer 1 (Birds)
  from the [EEA service](https://bio.discomap.eea.europa.eu/arcgis/rest/services/ProtectedSites/Natura2000Sites/MapServer),
  or add the prepared `natura2000.gpkg`. The source product is EPSG:3035;
  prepared data are EPSG:25832.
- **Protected nature types (§3) and reserves — Danmarks Miljøportal:** The
  project uses the publisher's CC0 dataset downloads, rather than an
  unverified WFS response. In ArcGIS Pro, download the shapefile archives
  from the respective [§3 dataset page](https://arealdata-api.miljoeportal.dk/datasets/urn:dmp:ds:beskyttede-naturtyper)
  and [reserve dataset page](https://arealdata-api.miljoeportal.dk/datasets/urn:dmp:ds:fredede-omraader),
  extract them, and add the shapefiles; alternatively add
  `protected_areas.gpkg`. The prepared layers use EPSG:25832. These are
  source dataset geometries and may not represent current on-the-ground
  conditions between publisher updates.
- **Population — GHSL:** GHS-POP 2020 was selected because it is openly
  downloadable, consistently gridded, and has a 100 m product matching the
  Python model's source resolution. Eurostat GEOSTAT's 1 km grid would be
  coarser; a Danmarks Statistik grid was not acquired or validated for this
  workflow, so no availability claim is made. GHSL represents the 2020
  epoch, not current population. In ArcGIS Pro, download the GHSL archive,
  extract its raster, and add it as a raster dataset (source CRS ESRI:54009);
  use `ghsl_population_2020.tif` for the prepared EPSG:25832, 100 m raster.

### WFS services

For an un-authenticated WFS, create a connection in ArcGIS Pro via
**Insert → Connections → New WFS Server**, enter the endpoint below, then add
the named layer from the Catalog pane. Use **WFS To Feature Class** or export
the layer to make a local copy, setting the output coordinate system to
EPSG:25832. See Esri's guide to
[adding WFS services](https://pro.arcgis.com/en/pro-app/3.6/help/data/services/add-wfs-services.htm).
The source CRS is listed per service; EMODnet layers are EPSG:4326 and need
projection on export.

| Dataset group | WFS endpoint | Layer names | Source CRS | Why selected and known limits |
|---|---|---|---|---|
| Drinking-water interests, BNBO, and groundwater catchments (Danish Environmental Protection Agency) | [GRUKOS WFS](https://wfs2-miljoegis.mim.dk/grukos/ows) | `grukos:drikkevandsinteresser`, `grukos:bnbo`, `grukos:indvindingsoplande_alle` | EPSG:25832 | Official Danish groundwater-area data under CC0. The layer schema and published coverage can change; drinking-water categories are split by their source attributes during preparation. |
| Protected ancient monuments and protection zones (Danish Agency for Culture and Palaces) | [Agency WFS](https://www.kulturarv.dk/ffgeoserver/public/wfs) | `public:fundogfortidsminder_areal_fredet`, `public:fundogfortidsminder_linje_fredet`, `public:fundogfortidsminder_punkt_fredet`, `public:fundogfortidsminder_areal_beskyttelse` | EPSG:25832 | Official CC0 monument and protection-zone layers. Areas, lines, and points represent different feature types; preparation keeps their source geometry type and may apply model-specific treatment. |
| Lake and stream protection lines (Danmarks Miljøportal) | [Miljøportal WFS](https://arealeditering-dist-geo.miljoeportal.dk/geoserver/wfs) | `dai:soe_bes_linjer`, `dai:aa_bes_linjer` | EPSG:25832 | CC0 protection lines from the `dai:` layers; the historical `dai_historik:` copies are deliberately not used. A line is a mapped protection boundary, not a watercourse polygon. |
| Contaminated land V1 and V2 (DKJord) | [DKJord WFS](https://jord.miljoeportal.dk/geo/wfs) | `DKJord:View_V2Flader`, `DKJord:View_V1Flader` | EPSG:25832 | CC0 publisher layers preserve the separate V1/V2 classifications. Their records and extents can change as sites are assessed or reclassified. |
| Maritime spatial-plan zones (Danish Maritime Authority) | [Havplan WFS](https://havplan.dk/geoserver/havplan/wfs) | `havplan:Danmarks_havplan_af_28_juni_2024` | EPSG:25832 | CC BY 4.0 planning zones provide a consistent source for marine-use classes. This is the plan dated 2024-06-28; check the publisher for later revisions. |
| Offshore wind, dumped munitions, subsea pipelines, and cables (EMODnet Human Activities) | [EMODnet WFS](https://ows.emodnet-humanactivities.eu/wfs) | `emodnet:windfarmspoly`, `emodnet:munitionspoly`, `emodnet:munitions`, `emodnet:pipelines`, `emodnet:pcablesbshcontis` | EPSG:4326 | CC BY 4.0 European marine-activity layers. Their mapped coverage and status depend on source reporting; the point munitions layer is buffered by 500 m during preparation. Project to EPSG:25832 when exporting. |
| Beach protection and protected forest (*fredskov*) (Klimadatastyrelsen / Datafordeler) | [MATRIKLEN WFS](https://wfs.datafordeler.dk/MATRIKLEN2/MatGaeldendeOgForeloebigWFS/1.0.0/WFS) | `mat:StrandbeskyttelseFlade_Gaeldende`, `mat:FredskovFlade_Gaeldende` | EPSG:25832 | CC BY 4.0 official cadastral layers. Access requires a Datafordeler API key. For ArcGIS Pro, prefer adding the prepared layers from `data/processed/phase_b.gpkg`; if connecting directly, keep the `apikey` request parameter private and do not save or share a connection containing the key. |

### Storage areas and other non-WFS sources

- **Danish Energy Agency storage areas:** These are official licence or
  designation polygons, used as context for candidate storage locations.
  Licence terms are not stated in the source; attribute the Danish Energy
  Agency's CO₂ storage licensing map. In ArcGIS Pro, add each FeatureServer
  layer from the exact URL in [`data/SOURCES.md`](../../data/SOURCES.md)
  using **Add Data From Path**; the source geometry is EPSG:4326. Thorning
  uses an ArcGIS item-data URL rather than a FeatureServer. The polygons
  describe licensing/designation areas, not proven capacity or permission to
  inject.
- **OSM basemap:** The standard tile service is a runtime basemap, not an
  analysis input. Add it through the ArcGIS Pro basemap gallery and retain
  visible OpenStreetMap attribution; do not bulk-download tiles.

For source details, exact download dates, and checksums, see
[`data/SOURCES.md`](../../data/SOURCES.md) and
[`data/raw/acquisition-manifest.json`](../../data/raw/acquisition-manifest.json).
