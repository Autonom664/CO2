# Data sources

Acquisition date below is the date recorded by the download run. The raw files and a SHA-256 manifest are in the git-ignored `data/raw/` directory. Processed vector outputs use EPSG:25832; the population raster uses EPSG:25832 at 100 m.

| Dataset | Publisher | Source URL | Licence / terms | Source CRS → processed CRS | Download date |
|---|---|---|---|---|---|
| Geofabrik Denmark extract boundary | OpenStreetMap contributors; Geofabrik | <https://download.geofabrik.de/europe/denmark.poly> | Open Database License (ODbL) 1.0; attribution required | EPSG:4326 | 2026-10-07 |
| OpenStreetMap Denmark extract (GeoPackage export) | OpenStreetMap contributors; Geofabrik | <https://download.geofabrik.de/europe/denmark-latest-free.gpkg.zip> | Open Database License (ODbL) 1.0; attribution required | EPSG:4326 (source); EPSG:25832 (processed) | 2026-10-07 |
| OpenStreetMap coastline-derived land polygons | OpenStreetMap contributors; osmdata.openstreetmap.de | <https://osmdata.openstreetmap.de/download/land-polygons-split-4326.zip> | ODbL 1.0; attribution required | EPSG:4326 (source); EPSG:25832 (processed) | 2026-10-07 |
| Natura 2000 Habitats Directive sites, version end 2024 | European Environment Agency | <https://bio.discomap.eea.europa.eu/arcgis/rest/services/ProtectedSites/Natura2000Sites/MapServer/0/query> | EEA reuse terms; attribution required; see dataset metadata | EPSG:3035 (catalogue product); EPSG:25832 (query output) | 2026-10-07 |
| Natura 2000 Birds Directive sites, version end 2024 | European Environment Agency | <https://bio.discomap.eea.europa.eu/arcgis/rest/services/ProtectedSites/Natura2000Sites/MapServer/1/query> | EEA reuse terms; attribution required; see dataset metadata | EPSG:3035 (catalogue product); EPSG:25832 (query output) | 2026-10-07 |
| Protected nature types (§3) | Danmarks Miljøportal | <https://arealdata-api.miljoeportal.dk/datasets/urn:dmp:ds:beskyttede-naturtyper> | CC0 1.0 | EPSG:25832 | 2026-10-07 |
| Fredede områder | Danmarks Miljøportal | <https://arealdata-api.miljoeportal.dk/datasets/urn:dmp:ds:fredede-omraader> | CC0 1.0 | EPSG:25832 | 2026-10-07 |
| GHS-POP R2023A, epoch 2020, 100 m | European Commission Joint Research Centre | <https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/GHS_POP_GLOBE_R2023A/GHS_POP_E2020_GLOBE_R2023A_54009_100/V1-0/GHS_POP_E2020_GLOBE_R2023A_54009_100_V1_0.zip> | European Commission reuse notice; source acknowledgment required | ESRI:54009 (source); EPSG:25832 (processed) | 2026-10-07 |
| OpenStreetMap standard tiles (web basemap) | OpenStreetMap contributors | <https://tile.openstreetmap.org/{z}/{x}/{y}.png> | OSM tile policy; visible attribution, caching, no bulk download | EPSG:3857 | Not downloaded (runtime tiles) |

The Geofabrik PBF extract was downloaded during initial format testing but is not used by the current preparation pipeline. OSM-derived processed layers are read from the GeoPackage export listed above.

Additional source endpoints used by the downloader:

- Geofabrik Denmark extract boundary: <https://download.geofabrik.de/europe/denmark.poly> (EPSG:4326).
- Natura 2000 metadata: <https://sdi.eea.europa.eu/catalogue/datahub/api/records/91357f39-7866-41ce-b447-43905c364ec8>. The EEA REST query downloads Denmark's Habitat Directive and Birds Directive layers; output queries request EPSG:25832.
- Danmarks Miljøportal distributes the §3 and fredede datasets as shapefile downloads and exposes EPSG:25832 WFS metadata.
- GHSL's full 100 m global archive is retained in raw storage; only the buffered Denmark extent is reprojected to the processed raster.

No download date is claimed until a source is actually downloaded. When multiple sources are downloaded on different days, update this register with their individual dates from `data/raw/acquisition-manifest.json`.

## CO2 hotspot candidates

