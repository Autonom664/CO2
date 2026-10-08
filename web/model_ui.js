// Connects the Model settings panel to the browser engine (engine/worker.js):
// loads the model pack, runs scenarios, draws the scenario routes and
// network, and explains the cost of the cell under the mouse.

import { LAYERS, PARAMETERS } from "./engine/labels.js";

const GROUP_TITLES = {
  wet_nature: "Wet and protected nature",
  forest_group: "Forest",
  people: "People and safety",
};
const KEY_LABELS = {
  open_land: "Open land", open_sea: "Open sea", landfall: "Landfall (shore crossing)",
  dwelling_proximity: "Near buildings", population: "Population density",
  population_risk: "CO₂ safety (people within 1 km)", natura2000: "Natura 2000",
  protected_nature: "Protected nature (§3, reserves)", urban_area: "Urban area",
  marine_cable_corridor: "Cable corridor (discount)",
};

let api = null;
let worker = null;
let ready = false;
let loading = null;
let running = false;
let hoverOn = false;
let explainId = 0;
let publishedBest = new Map();
let lastResult = null;

const $ = (id) => document.getElementById(id);
const fmt = (value, digits = 1) => Number(value).toFixed(digits).replace(/\.0$/, "");

function layerLabel(name) {
  return LAYERS[name]?.label || KEY_LABELS[name] || PARAMETERS[name]?.label || name.replaceAll("_", " ");
}

function setRunStatus(text) {
  const target = $("settings-run-status");
  if (target) target.textContent = text;
}

// ---- loading ------------------------------------------------------------

function ensureLoaded() {
  if (loading) return loading;
  worker = new Worker(new URL("./engine/worker.js", import.meta.url), { type: "module" });
  loading = new Promise((resolve, reject) => {
    worker.addEventListener("message", function onReady({ data }) {
      if (data.type === "ready") {
        ready = true;
        worker.removeEventListener("message", onReady);
        const mb = (data.bytes / 1e6).toFixed(1);
        setRunStatus(`Model data loaded (${mb} MB, ${data.grid.width} × ${data.grid.height} cells of 250 m).`);
        const run = $("settings-run");
        run.disabled = false;
        run.title = "Recalculate routes and network for your settings";
        resolve(data);
      } else if (data.type === "progress") {
        setRunStatus(`${data.stage} (${data.done}/${data.total})…`);
      } else if (data.type === "error") {
        const message = /HTTP 404/.test(data.message)
          ? "the model data has not been published on this site yet"
          : data.message;
        setRunStatus(`Model data could not be loaded: ${message}.`);
        loading = null; // allow a retry later
        reject(new Error(message));
      }
    });
  });
  worker.addEventListener("message", ({ data }) => {
    if (data.type === "explain") showExplanation(data);
  });
  worker.postMessage({ type: "load", base: new URL("./data/model", document.baseURI).href });
  return loading;
}

// ---- running ------------------------------------------------------------

async function runScenario() {
  if (running) return;
  await ensureLoaded();
  const scenario = api.currentScenario();
  const sites = scenario.sites.filter((s) => s.enabled);
  if (!sites.some((s) => s.role === "source") || !sites.some((s) => s.role === "storage")) {
    alert("Enable at least one emitter and one storage site in the Sites tab.");
    return;
  }
  running = true;
  const button = $("settings-run");
  button.disabled = true;
  button.textContent = "Running…";
  const maxSnapM = api.config().routing?.max_snap_distance_m ?? 2000;
  worker.postMessage({ type: "run", scenario, network: true, maxSnapM });
  const result = await new Promise((resolve) => {
    const onMessage = ({ data }) => {
      if (data.type === "progress") setRunStatus(`${data.stage} (${data.done + 1}/${data.total})…`);
      if (data.type === "result" || data.type === "error") {
        worker.removeEventListener("message", onMessage);
        resolve(data);
      }
    };
    worker.addEventListener("message", onMessage);
  });
  running = false;
  button.disabled = false;
  button.textContent = "Run";
  if (result.type === "error") {
    setRunStatus(`The run failed: ${result.message}`);
    return;
  }
  lastResult = result;
  api.recordAccumulationSeconds(result.timing.secondsPerAccumulation);
  api.markResultsCurrent();
  drawResult(result);
  renderSummary(result, scenario.name);
  setRunStatus(`Done in ${fmt(result.timing.total)} s (cost surface ${fmt(result.timing.costSeconds)} s, `
    + `${result.timing.accumulations} cost-distance runs at ${fmt(result.timing.secondsPerAccumulation, 2)} s).`);
}

// ---- drawing ------------------------------------------------------------

