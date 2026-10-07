# Temporary OVH demo deployment

The map is a static site served by one small Nginx container. Routing and map
asset generation happen before deployment; the web container does not need
Python, GIS libraries, or persistent application data. The Compose service
binds only to `127.0.0.1:18080`, so it can share the OVH host with other apps
and use the host's existing reverse proxy.

## Build the publishable files

From the repository root, with the project Python environment active:

```powershell
python -m src.cost_surface
python -m src.build_web
```

The routing command requires the expert-approved
`data/input/hotspots.csv`. If it is not supplied, the site still builds with
the input layers and cost surface, and it explicitly reports that routes are
not available. After the expert approves and supplies the CSV, run
`python -m src.routing` and then rebuild the site. Do not deploy placeholder
hotspot coordinates.

Review `web/data/map.json` and test the site locally before deployment:

```powershell
python -m http.server 8000 --directory web
```

The MapLibre library and OpenStreetMap basemap are loaded from their public
services in the browser, so viewers need internet access. Attribution is
displayed on the map.

## Prepare the OVH host

Use the OVH host with the largest available **RAM and CPU capacity** for
building routes and assets; the static web container itself is light. Check
the actual inventory in the OVH control panel rather than assuming a product
name or server address. On an Ubuntu host with Docker Engine and the Compose
plugin, first confirm ports `18080` and `80` are available. If port `80` is
already handled by an existing reverse proxy, keep that proxy and add the
`co2.michaelbinger.dk` virtual host to it.

Copy the repository's `web/`, `Dockerfile`, `docker-compose.yml`, and
`deploy/nginx-app.conf` to a deployment directory on the host. Keep source
data and the Python environment out of the web container. From that directory:

```sh
docker compose up -d --build
docker compose ps
curl --fail http://127.0.0.1:18080/
```

The container has a read-only root filesystem apart from temporary Nginx
files and restarts unless stopped. To remove the temporary demo later:

```sh
docker compose down
```

## Reverse proxy, DNS, and HTTPS

Install the provided
[`nginx-co2.michaelbinger.dk.conf`](./nginx-co2.michaelbinger.dk.conf) in the
host's Nginx configuration (or translate its proxy target into the existing
proxy manager), then test and reload Nginx. Configure the domain's A record to
the OVH host's public IPv4 address; add an AAAA record only if IPv6 is
configured and reachable. After DNS resolves, issue a TLS certificate with
the host's existing certificate manager or Certbot and redirect HTTP to
HTTPS.

No DNS changes, OVH account access, or server changes have been made. Before
adding the DNS record, confirm the chosen host's public IP, that its proxy
configuration is live, and that the user wants the record changed. The exact
record to add will be `co2` → the confirmed OVH server address.

The current deploy configuration is intentionally minimal for a short-lived
demo. Keep the `web/` build output and the repo's `data/raw/` source archives
separate; only the former is copied to the web server.
