"""Browser smoke test of the static map, driven by Playwright.

Serve web/ (for example `python -m http.server 18765 --directory web`), then
run with a Python that has Playwright and its Chromium installed:

    python validation/ui_smoke.py http://127.0.0.1:18765/ --routes 80 --sources 8

Prints PASS/FAIL per check, writes screenshots to --shots, and exits 1 on any
failure. It only reads the site; it never changes files in the project.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import unquote

from playwright.sync_api import Page, sync_playwright

LAUNCH_ARGS = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]
results: list[tuple[bool, str]] = []


def check(ok: bool, name: str, detail: str = "") -> None:
    results.append((ok, name))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))


def wait_ready(page: Page) -> None:
    # Wait for the app's own layers, not map.loaded(): that also waits for
    # every basemap tile, which can stall on slow or filtered networks.
    page.wait_for_selector("#map-loading.hidden", state="attached", timeout=30_000)
    page.wait_for_function(
        "window.co2Map && window.co2Map.isStyleLoaded()"
        " && window.co2Map.getLayer('cost-surface-raster-0')",
        timeout=30_000,
    )
    page.wait_for_function(
        "document.querySelector('#route-layers').children.length > 0", timeout=30_000
    )
    page.wait_for_timeout(1000)


def run(base: str, routes: int, sources: int, shots: Path) -> int:
    shots.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(args=LAUNCH_ARGS)
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on(
            "response",
            lambda r: errors.append(f"HTTP {r.status} {r.url}")
            if r.status >= 400 and "tile.openstreetmap.org" not in r.url
            else None,
        )

        page.goto(base)
        wait_ready(page)
        page.screenshot(path=shots / "01_start.png")
        check(page.locator("#status").inner_text().strip() != "", "status message shown",
              page.locator("#status").inner_text()[:80])
        sizes = page.evaluate(
            """async () => {
              const gl = document.createElement('canvas').getContext('webgl2');
              const manifest = await (await fetch('data/map.json')).json();
              const urls = manifest.cost_tiles.map(t => t.url);
              const dims = await Promise.all(urls.map(u => new Promise(ok => {
                const img = new Image(); img.onload = () => ok(Math.max(img.width, img.height));
                img.onerror = () => ok(-1); img.src = u;
              })));
              return {limit: gl.getParameter(gl.MAX_TEXTURE_SIZE), largest: Math.max(...dims),
                      tiles: dims.length};
            }"""
        )
        check(0 < sizes["largest"] <= sizes["limit"], "cost tiles fit the GPU texture limit",
              f"{sizes['tiles']} tiles, largest {sizes['largest']} px, limit {sizes['limit']}")
        badges = page.locator(".score-badge").count()
        check(badges >= 10, "score badges on layer toggles", f"{badges}")

        if page.evaluate("!!window.co2Map.getLayer('storage-areas-fill')"):
            areas = page.evaluate(
                "window.co2Map.querySourceFeatures('storage_areas').length"
            )
            check(areas > 0, "storage licence areas loaded", f"{areas} features")
        has_routes = page.locator("#route-list-wrap").is_visible()

        if not has_routes:
            check("not" in page.locator("#route-layers").inner_text().lower()
                  or page.locator("#route-layers").inner_text() != "",
                  "missing-routes message shown")
        else:
            rows = page.locator(".route-row").count()
            check(rows == routes, "route list length", f"{rows} rows, expected {routes}")
            options = page.locator("#route-filter option").count() - 1
            check(options == sources, "source filter options", f"{options}, expected {sources}")
            best = page.locator(".badge.best").count()
            check(best == sources, "one 'best' badge per source", f"{best}")
            network = page.locator(".badge.mst").count()
            check(network >= 1, "network badges present", f"{network}")

            page.locator(".route-row").first.click()
            page.wait_for_selector(".maplibregl-popup", timeout=10_000)
            page.wait_for_timeout(1500)
            page.screenshot(path=shots / "02_route_selected.png")
            check(page.locator(".route-row.selected").count() == 1, "clicked row is selected")
            check("route=" in page.url, "address bar has a route link", page.url.split("?")[-1])
            popup = page.locator(".maplibregl-popup").inner_text()
            check("Length" in popup and "km" in popup, "route popup shows length and km")
            highlighted = page.evaluate(
                "window.co2Map.queryRenderedFeatures({layers: ['route-highlight']}).length"
            )
            check(highlighted > 0, "selected route is highlighted on the map", f"{highlighted}")
            if page.evaluate("!!window.co2Map.getLayer('corridors-fill')"):
                corridor = page.evaluate(
                    "window.co2Map.queryRenderedFeatures({layers: ['corridors-fill']}).length"
                )
                check(corridor > 0, "selected route's corridor is drawn", f"{corridor}")

            for index in (1, 2):
                page.locator(".route-row").nth(index).click()
                page.wait_for_timeout(700)
            popups = page.locator(".maplibregl-popup").count()
            check(popups == 1, "only one popup open after selecting three routes",
                  f"{popups}")
            page.locator(".route-row").first.click()
            page.wait_for_timeout(700)

            selected_link = page.url
            values = page.locator("#route-filter option").evaluate_all(
                "options => options.map(o => o.value).filter(Boolean)"
            )
            page.select_option("#route-filter", values[-1])
            per_source = page.locator(".route-row").count()
            check(per_source == routes // sources, "filter shows one source's routes",
                  f"{per_source}, expected {routes // sources}")
            page.select_option("#route-filter", "")

            page.goto(selected_link)
            wait_ready(page)
            page.wait_for_selector(".maplibregl-popup", timeout=10_000)
            page.wait_for_timeout(1500)
            page.screenshot(path=shots / "03_deep_link.png")
            key = page.locator(".route-row.selected").get_attribute("data-route-key") or ""
            link = unquote(selected_link.split("route=")[-1])
            check(key.replace("→", ",") == link, "deep link selects the linked route", key)

            point = page.evaluate(
                """() => {
                  const map = window.co2Map;
                  map.jumpTo({center: [10.5, 56.0], zoom: 6});
                  const f = map.querySourceFeatures('hotspots')
                    .find(f => f.properties.ets_verified_2024_t);
                  if (!f) return null;
                  const p = map.project(f.geometry.coordinates);
                  return {x: p.x, y: p.y, name: f.properties.name};
                }"""
            )
            if point:
                page.wait_for_timeout(1000)
                box = page.locator("#map").bounding_box()
                page.mouse.click(box["x"] + point["x"], box["y"] + point["y"])
                page.wait_for_timeout(1000)
                popup = page.locator(".maplibregl-popup").last.inner_text()
                page.screenshot(path=shots / "04_hotspot_popup.png")
                check("ETS 2024" in popup and "biogenic" in popup,
                      "hotspot popup shows ETS and capture", point["name"])
            else:
                check(False, "hotspot with ETS data found on the map")

        groups = page.locator("#input-layers details").count()
        check(groups >= 3, "layer groups are collapsible", f"{groups} groups")
        page.evaluate("document.querySelectorAll('#input-layers details').forEach(d => d.open = true)")
        toggles = page.locator("#input-layers input[type=checkbox]")
        for index in range(toggles.count()):
            toggles.nth(index).check()
        page.wait_for_timeout(3000)
        page.screenshot(path=shots / "05_all_layers.png")
        visible = page.evaluate(
            """() => {
              const map = window.co2Map;
              const on = map.getStyle().layers
                .filter(l => l.id.includes('-raster-') && !l.id.startsWith('cost-surface')
                  && map.getLayoutProperty(l.id, 'visibility') !== 'none')
                .map(l => l.id.split('-raster-')[0]);
              return new Set(on).size;
            }"""
        )
        check(visible == toggles.count(), "every input layer toggles on",
              f"{visible}/{toggles.count()} (classes without data have no toggle)")
        browser.close()

    check(not errors, "no console errors or failed requests", "; ".join(errors[:3]))
    failed = [name for ok, name in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed. Screenshots: {shots}")
    return 1 if failed else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("url")
    parser.add_argument("--routes", type=int, default=80)
    parser.add_argument("--sources", type=int, default=8)
    parser.add_argument("--shots", type=Path, default=Path("ui_smoke_shots"))
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(run(args.url, args.routes, args.sources, args.shots))


if __name__ == "__main__":
    main()