function drawResult(result) {
  const map = window.co2Map;
  const set = (id, data) => {
    if (map.getSource(id)) map.getSource(id).setData(data);
    else map.addSource(id, { type: "geojson", data });
  };
  set("scenario-routes", result.routes);
  set("scenario-network", result.network);
  if (!map.getLayer("scenario-routes-other")) {
    map.addLayer({
      id: "scenario-routes-other", type: "line", source: "scenario-routes",
      filter: ["!", ["get", "best"]],
      layout: { visibility: "none" },
      paint: { "line-color": "#ff8a00", "line-width": 1.2, "line-opacity": 0.55, "line-dasharray": [2, 2] },
    });
    map.addLayer({
      id: "scenario-network", type: "line", source: "scenario-network",
      paint: { "line-color": "#b0006e", "line-width": 2.5, "line-opacity": 0.85 },
    });
    map.addLayer({
      id: "scenario-routes-best", type: "line", source: "scenario-routes",
      filter: ["get", "best"],
      paint: { "line-color": "#ff8a00", "line-width": 3.5, "line-opacity": 0.95 },
    });
    map.on("click", "scenario-routes-best", (event) => routePopup(event));
    map.on("click", "scenario-routes-other", (event) => routePopup(event));
    for (const id of ["scenario-routes-best", "scenario-routes-other"]) {
      map.on("mouseenter", id, () => { map.getCanvas().style.cursor = "pointer"; });
      map.on("mouseleave", id, () => { map.getCanvas().style.cursor = ""; });
    }
  }
}

function routePopup(event) {
  const p = event.features[0].properties;
  new maplibregl.Popup({ maxWidth: "320px" })
    .setLngLat(event.lngLat)
    .setHTML(`<strong>Your scenario</strong><br>${p.from_name} → ${p.to_name}<br>`
      + `${fmt(p.length_km)} km · cost ${fmt(p.accumulated_cost, 0)} · ${fmt(p.km_open_sea)} km at sea<br>`
      + `Option ${p.rank} for this source${p.best ? " (best)" : ""}`)
    .addTo(window.co2Map);
}

function setVisible(ids, visible) {
  for (const id of ids) {
    if (window.co2Map.getLayer(id)) window.co2Map.setLayoutProperty(id, "visibility", visible ? "visible" : "none");
  }
}

function renderSummary(result, name) {
  const box = $("scenario-results");
  const best = result.routes.features.filter((f) => f.properties.best);
  const rows = best.map((f) => {
    const p = f.properties;
    const published = publishedBest.get(p.from_id);
    const changed = published && published.to_id !== p.to_id;
    return `<tr class="${changed ? "changed" : ""}"><td>${p.from_name}</td><td>${p.to_name}${changed
      ? `<br><span class="muted">was ${published.to_name}</span>` : ""}</td><td>${fmt(p.length_km, 0)} km</td></tr>`;
  }).join("");
  const changedCount = best.filter((f) => {
    const published = publishedBest.get(f.properties.from_id);
    return published && published.to_id !== f.properties.to_id;
  }).length;
  box.hidden = false;
  box.innerHTML = `
    <h3>Results: ${name}</h3>
    <p class="muted">Orange: your scenario (250 m). The published 100 m routes stay on the map for comparison.
    ${changedCount ? `<strong>${changedCount} source${changedCount > 1 ? "s" : ""} changed their best storage site.</strong>`
      : "Every source keeps its published best storage site."}</p>
    ${result.problems.length ? `<p class="notice">${result.problems.join("<br>")}</p>` : ""}
    <div class="result-toggles">
      <label><input type="checkbox" data-layers="scenario-routes-best" checked> Best routes</label>
      <label><input type="checkbox" data-layers="scenario-routes-other"> All options</label>
      <label><input type="checkbox" data-layers="scenario-network" checked> Network</label>
      <button type="button" id="scenario-download">Download GeoJSON</button>
    </div>
    <table class="result-table"><thead><tr><th>Source</th><th>Best storage</th><th>Length</th></tr></thead>
    <tbody>${rows}</tbody></table>`;
  for (const box of document.querySelectorAll(".result-toggles input")) {
    box.addEventListener("change", () => setVisible([box.dataset.layers], box.checked));
  }
  $("scenario-download").addEventListener("click", () => {
    const features = [
      ...result.routes.features.map((f) => ({ ...f, properties: { ...f.properties, layer: "route" } })),
      ...result.network.features.map((f) => ({ ...f, properties: { ...f.properties, layer: "network" } })),
    ];
    const blob = new Blob([JSON.stringify({ type: "FeatureCollection", name, features })], { type: "application/geo+json" });
    const link = Object.assign(document.createElement("a"), {
      href: URL.createObjectURL(blob), download: `${name.replace(/[^\w-]+/g, "_") || "scenario"}_routes.geojson`,
    });
    link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  });
}

// ---- hover explanation --------------------------------------------------

function explainBox() {
  let box = $("cost-explain");
  if (!box) {
    box = Object.assign(document.createElement("div"), { id: "cost-explain", className: "cost-explain" });
    box.hidden = true;
    document.querySelector(".map-wrap").append(box);
  }
  return box;
}

