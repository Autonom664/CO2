"use strict";

const mapElement = document.getElementById("map");
const statusElement = document.getElementById("status");
const loadingElement = document.getElementById("map-loading");
const sidebar = document.getElementById("sidebar");
const routeLayerIds = {
  routes: "pair-routes",
  minimum_spanning_network: "mst-network",
  hotspots: "hotspots",
};

function setStatus(message, severity = "ok") {
  statusElement.textContent = message;
  statusElement.classList.toggle("warning", severity === "warning");
  statusElement.classList.toggle("error", severity === "error");
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[character]);
}

function makeLayerToggle(id, label, color, checked, onChange, score = "") {
  const wrapper = document.createElement("label");
  wrapper.className = "layer-toggle";
  const input = document.createElement("input");
  input.type = "checkbox";
  input.checked = checked;
  input.addEventListener("change", () => onChange(input.checked));
  const swatch = document.createElement("span");
  swatch.className = "swatch";
  swatch.style.backgroundColor = color || "#ffffff";
  const text = document.createElement("span");
  text.textContent = label;
  wrapper.append(input, swatch, text);
  if (score) {
    const badge = document.createElement("span");
    badge.className = "score-badge";
    badge.textContent = score;
    badge.title = score === "barrier"
      ? "Impassable barrier"
      : "Configured cost score (1–10, config/costs.yaml)";
    wrapper.appendChild(badge);
  }
  wrapper.dataset.layerId = id;
  return wrapper;
}

function routeKey(properties) {
  return `${properties.from_id}→${properties.to_id}`;
}

function geometryBounds(geometry) {
  const lines = geometry.type === "MultiLineString"
    ? geometry.coordinates
    : [geometry.coordinates];
  const bounds = new maplibregl.LngLatBounds();
  for (const line of lines) for (const point of line) bounds.extend(point);
  return bounds;
}

function geometryMidpoint(geometry) {
  const line = geometry.type === "MultiLineString"
    ? geometry.coordinates[0]
    : geometry.coordinates;
  return line[Math.floor(line.length / 2)];
}

function addImageLayer(map, layer) {
  if (!map.getSource(layer.id)) {
    map.addSource(layer.id, {
      type: "image",
      url: layer.url,
      coordinates: map.co2Bounds,
    });
  }
  if (!map.getLayer(`${layer.id}-raster`)) {
    map.addLayer({
      id: `${layer.id}-raster`,
      type: "raster",
      source: layer.id,
      paint: { "raster-opacity": 0.92, "raster-fade-duration": 0 },
    });
  }
  map.setLayoutProperty(`${layer.id}-raster`, "visibility", "visible");
}

function addGeoJsonLayer(map, layer, data) {
  if (map.getSource(layer.id)) return;
  map.addSource(layer.id, { type: "geojson", data: data || layer.url });
  if (layer.id === "routes") {
    map.addLayer({
      id: "pair-routes",
      type: "line",
      source: "routes",
      layout: { "line-cap": "round", "line-join": "round" },
      paint: {
        "line-color": "#d94d41",
        "line-width": ["interpolate", ["linear"], ["zoom"], 4, 1.2, 9, 3],
        "line-opacity": 0.78,
      },
    });
    map.addLayer({
      id: "route-highlight",
      type: "line",
      source: "routes",
      filter: ["==", ["get", "from_id"], "__none__"],
      layout: { "line-cap": "round", "line-join": "round" },
      paint: {
        "line-color": "#ffd23f",
        "line-width": ["interpolate", ["linear"], ["zoom"], 4, 4, 9, 8],
        "line-opacity": 0.95,
      },
    });
  } else if (layer.id === "minimum_spanning_network") {
    map.addLayer({
      id: "mst-network",
      type: "line",
      source: "minimum_spanning_network",
      layout: { "line-cap": "round", "line-join": "round" },
      paint: {
        "line-color": "#2c296e",
        "line-width": ["interpolate", ["linear"], ["zoom"], 4, 2.2, 9, 4.5],
        "line-opacity": 0.95,
      },
    });
  } else if (layer.id === "hotspots") {
    map.addLayer({
      id: "hotspots",
      type: "circle",
      source: "hotspots",
      paint: {
        "circle-radius": [
          "interpolate", ["linear"], ["zoom"],
          4, ["match", ["get", "role"], "storage", 6, 4],
          9, ["match", ["get", "role"], "storage", 11, 8],
        ],
        "circle-color": [
          "match",
          ["get", "role"],
          "storage",
          "#2878a8",
          "#e28b24",
        ],
        "circle-stroke-color": [
          "match", ["get", "role"], "storage", "#ffffff", "#17333a",
        ],
        "circle-stroke-width": ["match", ["get", "role"], "storage", 3, 2],
      },
    });
  }
}