`data/input/hotspots.csv` contains eight illustrative source/hub locations and
four potential storage locations. Coordinates use WGS84 (EPSG:4326); routing
reprojects them to EPSG:25832. The `source_url` field records the coordinate
reference and `project_source_url` records the cited project/status reference.
These are demo anchors: named industrial-area representative points and
village-centre proxies are not surveyed capture, terminal, injection, or
licence-boundary coordinates.

| Hotspot | Role and coordinate basis | Project/status reference |
|---|---|---|
| Aalborg Portland cement works | Source; representative point of OSM way 21107368 | [ACCSION project](https://aalborgportland.dk/accsion/) |
| Ørsted Asnæs power station | Source; representative point of OSM way 326024684 | [Danish Energy Agency CCUS award](https://ens.dk/en/press/first-tender-ccus-subsidy-scheme-has-been-finalized-danish-energy-agency-awards-contract) |
| Ørsted Avedøre power station | Source; representative point of OSM way 25134192 | [Danish Energy Agency CCUS award](https://ens.dk/en/press/first-tender-ccus-subsidy-scheme-has-been-finalized-danish-energy-agency-awards-contract) |
| ARC Amager Bakke | Source; representative point of OSM way 429610236; no capture-project status is asserted | [ARC](https://a-r-c.dk/) |
| Vestforbrænding | Source; OSM industrial building way 25945244, geocoded with Nominatim | [Vestforbrænding project update](https://vestfor.dk/bliv-klogere/nyheder/nyhedsoverblik/vestforbraending-og-cip-traekker-sig-fra-udbud-om-co2-fangst-og-lagring) |
| Fjernvarme Fyn Odense plant | Source; representative point of OSM way 1385960182 | [Fjernvarme Fyn CCS-fund update](https://www.fjernvarmefyn.dk/nyheder/fjernvarme-fyn-ansoeger-ikke-statens-ccs-pulje/) |
| Greenport Scandinavia Hirtshals terminal | Source; OSM marina node 2244918038 used as an approximate port-area location | [Greenport Scandinavia](https://greenportscandinavia.com/) |
| Port of Aalborg East Port CO2 terminal | Source; representative point of OSM way 1036639242, not the planned terminal footprint | [Port of Aalborg CO2 reception announcement](https://portofaalborg.dk/en/new-co2-reception-facilities-will-make-aalborg-one-of-europes-leaders-in-carbon-management/) |
| Greensand Nini West | Storage; approximate Nini B platform coordinate used as a field proxy | [Coordinate reference](https://en.wikipedia.org/wiki/Siri,_Nini_and_Cecilie_oil_fields); [storage-project approval summary](https://stateofgreen.com/en/news/denmark-approves-first-co2-storage-facility/) |
| Greenstore Gassum | Storage; Nominatim village-centre proxy for the broad exploration area | [Danish Energy Agency on exploration licences](https://ens.dk/en/press/first-licenses-danish-history-explore-onshore-co2-storage-potentials-awarded); [Greenstore](https://greenstore.dk/en/home-page/) |
| Havnsø exploration area | Storage; Nominatim village-centre proxy for the broad exploration area | [Danish Energy Agency on exploration licences](https://ens.dk/en/press/first-licenses-danish-history-explore-onshore-co2-storage-potentials-awarded) |
| Rødby exploration area | Storage; Nominatim village-centre proxy for the broad exploration area | [Danish Energy Agency on exploration licences](https://ens.dk/en/press/first-licenses-danish-history-explore-onshore-co2-storage-potentials-awarded) |

The five emitter industrial-area representative points and the Port of Aalborg
point are derived from the Geofabrik OSM Denmark GeoPackage already listed above
(OSM contributors, ODbL 1.0). The Vestforbrænding building location and the
Gassum, Havnsø, Rødby, and Hirtshals mapped-place locations are retrieved via
the OSM Nominatim search API (ODbL 1.0; attribution required). Nini West's
coordinate is an approximate point for the offshore Nini B platform, not an
official injection-well coordinate; the cited State of Green page identifies
the approved project and field but does not supply that coordinate. Wikipedia
content is CC BY-SA; all hotspot coordinates and status descriptions remain
explicitly indicative.

The three onshore storage candidates are exploration-licence areas, not
permitted operating stores. The map and route outputs must not imply otherwise.
Nini West is offshore, so `routing.offshore_corridor_half_width_m` in
`config/costs.yaml` controls the 10 km half-width corridor added to the
land-buffered study area. All 1–10 cost assumptions remain user-adjustable in
that same configuration file.
