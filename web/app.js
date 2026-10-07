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

function makeLayerToggle(id, label, color, checked, onChange) {
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
  wrapper.dataset.layerId = id;
  return wrapper;
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

function addGeoJsonLayer(map, layer) {
  if (map.getSource(layer.id)) return;
  map.addSource(layer.id, { type: "geojson", data: layer.url });
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
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 4, 4, 9, 8],
        "circle-color": [
          "match",
          ["get", "role"],
          "storage",
          "#2878a8",
          "#e28b24",
        ],
        "circle-stroke-color": "#17333a",
        "circle-stroke-width": 2,
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
        .filter(([key]) => key.startsWith("km_"))
        .map(([key, value]) => [
          key.slice(3).replaceAll("_", " "),
          `${Number(value).toFixed(2)} km`,
        ]),
    ].filter(([, value]) => value !== "" && value !== null && value !== undefined);
    rows = `<table class="popup-table">${entries.map(([key, value]) =>
      `<tr><td>${escapeHtml(key)}</td><td>${escapeHtml(value)}</td></tr>`
    ).join("")}</table>`;
  } else {
    const details = [
      ["Role", properties.role],
      ["Type", properties.site_type],
      ["Project status", properties.project_status],
      ["Location basis", properties.location_basis],
    ].filter(([, value]) => value);
    rows = `<table class="popup-table">${details.map(([key, value]) =>
      `<tr><td>${escapeHtml(key)}</td><td>${escapeHtml(value)}</td></tr>`
    ).join("")}</table>`;
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
      ));
    }
    container.appendChild(section);
  }
}

function setupRoutes(map, routeLayers) {
  const section = document.getElementById("routes-section");
  const container = document.getElementById("route-layers");
  if (!routeLayers.length) return;
  section.hidden = false;
  for (const layer of routeLayers) {
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
        if (visible) addGeoJsonLayer(map, layer);
        const mapLayerId = routeLayerIds[layer.id];
        if (map.getLayer(mapLayerId)) {
          map.setLayoutProperty(mapLayerId, "visibility", visible ? "visible" : "none");
        }
      },
    ));
    addGeoJsonLayer(map, layer);
    const mapLayerId = routeLayerIds[layer.id];
    if (!defaultVisible) {
      map.setLayoutProperty(mapLayerId, "visibility", "none");
    }
  }
  for (const layerId of ["pair-routes", "mst-network", "hotspots"]) {
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
    setupRoutes(map, manifest.route_layers);
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