function addRoutePopup(map, event) {
  const feature = event.features && event.features[0];
  if (!feature) return;
  const properties = feature.properties || {};
  const routeName = properties.from_name
    ? `${properties.from_name} → ${properties.to_name}`
    : properties.name || properties.id || "Hotspot";
  let rows = "";
  if (properties.from_name) {
    const entries = [
      ["From status", properties.from_project_status],
      ["To status", properties.to_project_status],
      ["Length", `${Number(properties.length_km).toFixed(2)} km`],
      ["Accumulated cost", Number(properties.accumulated_cost).toFixed(2)],
      ...Object.entries(properties)
        .filter(([key, value]) => key.startsWith("km_") && Number(value) > 0)
        .map(([key, value]) => [
          key.slice(3).replaceAll("_", " "),
          `${Number(value).toFixed(2)} km`,
        ]),
    ].filter(([, value]) => value !== "" && value !== null && value !== undefined);
    rows = `<table class="popup-table">${entries.map(([key, value]) =>
      `<tr><td>${escapeHtml(key)}</td><td>${escapeHtml(value)}</td></tr>`
    ).join("")}</table>`;
  } else {
    const tonnes = (value) => {
      const number = Number(value);
      return value === "" || value === null || value === undefined || !Number.isFinite(number)
        ? ""
        : `${number.toLocaleString("en-GB", { maximumFractionDigits: 0 })} t/yr`;
    };
    const details = [
      ["Role", properties.role],
      ["Type", properties.site_type],
      ["Project status", properties.project_status],
      ["ETS 2024 (fossil)", tonnes(properties.ets_verified_2024_t)],
      ["Planned capture", tonnes(properties.planned_capture_tpa)],
      ["Capture basis", properties.capture_basis],
      ["Location basis", properties.location_basis],
    ].filter(([, value]) => value);
    rows = `<table class="popup-table">${details.map(([key, value]) =>
      `<tr><td>${escapeHtml(key)}</td><td>${escapeHtml(value)}</td></tr>`
    ).join("")}</table>`;
    if (properties.ets_verified_2024_t !== undefined && properties.ets_verified_2024_t !== null && properties.ets_verified_2024_t !== "") {
      rows += '<p class="popup-note">EU ETS figures exclude biogenic CO₂, so biomass and waste plants can capture far more than they report.</p>';
    }
    if (properties.capture_source_url) {
      rows += `<p><a href="${escapeHtml(properties.capture_source_url)}" target="_blank" rel="noopener noreferrer">Capture source</a></p>`;
    }
    if (properties.source_url) {
      rows += `<p><a href="${escapeHtml(properties.source_url)}" target="_blank" rel="noopener noreferrer">Location source</a></p>`;
    }
    if (properties.project_source_url) {
      rows += `<p><a href="${escapeHtml(properties.project_source_url)}" target="_blank" rel="noopener noreferrer">Project source</a></p>`;
    }
  }
  new maplibregl.Popup({ maxWidth: "340px" })
    .setLngLat(event.lngLat)
    .setHTML(`<h3 class="popup-title">${escapeHtml(routeName)}</h3>${rows}`)
    .addTo(map);
}

function setupInputLayers(map, layers) {
  const container = document.getElementById("input-layers");
  const groups = new Map();
  for (const layer of layers) {
    if (!groups.has(layer.group)) groups.set(layer.group, []);
    groups.get(layer.group).push(layer);
  }
  for (const [groupName, groupLayers] of groups) {
    const section = document.createElement("section");
    section.className = "layer-group";
    const title = document.createElement("h2");
    title.textContent = groupName;
    section.appendChild(title);
    for (const layer of groupLayers) {
      section.appendChild(makeLayerToggle(
        layer.id,
        layer.label,
        layer.color,
        layer.default_visible,
        (visible) => {
          if (visible) addImageLayer(map, layer);
          else if (map.getLayer(`${layer.id}-raster`)) {
            map.setLayoutProperty(`${layer.id}-raster`, "visibility", "none");
          }
        },
        layer.score,
      ));
    }
    container.appendChild(section);
  }
}

async function fetchGeoJson(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) throw new Error(`${url} returned HTTP ${response.status}`);
  return response.json();
}

