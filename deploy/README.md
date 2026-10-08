# Static-site deployment

The map is a static site served by one small Nginx container. Routing and map
asset generation happen before deployment; the web container does not need
Python, GIS libraries, or persistent application data. The Compose service
binds only to `127.0.0.1:18080` by default, so it can sit behind an existing
reverse proxy.

## Build the publishable files

From the repository root, with the project Python environment active:

```powershell
python -m src.cost_surface
python -m src.routing
python -m src.corridors
python -m src.build_web
python -m src.export_model
python -m validation.model_parity
python -m validation.check_outputs
```

Both the model-pack parity command and the output validation command must pass
before deployment. `src.export_model` writes the 250 m browser inputs to
`web/data/model/`; it does not replace the 100 m published cost surface or
routes. Optionally run
`validation/ui_smoke.py` against the local site; it requires Playwright.

Compose binds the site to `127.0.0.1:18080` by default. Override
`CO2_MAP_BIND` to change the host binding, for example
`CO2_MAP_BIND=0.0.0.0:8080` when direct external binding is intended.

Review `web/data/map.json` and test the site locally before deployment:

```powershell
python -m http.server 8000 --directory web
```

The MapLibre library and OpenStreetMap basemap are loaded from their public
services in the browser, so viewers need internet access. Attribution is
displayed on the map.

## Prepare the host

Use a host with enough **RAM and CPU capacity** for building routes and
assets; the static web container itself is light. Check the host's actual
capacity rather than assuming a product or address. On an Ubuntu host with
Docker Engine and the Compose plugin, first confirm the selected bind port
and port `80` are available. If port `80` is already handled by a reverse
proxy, keep it and add a virtual host for a domain you control.

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

Configure the host's reverse proxy to forward requests for your domain to
the local Compose bind address. Test the proxy configuration before reloading
it. Point the domain's DNS record to the chosen host; add an AAAA record
only if IPv6 is configured and reachable. After DNS resolves, issue a TLS
certificate with the host's certificate manager or Certbot and redirect HTTP
to HTTPS.

These local deployment instructions make no DNS, hosting-account, or server
changes. Do not modify DNS without explicit confirmation.

Keep the `web/` build output and the repo's `data/raw/` source archives
separate; only the former is copied to the web server.

To roll back the Compose service and its virtual host:

```sh
cd /path/to/deployment
sudo docker compose down
sudo rm /etc/nginx/sites-enabled/example-site.conf
sudo nginx -t
sudo systemctl reload nginx
```
