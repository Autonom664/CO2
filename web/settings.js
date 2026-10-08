// Model settings panel: lets the user change layer treatment and weights,
// model parameters and sites, and save or load scenarios. Results are
// computed by the browser engine (engine/), which reads the same scenario.

import {
  ABOUT_TEXT, ARCGIS_GLOSSARY, GROUPS, GROUP_RULE_HELP, LAYERS, PARAMETERS, WEIGHT_SCALE_HELP,
} from "./engine/labels.js";
import { EXPERIMENTS } from "./engine/experiments.js";
import { initModelUi } from "./model_ui.js";
import {
  defaultScenario, describeChanges, loadLocal, reconcile, saveLocal, sitesFromCsv, sitesToCsv,
} from "./engine/scenario.js";

const state = {
  config: null,
  defaults: null,
  scenario: null,
  listeners: new Set(),
  siteMarkers: [],
  addingSite: null,
};

const TABS = [
  ["layers", "Layers & weights"],
  ["model", "Model"],
  ["sites", "Sites"],
  ["sensitivity", "Sensitivity"],
  ["scenarios", "Scenarios"],
  ["learn", "Learn"],
  ["help", "Help"],
];

function element(tag, attributes = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attributes)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (value === true) node.setAttribute(key, "");
    else node.setAttribute(key, value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function labelFor(name) {
  return LAYERS[name]?.label || PARAMETERS[name]?.label || name;
}

function help(text, extra) {
  return element("details", { class: "help" },
    element("summary", { "aria-label": "Explain" }, "?"),
    element("p", {}, text),
    extra ? element("p", { class: "muted" }, extra) : null);
}

function download(name, text, type) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const link = element("a", { href: url, download: name });
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function pickFile(accept) {
  return new Promise((resolve) => {
    const input = element("input", { type: "file", accept });
    input.addEventListener("change", () => resolve(input.files?.[0] || null));
    input.click();
  });
}

// ---- run-time estimate --------------------------------------------------

// Seconds per full cost-distance run on the 250 m grid: 1.1 s measured on a
// 2026 laptop; replaced by this browser's own timing after the first Run.
const TIMING_KEY = "co2-routing-seconds-per-accumulation";
const COST_SURFACE_SECONDS = 2;

function secondsPerAccumulation() {
  try {
    const stored = Number(localStorage.getItem(TIMING_KEY));
    if (stored > 0) return { seconds: stored, measured: true };
  } catch {
    // Storage blocked: use the default.
  }
  return { seconds: 1.1, measured: false };
}

export function recordAccumulationSeconds(seconds) {
  try {
    localStorage.setItem(TIMING_KEY, String(seconds));
  } catch {
    // Storage blocked: the estimate stays at the default.
  }
  updateRunEstimate();
}

function runEstimate() {
  const sites = state.scenario.sites.filter((site) => site.enabled);
  const sources = sites.filter((site) => site.role === "source").length;
  const { seconds, measured } = secondsPerAccumulation();
  const routes = sources * seconds;
  const network = sites.length * seconds;
  const total = COST_SURFACE_SECONDS + routes + network;
  return { sources, sites: sites.length, seconds, measured, routes, network, total };
}

function updateRunEstimate() {
  const target = document.getElementById("settings-run-status");
  if (!target || !state.scenario) return;
  const e = runEstimate();
  const round = (value) => (value < 10 ? value.toFixed(1) : Math.round(value));
  target.textContent = `Recalculation takes about ${round(e.total)} s in this browser`
    + (e.measured ? " (measured here)." : " (estimate until the first run).");
  target.title =
    `Cost surface ≈ ${COST_SURFACE_SECONDS} s; routes: ${e.sources} sources × ${round(e.seconds)} s; ` +
    `network: ${e.sites} sites × ${round(e.seconds)} s. The map stays usable while it runs.`;
}

// ---- state changes ------------------------------------------------------

function changed({ rerender = false } = {}) {
  saveLocal(state.scenario);
  const count = describeChanges(state.scenario, state.defaults, labelFor).length;
  const badge = document.getElementById("settings-changes");
  badge.textContent = count ? `${count} change${count === 1 ? "" : "s"}` : "Published model";
  badge.classList.toggle("modified", count > 0);
  document.getElementById("settings-stale").hidden = false;
  updateRunEstimate();
  if (rerender) renderActiveTab();
  for (const listener of state.listeners) listener(state.scenario);
}

export function onScenarioChange(listener) {
  state.listeners.add(listener);
}

export function currentScenario() {
  return state.scenario;
}

export function markResultsCurrent() {
  document.getElementById("settings-stale").hidden = true;
}

// ---- tabs ---------------------------------------------------------------

function numberInput(value, { min = 0, max = 10, step = 0.5, disabled = false, onChange }) {
  const range = element("input", { type: "range", min, max, step, value, disabled });
  const box = element("input", { type: "number", min, max, step, value, disabled, class: "number" });
  const sync = (source, target) => {
    const number = Number(source.value);
    if (!Number.isFinite(number)) return;
    target.value = String(number);
    onChange(number);
  };
  range.addEventListener("input", () => sync(range, box));
  box.addEventListener("change", () => sync(box, range));
  return element("span", { class: "number-control" }, range, box);
}

function layersTab() {
  const filter = element("input", {
    type: "search", placeholder: "Find a layer…", class: "layer-search", "aria-label": "Find a layer",
  });
  const sections = [];
  for (const group of GROUPS) {
    const names = Object.keys(state.scenario.layers).filter((name) => (LAYERS[name]?.group || "land") === group.id);
    if (!names.length) continue;
    const rows = names.map((name) => {
      const layer = state.scenario.layers[name];
      const base = state.defaults.layers[name];
      const info = LAYERS[name] || {};
      const weight = numberInput(layer.weight, {
        disabled: layer.treatment !== "cost",
        onChange: (value) => { layer.weight = value; row.classList.toggle("modified", isModified()); changed(); },
      });
      const treatment = element("select", { "aria-label": `${info.label || name}: treatment` },
        ...[["cost", "Cost"], ["barrier", "Barrier"], ["ignore", "Ignore"]].map(([value, text]) =>
          element("option", { value, selected: layer.treatment === value }, text)));
      treatment.addEventListener("change", () => {
        layer.treatment = treatment.value;
        for (const input of weight.querySelectorAll("input")) input.disabled = layer.treatment !== "cost";
        row.classList.toggle("modified", isModified());
        changed();
      });
      const isModified = () => layer.treatment !== base.treatment || layer.weight !== base.weight;
      const row = element("div", { class: `layer-row${isModified() ? " modified" : ""}`, "data-layer": name },
        element("div", { class: "layer-name" },
          element("span", {}, info.label || name),
          help(info.help || "", [info.source && `Source: ${info.source}`, info.ref && `Published practice: ${info.ref}`]
            .filter(Boolean).join(" · "))),
        treatment, weight);
      return row;
    });
    sections.push(element("details", { class: "settings-group", open: true },
      element("summary", {}, group.title, element("span", { class: "count" }, String(rows.length))), ...rows));
  }
  filter.addEventListener("input", () => {
    const query = filter.value.trim().toLowerCase();
    for (const row of document.querySelectorAll(".layer-row")) {
      const text = row.querySelector(".layer-name > span").textContent.toLowerCase() + " " + row.dataset.layer;
      row.hidden = Boolean(query) && !text.includes(query);
    }
    for (const group of document.querySelectorAll(".settings-group")) {
      group.hidden = ![...group.querySelectorAll(".layer-row")].some((row) => !row.hidden);
    }
  });
  return [
    element("p", { class: "muted" }, WEIGHT_SCALE_HELP),
    element("p", { class: "muted" }, "Cost: adds the weight. Barrier: routes cannot cross it. Ignore: the layer has no effect."),
    filter,
    ...sections,
  ];
}

function modelTab() {
  const p = state.scenario.params;
  const d = state.defaults.params;
  const row = (name, control, note) => element("div", { class: "param-row" },
    element("div", { class: "layer-name" }, element("span", {}, PARAMETERS[name]?.label || name),
      help(PARAMETERS[name]?.help || "", [PARAMETERS[name]?.ref && `Published practice: ${PARAMETERS[name].ref}`, note]
        .filter(Boolean).join(" · "))),
    control);
  const set = (object, key) => (value) => { object[key] = value; changed(); };
  const toggle = (object, key, label) => {
    const box = element("input", { type: "checkbox", checked: object[key] });
    box.addEventListener("change", () => { object[key] = box.checked; changed(); });
    return element("label", { class: "inline-check" }, box, label);
  };
  const groupRows = Object.entries(state.scenario.groups).map(([name, group]) => {
    const members = state.config.combine_groups[name]?.members || [];
    const select = element("select", { "aria-label": `${name} rule` },
      element("option", { value: "max", selected: group.rule === "max" }, "Highest only"),
      element("option", { value: "sum", selected: group.rule === "sum" }, "Add up"));
    select.addEventListener("change", () => { group.rule = select.value; changed(); });
    return element("div", { class: "param-row" },
      element("div", { class: "layer-name" }, element("span", {}, name.replaceAll("_", " ")),
        element("span", { class: "muted small" }, members.join(", "))),
      select);
  });
  return [
    element("h3", {}, "Base costs"),
    row("open_land", numberInput(p.open_land, { min: 0.1, max: 5, step: 0.1, onChange: set(p, "open_land") })),
    row("open_sea", numberInput(p.open_sea, { min: 0.1, max: 10, step: 0.1, onChange: set(p, "open_sea") }),
      `Published model: ${d.open_sea}`),
    row("landfall", numberInput(p.landfall, { min: 0, max: 30, step: 1, onChange: set(p, "landfall") })),
    row("parallel_factor", numberInput(p.parallel_factor, { min: 0.5, max: 1, step: 0.05, onChange: set(p, "parallel_factor") })),
    element("h3", {}, "People and safety"),
    row("dwelling_proximity", element("div", { class: "stack" },
      toggle(p.dwelling_proximity, "enabled", "On"),
      element("label", {}, "Distance (m) ", numberInput(p.dwelling_proximity.max_distance_m,
        { min: 0, max: 1000, step: 25, onChange: set(p.dwelling_proximity, "max_distance_m") })),
      element("label", {}, "Weight next to a building ", numberInput(p.dwelling_proximity.max_score,
        { onChange: set(p.dwelling_proximity, "max_score") })))),
    row("population", element("div", { class: "stack" },
      toggle(p.population, "enabled", "On"),
      element("label", {}, "Minimum weight ", numberInput(p.population.minimum, { onChange: set(p.population, "minimum") })),
      element("label", {}, "Maximum weight ", numberInput(p.population.maximum, { onChange: set(p.population, "maximum") })))),
    row("population_risk", element("div", { class: "stack" },
      toggle(p.population_risk, "enabled", "On"),
      element("label", {}, "People within 1 km, at least ", numberInput(p.population_risk.threshold_people,
        { min: 0, max: 5000, step: 10, onChange: set(p.population_risk, "threshold_people") })),
      element("label", {}, "Maximum weight ", numberInput(p.population_risk.maximum,
        { onChange: set(p.population_risk, "maximum") })))),
    row("buildings", numberInput(p.buildings_share, { min: 0.05, max: 1, step: 0.05, onChange: set(p, "buildings_share") }),
      "0.5 = a cell is blocked when half or more of it is built on."),
    element("h3", {}, "Overlapping layers"),
    element("p", { class: "muted" }, GROUP_RULE_HELP),
    ...groupRows,
  ];
}

function sitesTab() {
  const rows = state.scenario.sites.map((site) => {
    const enabled = element("input", { type: "checkbox", checked: site.enabled, "aria-label": `Use ${site.name}` });
    enabled.addEventListener("change", () => { site.enabled = enabled.checked; changed(); refreshSiteMarkers(); });
    const name = element("input", { type: "text", value: site.name, class: "site-name", "aria-label": "Site name" });
    name.addEventListener("change", () => { site.name = name.value.trim() || site.id; changed(); refreshSiteMarkers(); });
    const role = element("select", { "aria-label": `${site.name}: role` },
      element("option", { value: "source", selected: site.role === "source" }, "Emitter / hub"),
      element("option", { value: "storage", selected: site.role === "storage" }, "Storage"));
    role.addEventListener("change", () => { site.role = role.value; changed(); refreshSiteMarkers(); });
    const zoom = element("button", { type: "button", class: "link-button", title: "Zoom to site",
      onclick: () => window.co2Map?.flyTo({ center: [site.lon, site.lat], zoom: 10 }) }, "⌖");
    const remove = element("button", { type: "button", class: "link-button", title: "Delete site", onclick: () => {
      state.scenario.sites = state.scenario.sites.filter((other) => other !== site);
      changed({ rerender: true });
      refreshSiteMarkers();
    } }, "✕");
    return element("div", { class: `site-row ${site.role}` }, enabled, name, role, zoom, remove);
  });
  const addButton = (role, text) => element("button", { type: "button", onclick: () => startAddingSite(role) }, text);
  return [
    element("p", { class: "muted" },
      "Drag a site on the map to move it. Untick a site to leave it out without deleting it. " +
      "Sites snap to the nearest passable cell within 2 km."),
    element("div", { class: "button-row" },
      addButton("source", "+ Emitter"), addButton("storage", "+ Storage"),
      element("button", { type: "button", onclick: importSites }, "Import CSV…"),
      element("button", { type: "button", onclick: () =>
        download("sites.csv", sitesToCsv(state.scenario.sites), "text/csv") }, "Export CSV")),
    element("p", { id: "adding-site", class: "notice", hidden: !state.addingSite },
      "Click on the map to place the new site. Press Esc to cancel."),
    element("div", { class: "site-list" }, ...rows),
  ];
}

function sensitivityTab() {
  return [
    element("p", {}, "Sensitivity shows how much the routes depend on each weight."),
    element("p", { class: "muted" },
      "One-click tests (vary a group of weights by a percentage and compare the routes) become " +
      "available once the browser model is loaded."),
    element("div", { id: "sensitivity-body" }),
  ];
}

function scenariosTab() {
  const name = element("input", { type: "text", value: state.scenario.name, "aria-label": "Scenario name" });
  name.addEventListener("change", () => { state.scenario.name = name.value.trim() || "Unnamed scenario"; changed(); });
  const changes = describeChanges(state.scenario, state.defaults, labelFor);
  return [
    element("label", { class: "stack" }, "Scenario name", name),
    element("div", { class: "button-row" },
      element("button", { type: "button", onclick: () => download(
        `${state.scenario.name.replace(/[^\w-]+/g, "_") || "scenario"}.json`,
        JSON.stringify(state.scenario, null, 2), "application/json") }, "Save to file"),
      element("button", { type: "button", onclick: loadScenarioFile }, "Load file…"),
      element("button", { type: "button", class: "danger", onclick: () => {
        if (!confirm("Reset every setting and site to the published model?")) return;
        state.scenario = structuredClone(state.defaults);
        changed({ rerender: true });
        refreshSiteMarkers();
      } }, "Reset to published")),
    element("p", { class: "muted" },
      "Your settings are kept in this browser automatically. Save to a file to keep a scenario, " +
      "share it, or attach it to the thesis."),
    element("h3", {}, changes.length ? `Changes from the published model (${changes.length})` : "No changes from the published model"),
    element("ul", { class: "change-list" }, ...changes.map((line) => element("li", {}, line))),
  ];
}

function helpTab() {
  return [
    element("p", {}, ABOUT_TEXT),
    element("h3", {}, "How the model works"),
    element("p", {}, WEIGHT_SCALE_HELP),
    element("p", {}, "The route between two sites is the path with the lowest total cost, like ArcGIS Cost Path. " +
      "The network joins all sites with the cheapest set of links, like Optimal Region Connections."),
    element("h3", {}, "How long does a recalculation take?"),
    element("p", {}, "In this browser: seconds. The time shown next to Run is measured on this computer after the " +
      "first run. The browser works on a 250 m grid (about 4.5 million cells)."),
    element("p", {}, "The published 100 m model (28 million cells) is rebuilt with Python: about 25–30 minutes for " +
      "cost surface, routes, corridors, validation and map tiles, and several hours if all source data is " +
      "downloaded and prepared again. In ArcGIS Pro, expect several minutes per source at 100 m for all of Denmark."),
    element("h3", {}, "ArcGIS Pro equivalents"),
    element("table", { class: "glossary" },
      element("thead", {}, element("tr", {}, element("th", {}, "Here"), element("th", {}, "ArcGIS Pro"))),
      element("tbody", {}, ...ARCGIS_GLOSSARY.map(([here, arcgis]) =>
        element("tr", {}, element("td", {}, here), element("td", {}, arcgis))))),
    element("p", { class: "muted" }, "Weights are relative assumptions, not money. Data sources and licences: ",
      element("a", { href: "SOURCES.md" }, "SOURCES.md"), "."),
  ];
}

const WIKI_PAGES = [
  ["README.md", "Start here"],
  ["method.md", "How the routing works"],
  ["weights.md", "Every weight, and why"],
  ["sources.md", "Data sources"],
  ["data_preparation.md", "Data preparation"],
  ["modelbuilder.md", "Build it in ArcGIS Pro ModelBuilder (step by step)"],
  ["arcgis_recipe.md", "ArcGIS Pro recipe (overview)"],
  ["experiments.md", "Experiments"],
  ["decisions.md", "Design decisions"],
  ["validation.md", "Validation and sensitivity"],
  ["history.md", "How the model evolved (5 versions)"],
  ["references.md", "References (literature)"],
  ["faq.md", "Frequently asked questions"],
  ["glossary.md", "Glossary with ArcGIS terms"],
];

let markedModule = null;
async function renderMarkdown(text) {
  markedModule ??= await import("https://unpkg.com/marked@12.0.2/lib/marked.esm.js");
  return markedModule.marked.parse(text);
}

async function openWikiPage(file, title) {
  const dialog = document.getElementById("wiki-dialog") || document.body.appendChild(
    element("dialog", { id: "wiki-dialog", class: "wiki-dialog" },
      element("form", { method: "dialog", class: "wiki-close" }, element("button", { "aria-label": "Close" }, "✕")),
      element("article", { id: "wiki-body", class: "wiki-body" })));
  const body = document.getElementById("wiki-body");
  body.textContent = `Loading ${title}…`;
  dialog.showModal();
  try {
    const response = await fetch(`wiki/${file}`, { cache: "no-cache" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    // The wiki is our own Markdown, written in this repository.
    body.innerHTML = await renderMarkdown(await response.text());
    for (const link of body.querySelectorAll("a[href$='.md']")) {
      const target = link.getAttribute("href");
      if (target.includes("/")) continue;
      link.addEventListener("click", (event) => {
        event.preventDefault();
        openWikiPage(target, link.textContent);
      });
    }
  } catch (error) {
    body.textContent = `This page is not available yet (${error.message}).`;
  }
}

function learnTab() {
  const experiments = EXPERIMENTS.map((experiment) => element("div", { class: "experiment" },
    element("strong", {}, experiment.title),
    element("p", { class: "muted" }, experiment.question),
    element("details", {}, element("summary", {}, "What to look for"), element("p", {}, experiment.lookFor)),
    element("button", { type: "button", onclick: () => {
      experiment.apply(state.scenario);
      state.scenario.name = `Experiment: ${experiment.title}`;
      changed();
      refreshSiteMarkers();
      document.getElementById("settings-stale").scrollIntoView({ behavior: "smooth" });
    } }, "Try it")));
  return [
    element("p", {}, "The best way to understand a least-cost model is to change it and see what moves. " +
      "Each experiment changes your current settings; press Run afterwards. " +
      "Scenarios → Reset to published takes you back."),
    element("h3", {}, "Wiki"),
    element("ul", { class: "wiki-links" }, ...WIKI_PAGES.map(([file, title]) => element("li", {},
      element("a", { href: `wiki/${file}`, onclick: (event) => { event.preventDefault(); openWikiPage(file, title); } }, title)))),
    element("h3", {}, "ArcGIS Pro"),
    element("p", {}, "Rebuild the model in ModelBuilder with the starter kit: every layer as an aligned 100 m raster, " +
      "the sites and published results in a File Geodatabase, and the weights table. ",
      element("a", { href: "downloads/co2_arcgis_starter_kit.zip", download: "" }, "Download the ArcGIS starter kit (zip)"),
      ". Then follow the ModelBuilder guide above."),
    element("h3", {}, "Try this"),
    ...experiments,
  ];
}

const RENDERERS = {
  layers: layersTab, model: modelTab, sites: sitesTab,
  sensitivity: sensitivityTab, scenarios: scenariosTab, learn: learnTab, help: helpTab,
};
let activeTab = "layers";

function renderActiveTab() {
  const body = document.getElementById("settings-body");
  body.replaceChildren(...RENDERERS[activeTab]());
  for (const button of document.querySelectorAll(".settings-tabs button")) {
    button.setAttribute("aria-selected", String(button.dataset.tab === activeTab));
  }
}

// ---- files --------------------------------------------------------------

async function loadScenarioFile() {
  const file = await pickFile(".json,application/json");
  if (!file) return;
  let parsed;
  try {
    parsed = JSON.parse(await file.text());
  } catch {
    alert("This file is not valid JSON.");
    return;
  }
  const { scenario, notes } = reconcile(parsed, state.defaults);
  state.scenario = scenario;
  changed({ rerender: true });
  refreshSiteMarkers();
  if (notes.length) alert(`Loaded "${scenario.name}".\n\n${notes.join("\n")}`);
}

async function importSites() {
  const file = await pickFile(".csv,text/csv");
  if (!file) return;
  const { sites, errors } = sitesFromCsv(await file.text());
  if (!sites.length) {
    alert(errors.join("\n") || "No sites found.");
    return;
  }
  const replace = confirm(`${sites.length} sites found.\n\nOK = replace all current sites\nCancel = add them to the current sites`);
  const taken = new Set(replace ? [] : state.scenario.sites.map((site) => site.id));
  for (const site of sites) {
    let id = site.id;
    for (let n = 2; taken.has(id); n++) id = `${site.id}_${n}`;
    site.id = id;
    taken.add(id);
  }
  state.scenario.sites = replace ? sites : [...state.scenario.sites, ...sites];
  changed({ rerender: true });
  refreshSiteMarkers();
  if (errors.length) alert(errors.join("\n"));
}

// ---- sites on the map ---------------------------------------------------

function refreshSiteMarkers() {
  for (const marker of state.siteMarkers) marker.remove();
  state.siteMarkers = [];
  const map = window.co2Map;
  if (!map || !document.getElementById("settings-panel").classList.contains("open") || activeTab !== "sites") return;
  for (const site of state.scenario.sites) {
    const dot = element("div", {
      class: `site-marker ${site.role}${site.enabled ? "" : " disabled"}`, title: site.name,
    });
    const marker = new maplibregl.Marker({ element: dot, draggable: true })
      .setLngLat([site.lon, site.lat])
      .addTo(map);
    marker.on("dragend", () => {
      const { lng, lat } = marker.getLngLat();
      site.lon = Number(lng.toFixed(5));
      site.lat = Number(lat.toFixed(5));
      changed();
    });
    state.siteMarkers.push(marker);
  }
}

function startAddingSite(role) {
  state.addingSite = role;
  document.getElementById("adding-site").hidden = false;
  window.co2Map.getCanvas().style.cursor = "crosshair";
}

function stopAddingSite() {
  state.addingSite = null;
  const notice = document.getElementById("adding-site");
  if (notice) notice.hidden = true;
  if (window.co2Map) window.co2Map.getCanvas().style.cursor = "";
}

function handleMapClick(event) {
  if (!state.addingSite) return;
  const role = state.addingSite;
  const name = prompt(`Name of the new ${role === "storage" ? "storage site" : "emitter / hub"}:`);
  stopAddingSite();
  if (!name) return;
  const taken = new Set(state.scenario.sites.map((site) => site.id));
  let id = name.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "") || "site";
  for (let n = 2, base = id; taken.has(id); n++) id = `${base}_${n}`;
  state.scenario.sites.push({
    id, name, role, enabled: true,
    lon: Number(event.lngLat.lng.toFixed(5)), lat: Number(event.lngLat.lat.toFixed(5)),
  });
  changed({ rerender: true });
  refreshSiteMarkers();
}

// ---- setup --------------------------------------------------------------

function buildPanel() {
  const panel = element("aside", { id: "settings-panel", class: "settings-panel", "aria-label": "Model settings" },
    element("header", { class: "settings-header" },
      element("div", {},
        element("h2", {}, "Model settings"),
        element("span", { id: "settings-changes", class: "changes-badge" }, "Published model")),
      element("button", { type: "button", class: "close", "aria-label": "Close settings", onclick: () => togglePanel(false) }, "✕")),
    element("div", { id: "settings-stale", class: "notice", hidden: true },
      element("strong", {}, "Settings changed. "),
      "Press Run to recalculate the routes in this browser (see the time estimate below). ",
      element("details", { class: "inline-details" },
        element("summary", {}, "Why is it fast here, and slow in the full model?"),
        element("p", {},
          "The browser recalculates on a 250 m grid (about 4.5 million cells) in seconds. The published " +
          "routes use a 100 m grid (28 million cells) and are rebuilt with Python: about 25–30 minutes " +
          "for cost surface, routes, corridors, validation and map tiles, and several hours if the source " +
          "data must be downloaded and prepared again. The 100 m routes stay on the map as the reference."),
        element("p", {},
          "In ArcGIS Pro the same steps are Weighted Sum (cost surface), Distance Accumulation (per " +
          "source) and Optimal Path As Line. Expect minutes per source at 100 m for all of Denmark."))),
    element("nav", { class: "settings-tabs", role: "tablist" },
      ...TABS.map(([id, text]) => element("button", {
        type: "button", role: "tab", "data-tab": id, "aria-selected": String(id === activeTab),
        onclick: () => { activeTab = id; stopAddingSite(); renderActiveTab(); refreshSiteMarkers(); },
      }, text))),
    element("div", { id: "settings-body", class: "settings-body" }),
    element("footer", { class: "settings-footer" },
      element("button", { type: "button", id: "settings-run", class: "primary", disabled: true,
        title: "Available once the browser model data is loaded" }, "Run"),
      element("span", { id: "settings-run-status", class: "muted" }, "")));
  document.querySelector(".workspace").append(panel);
}

const panelOpenListeners = new Set();

function togglePanel(open) {
  const panel = document.getElementById("settings-panel");
  const isOpen = open ?? !panel.classList.contains("open");
  if (isOpen) for (const listener of panelOpenListeners) listener();
  panel.classList.toggle("open", isOpen);
  document.getElementById("settings-toggle").setAttribute("aria-expanded", String(isOpen));
  if (!isOpen) stopAddingSite();
  refreshSiteMarkers();
}

async function fetchJson(url) {
  const response = await fetch(url, { cache: "no-cache" });
  if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
  return response.json();
}

async function init() {
  const toggle = document.getElementById("settings-toggle");
  let config;
  let hotspots;
  try {
    [config, hotspots] = await Promise.all([
      fetchJson("data/model/config.json"),
      fetchJson("data/hotspots.geojson").then((data) => data.features).catch(() => []),
    ]);
  } catch (error) {
    toggle.disabled = true;
    toggle.title = "Model settings are not available in this build.";
    console.info("Model settings disabled:", error.message);
    return;
  }
  state.config = config;
  state.defaults = defaultScenario(config, hotspots);
  const { scenario } = reconcile(loadLocal() ?? state.defaults, state.defaults);
  state.scenario = scenario;
  buildPanel();
  renderActiveTab();
  changed();
  if (!describeChanges(state.scenario, state.defaults).length) markResultsCurrent();
  updateRunEstimate();
  toggle.addEventListener("click", () => togglePanel());
  document.addEventListener("keydown", (event) => { if (event.key === "Escape") stopAddingSite(); });
  window.co2Settings = {
    currentScenario, onScenarioChange, markResultsCurrent, togglePanel, recordAccumulationSeconds,
    config: () => state.config,
    onPanelOpen: (listener) => panelOpenListeners.add(listener),
  };
  const attach = () => {
    window.co2Map.on("click", handleMapClick);
    initModelUi(window.co2Settings);
  };
  if (window.co2Map) attach();
  else window.addEventListener("co2map-ready", attach, { once: true });
}

init();