function setRouteLayerVisible(map, visible) {
  for (const layerId of ["pair-routes", "route-highlight"]) {
    if (map.getLayer(layerId)) {
      map.setLayoutProperty(layerId, "visibility", visible ? "visible" : "none");
    }
  }
  const toggle = document.querySelector('[data-layer-id="routes"] input');
  if (toggle) toggle.checked = visible;
}

function selectRoute(map, feature, { zoom = true, popup = true } = {}) {
  const properties = feature.properties;
  setRouteLayerVisible(map, true);
  map.setFilter("route-highlight", [
    "all",
    ["==", ["get", "from_id"], properties.from_id],
    ["==", ["get", "to_id"], properties.to_id],
  ]);
  for (const row of document.querySelectorAll(".route-row")) {
    row.classList.toggle("selected", row.dataset.routeKey === routeKey(properties));
  }
  if (zoom) {
    map.fitBounds(geometryBounds(feature.geometry), { padding: 60, maxZoom: 10 });
  }
  if (popup) {
    addRoutePopup(map, {
      features: [feature],
      lngLat: geometryMidpoint(feature.geometry),
    });
  }
}

function setupRouteList(map, routes, networkKeys) {
  const container = document.getElementById("route-list");
  const filter = document.getElementById("route-filter");
  const features = routes.features
    .filter((feature) => feature.geometry)
    .sort((a, b) => a.properties.accumulated_cost - b.properties.accumulated_cost);
  const cheapestBySource = new Map();
  for (const feature of features) {
    if (!cheapestBySource.has(feature.properties.from_id)) {
      cheapestBySource.set(feature.properties.from_id, routeKey(feature.properties));
    }
  }
  const sources = [...new Map(features.map((feature) => [
    feature.properties.from_id, feature.properties.from_name,
  ])).entries()].sort((a, b) => a[1].localeCompare(b[1]));
  for (const [id, name] of sources) {
    const option = document.createElement("option");
    option.value = id;
    option.textContent = name;
    filter.appendChild(option);
  }

  function render() {
    container.replaceChildren();
    const selected = filter.value;
    const visible = features.filter((feature) =>
      !selected || feature.properties.from_id === selected
    );
    for (const feature of visible) {
      const properties = feature.properties;
      const key = routeKey(properties);
      const row = document.createElement("button");
      row.type = "button";
      row.className = "route-row";
      row.dataset.routeKey = key;
      const title = document.createElement("span");
      title.className = "route-title";
      title.textContent = `${properties.from_name} → ${properties.to_name}`;
      const meta = document.createElement("span");
      meta.className = "route-meta";
      const sea = Number(properties.km_open_sea || 0);
      meta.textContent =
        `${Number(properties.length_km).toFixed(0)} km · cost ${Number(properties.accumulated_cost).toFixed(0)}`
        + (sea > 0 ? ` · ${sea.toFixed(0)} km sea` : "");
      row.append(title, meta);
      const badges = document.createElement("span");
      badges.className = "route-badges";
      if (cheapestBySource.get(properties.from_id) === key) {
        badges.insertAdjacentHTML("beforeend", '<span class="badge best" title="Lowest-cost storage option for this source">best</span>');
      }
      if (networkKeys.has(key)) {
        badges.insertAdjacentHTML("beforeend", '<span class="badge mst" title="Part of the minimum spanning network">network</span>');
      }
      row.appendChild(badges);
      row.addEventListener("click", () => selectRoute(map, feature));
      container.appendChild(row);
    }
  }
  filter.addEventListener("change", render);
  render();
  document.getElementById("route-list-wrap").hidden = false;
}