function showExplanation(data) {
  if (!hoverOn || data.requestId !== explainId) return;
  const box = explainBox();
  if (!data.available) { box.hidden = true; return; }
  if (data.outside) {
    box.innerHTML = "<strong>Outside the analysis area</strong><br><span class='muted'>Routes cannot go here.</span>";
    box.hidden = false;
    return;
  }
  const s = data.costScale || 1;
  const w = (value) => fmt(value / s, 2);
  const lines = [];
  if (data.blocked) {
    const reason = LAYERS[data.blocked] ? layerLabel(data.blocked) : data.blocked;
    lines.push(`<div class="explain-head blocked">Barrier: ${reason}</div>`,
      "<div class='muted'>Routes cannot cross this cell. You can change this in Model settings → Layers & weights.</div>");
  } else {
    const multiple = data.cost / data.openLand;
    lines.push(`<div class="explain-head">Cost ${w(data.cost)} <span class="muted">= ${fmt(multiple, 1)}× open land</span></div>`);
    for (const step of data.steps) {
      if (step.step === "base") {
        lines.push(`<div>${layerLabel(step.label)} <b>${w(step.value)}</b></div>`);
      } else if (step.step === "group") {
        const rule = step.rule === "sum" ? "added up" : "highest only";
        const parts = step.parts.map((part) => `${layerLabel(part.layer || part.key)} ${w(part.value)}`).join(", ");
        lines.push(`<div>+ ${GROUP_TITLES[step.label] || layerLabel(step.label)} <b>${w(step.value)}</b>`
          + ` <span class="muted">(${rule}: ${parts})</span></div>`);
      } else if (step.step === "layer") {
        lines.push(`<div>+ ${layerLabel(step.layer || step.label)} <b>${w(step.value)}</b></div>`);
      } else if (step.step === "discount") {
        lines.push(`<div>− ${layerLabel(step.layer || step.label)} <b>${w(-step.value)}</b></div>`);
      } else if (step.step === "parallel") {
        lines.push(`<div>× ${fmt(step.factor, 2)} alongside an existing line <b>${w(step.value)}</b></div>`);
      }
    }
  }
  const c = data.context;
  if (c) {
    const facts = [];
    facts.push(c.isLand ? "Land" : "Sea");
    if (c.buildingDistance !== null) facts.push(c.buildingDistance === 0 ? "buildings in this cell" : `nearest building ${fmt(c.buildingDistance, 0)} m`);
    if (c.buildingShare > 0) facts.push(`${fmt(c.buildingShare * 100, 0)}% built over`);
    if (c.population1km !== null && c.population1km > 0) facts.push(`${fmt(c.population1km, 0)} people within 1 km`);
    if (c.landfall) facts.push("coastline cell");
    if (c.parallel) facts.push("50–300 m from a power line or gas pipeline");
    lines.push(`<div class="explain-facts">${facts.join(" · ")}</div>`);
  }
  box.innerHTML = lines.join("");
  box.hidden = false;
}

let pendingHover = null;
function onMouseMove(event) {
  if (!hoverOn || !ready) return;
  pendingHover = event.lngLat;
  if (onMouseMove.scheduled) return;
  onMouseMove.scheduled = true;
  setTimeout(() => {
    onMouseMove.scheduled = false;
    if (!pendingHover) return;
    explainId += 1;
    worker.postMessage({
      type: "explain", requestId: explainId, lon: pendingHover.lng, lat: pendingHover.lat,
      scenario: api.currentScenario(),
    });
  }, 60);
}

async function setHover(on) {
  hoverOn = on;
  $("hover-toggle").setAttribute("aria-pressed", String(on));
  $("hover-toggle").classList.toggle("active", on);
  if (!on) { explainBox().hidden = true; return; }
  const box = explainBox();
  box.innerHTML = "Loading model data for explanations…";
  box.hidden = false;
  try {
    await ensureLoaded();
    box.innerHTML = "Move the mouse over the map to see why a place costs what it does.";
  } catch (error) {
    box.innerHTML = `Explanations are not available: ${error.message}`;
  }
}

// ---- setup --------------------------------------------------------------

export async function initModelUi(settingsApi) {
  api = settingsApi;
  const map = window.co2Map;
  const footer = document.querySelector(".settings-footer");
  footer.insertAdjacentHTML("beforebegin", '<section id="scenario-results" class="scenario-results" hidden></section>');
  $("settings-run").addEventListener("click", runScenario);

  const toggle = Object.assign(document.createElement("button"), {
    id: "hover-toggle", type: "button", className: "hover-toggle",
    textContent: "Explain cost under the mouse",
    title: "Show which layers, distances and people make up the cost at the mouse position",
  });
  toggle.setAttribute("aria-pressed", "false");
  toggle.addEventListener("click", () => setHover(!hoverOn));
  document.querySelector(".map-wrap").append(toggle);
  map.on("mousemove", onMouseMove);
  map.getCanvas().addEventListener("mouseleave", () => { if (hoverOn) explainBox().hidden = true; });

  settingsApi.onPanelOpen(() => ensureLoaded().catch(() => {}));
  try {
    const routes = await (await fetch("data/routes.geojson", { cache: "no-cache" })).json();
    const sorted = routes.features.sort((a, b) => a.properties.accumulated_cost - b.properties.accumulated_cost);
    for (const feature of sorted) {
      if (!publishedBest.has(feature.properties.from_id)) publishedBest.set(feature.properties.from_id, feature.properties);
    }
  } catch {
    // Without published routes, results are shown without the comparison.
  }
}
