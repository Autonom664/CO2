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
