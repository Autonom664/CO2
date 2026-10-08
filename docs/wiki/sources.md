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

For source details, exact download dates, and checksums, see
[`data/SOURCES.md`](../../data/SOURCES.md) and
[`data/raw/acquisition-manifest.json`](../../data/raw/acquisition-manifest.json).