async function setupRoutes(map, manifest) {
  const routeLayers = manifest.route_layers || [];
  const section = document.getElementById("routes-section");
  const container = document.getElementById("route-layers");
  section.hidden = false;
  if (!routeLayers.length) {
    const note = document.createElement("p");
    note.className = "muted";
    note.textContent = manifest.route_status
      || "Route outputs have not been generated yet.";
    container.appendChild(note);
    return;
  }
  const data = {};
  await Promise.all(routeLayers.map(async (layer) => {
    try {
      data[layer.id] = await fetchGeoJson(layer.url);
    } catch (error) {
      setStatus(`Route data could not be loaded: ${error.message}`, "warning");
    }
  }));
  for (const layer of routeLayers) {
    if (!data[layer.id]) continue;
    const color = layer.id === "hotspots"
      ? "#f5f3ec"
      : layer.id === "minimum_spanning_network" ? "#2c296e" : "#d94d41";
    const defaultVisible = layer.id !== "routes";
    container.appendChild(makeLayerToggle(
      layer.id,
      layer.label,
      color,
      defaultVisible,
      (visible) => {
        if (layer.id === "routes") {
          setRouteLayerVisible(map, visible);
          return;
        }
        const mapLayerId = routeLayerIds[layer.id];
        if (map.getLayer(mapLayerId)) {
          map.setLayoutProperty(mapLayerId, "visibility", visible ? "visible" : "none");
        }
      },
    ));
    addGeoJsonLayer(map, layer, data[layer.id]);
    if (!defaultVisible) setRouteLayerVisible(map, false);
  }
  if (map.getLayer("hotspots")) map.moveLayer("hotspots");
  document.getElementById("hotspot-legend").hidden = !data.hotspots;
  if (data.routes) {
    const networkKeys = new Set(
      (data.minimum_spanning_network?.features || [])
        .map((feature) => routeKey(feature.properties))
    );
    setupRouteList(map, data.routes, networkKeys);
    map.on("click", "pair-routes", (event) => {
      const clicked = event.features && event.features[0];
      const feature = clicked && data.routes.features.find((candidate) =>
        routeKey(candidate.properties) === routeKey(clicked.properties)
      );
      if (feature) selectRoute(map, feature, { zoom: false, popup: false });
    });
  }
  for (const layerId of ["pair-routes", "mst-network", "hotspots"]) {
    if (!map.getLayer(layerId)) continue;
    map.on("click", layerId, (event) => addRoutePopup(map, event));
    map.on("mouseenter", layerId, () => { map.getCanvas().style.cursor = "pointer"; });
    map.on("mouseleave", layerId, () => { map.getCanvas().style.cursor = ""; });
  }
}

async function startMap() {
  let manifest;
  try {
    const response = await fetch("data/map.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`Map metadata returned HTTP ${response.status}`);
    manifest = await response.json();
  } catch (error) {
    setStatus(`Map data is unavailable: ${error.message}`, "error");
    loadingElement.textContent = "Build the map assets with python -m src.build_web.";
    return;
  }

  setStatus(manifest.route_status, manifest.routes_available ? "ok" : "warning");
  document.getElementById("analysis-meta").textContent =
    `Open-data least-cost analysis · ${manifest.crs} · ${manifest.resolution_m} m grid`;
  document.getElementById("cost-low").textContent =
    `Low (${Number(manifest.cost_range_percentile_2_98[0]).toFixed(1)})`;
  document.getElementById("cost-high").textContent =
    `High (${Number(manifest.cost_range_percentile_2_98[1]).toFixed(1)})`;
  document.getElementById("scale-note").textContent =
    `Overlay colors are emphasized; zoom in for roads and watercourses. Display ${manifest.display_resolution_m} m; analysis ${manifest.resolution_m} m.`;

  const map = new maplibregl.Map({
    container: mapElement,
    style: {
      version: 8,
      sources: {
        osm: {
          type: "raster",
          tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
          tileSize: 256,
          attribution: "© OpenStreetMap contributors",
        },
      },
      layers: [{ id: "osm-basemap", type: "raster", source: "osm" }],
    },
    center: [10.2, 56.0],
    zoom: 5,
    maxZoom: 16,
    attributionControl: true,
  });
  map.co2Bounds = manifest.bounds;
  map.addControl(new maplibregl.NavigationControl(), "top-right");
  map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-left");
  map.once("load", () => {
    map.addSource("cost-surface", {
      type: "image",
      url: manifest.cost_image,
      coordinates: manifest.bounds,
    });
    map.addLayer({
      id: "cost-surface-layer",
      type: "raster",
      source: "cost-surface",
      paint: {
        "raster-opacity": manifest.cost_opacity,
        "raster-fade-duration": 0,
      },
    });
    document.getElementById("cost-toggle").addEventListener("change", (event) => {
      map.setLayoutProperty(
        "cost-surface-layer",
        "visibility",
        event.target.checked ? "visible" : "none",
      );
    });
    setupInputLayers(map, manifest.layers);
    setupRoutes(map, manifest);
    map.fitBounds(
      [
        manifest.bounds[3],
        manifest.bounds[1],
      ],
      { padding: 35, duration: 0 },
    );
    loadingElement.classList.add("hidden");
  });
  map.on("error", (event) => {
    if (event.error) setStatus(`A map layer could not be loaded: ${event.error.message}`, "error");
  });
}

document.getElementById("panel-toggle").addEventListener("click", (event) => {
  const hidden = sidebar.classList.toggle("sidebar-hidden");
  event.currentTarget.setAttribute("aria-expanded", String(!hidden));
  window.setTimeout(() => window.dispatchEvent(new Event("resize")), 180);
});

startMap();
