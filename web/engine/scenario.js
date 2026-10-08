// Scenario = everything Lauge can change: how each layer is treated, its
// weight, the model settings and the sites. Built from the published config
// (the flattened costs.yaml), so the default scenario reproduces the
// published model. Plain JSON, so it can be saved, loaded and attached to
// the thesis.

export const SCENARIO_VERSION = 1;
const STORAGE_KEY = "co2-routing-scenario";

function numeric(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

/** Default scenario from the published config and hotspot features. */
export function defaultScenario(config, hotspots = []) {
  const costs = config.costs || {};
  const barriers = new Set(config.barriers || []);
  const layers = {};
  for (const [name, layer] of Object.entries(config.layers || {})) {
    const key = layer.cost;
    // Barrier layers have no configured weight; 10 is the starting weight
    // if the user switches one to "Cost".
    layers[name] = {
      treatment: barriers.has(key) ? "barrier" : "cost",
      weight: numeric(costs[key], barriers.has(key) ? 10 : 0),
    };
  }
  const groups = {};
  for (const [name, group] of Object.entries(config.combine_groups || {})) {
    groups[name] = { rule: group.rule || "max" };
  }
  const proximity = costs.dwelling_proximity || {};
  const population = costs.population || {};
  const risk = costs.population_risk || {};
  return {
    version: SCENARIO_VERSION,
    name: "Published model",
    params: {
      open_land: numeric(costs.open_land, 1),
      open_sea: numeric(costs.open_sea, 2),
      landfall: config.landfall?.enabled ? numeric(costs[config.landfall.cost], 0) : 0,
      parallel_factor: config.parallel_corridor?.enabled
        ? numeric(config.parallel_corridor.factor, 1) : 1,
      dwelling_proximity: {
        enabled: proximity.enabled !== false,
        max_distance_m: numeric(proximity.max_distance_m, 200),
        max_score: numeric(proximity.max_score, 0),
      },
      population: {
        enabled: population.enabled !== false,
        min_per_cell: numeric(population.min_per_cell, 1),
        minimum: numeric(population.minimum, 0),
        maximum: numeric(population.maximum, 0),
      },
      population_risk: {
        enabled: risk.enabled === true,
        threshold_people: numeric(risk.threshold_people, 50),
        maximum: numeric(risk.maximum, 0),
      },
      buildings_share: 0.5,
    },
    layers,
    groups,
    sites: hotspots.map((feature) => ({
      id: String(feature.properties.id),
      name: String(feature.properties.name || feature.properties.id),
      role: feature.properties.role === "storage" ? "storage" : "source",
      lon: feature.geometry.coordinates[0],
      lat: feature.geometry.coordinates[1],
      enabled: true,
    })),
  };
}

/**
 * Bring a loaded scenario in line with the current published config: keep
 * the user's values for everything that still exists, take defaults for
 * anything new, and drop what no longer exists. Returns the scenario and a
 * list of human-readable notes about what was changed.
 */
export function reconcile(loaded, defaults) {
  const notes = [];
  if (!loaded || typeof loaded !== "object") {
    return { scenario: structuredClone(defaults), notes: ["The file is not a scenario."] };
  }
  if (loaded.version !== SCENARIO_VERSION) {
    notes.push(`Scenario version ${loaded.version} differs from ${SCENARIO_VERSION}; values were matched by name.`);
  }
  const scenario = structuredClone(defaults);
  scenario.name = typeof loaded.name === "string" && loaded.name ? loaded.name : defaults.name;

  for (const [key, value] of Object.entries(loaded.params || {})) {
    if (!(key in scenario.params)) {
      notes.push(`Setting "${key}" no longer exists and was ignored.`);
    } else if (typeof scenario.params[key] === "object") {
      for (const [sub, subValue] of Object.entries(value || {})) {
        if (sub in scenario.params[key]) scenario.params[key][sub] = subValue;
      }
    } else {
      scenario.params[key] = numeric(value, scenario.params[key]);
    }
  }
  for (const [name, value] of Object.entries(loaded.layers || {})) {
    if (!(name in scenario.layers)) {
      notes.push(`Layer "${name}" is not in this model and was ignored.`);
      continue;
    }
    if (["cost", "barrier", "ignore"].includes(value.treatment)) {
      scenario.layers[name].treatment = value.treatment;
    }
    scenario.layers[name].weight = numeric(value.weight, scenario.layers[name].weight);
  }
  for (const [name, value] of Object.entries(loaded.groups || {})) {
    if (name in scenario.groups && ["max", "sum"].includes(value.rule)) {
      scenario.groups[name].rule = value.rule;
    }
  }
  if (Array.isArray(loaded.sites)) {
    scenario.sites = loaded.sites
      .filter((site) => Number.isFinite(site.lon) && Number.isFinite(site.lat))
      .map((site, index) => ({
        id: String(site.id || `site_${index + 1}`),
        name: String(site.name || site.id || `Site ${index + 1}`),
        role: site.role === "storage" ? "storage" : "source",
        lon: site.lon,
        lat: site.lat,
        enabled: site.enabled !== false,
      }));
  }
  return { scenario, notes };
}

/** Differences from the defaults, as short lines for the Scenarios tab. */
export function describeChanges(scenario, defaults, labelFor = (name) => name) {
  const lines = [];
  for (const [key, value] of Object.entries(scenario.params)) {
    const base = defaults.params[key];
    if (typeof value === "object") {
      for (const [sub, subValue] of Object.entries(value)) {
        if (subValue !== base[sub]) lines.push(`${labelFor(key)} ${sub}: ${base[sub]} → ${subValue}`);
      }
    } else if (value !== base) {
      lines.push(`${labelFor(key)}: ${base} → ${value}`);
    }
  }
  for (const [name, layer] of Object.entries(scenario.layers)) {
    const base = defaults.layers[name];
    if (!base) continue;
    if (layer.treatment !== base.treatment) lines.push(`${labelFor(name)}: ${base.treatment} → ${layer.treatment}`);
    if (layer.weight !== base.weight) lines.push(`${labelFor(name)} weight: ${base.weight} → ${layer.weight}`);
  }
  for (const [name, group] of Object.entries(scenario.groups)) {
    if (group.rule !== defaults.groups[name]?.rule) {
      lines.push(`Group ${name}: ${defaults.groups[name]?.rule} → ${group.rule}`);
    }
  }
  const baseSites = new Map(defaults.sites.map((site) => [site.id, site]));
  for (const site of scenario.sites) {
    const base = baseSites.get(site.id);
    if (!base) lines.push(`Added site: ${site.name} (${site.role})`);
    else if (!site.enabled) lines.push(`Disabled site: ${site.name}`);
    else if (Math.abs(site.lon - base.lon) > 1e-6 || Math.abs(site.lat - base.lat) > 1e-6) {
      lines.push(`Moved site: ${site.name}`);
    }
  }
  for (const id of baseSites.keys()) {
    if (!scenario.sites.some((site) => site.id === id)) lines.push(`Removed site: ${baseSites.get(id).name}`);
  }
  return lines;
}

export function saveLocal(scenario) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(scenario));
  } catch {
    // Private windows or blocked storage: the scenario still works for this visit.
  }
}

export function loadLocal() {
  try {
    const text = localStorage.getItem(STORAGE_KEY);
    return text ? JSON.parse(text) : null;
  } catch {
    return null;
  }
}

/** Sites as CSV that opens in Excel and imports into ArcGIS Pro (XY Table To Point). */
export function sitesToCsv(sites) {
  const quote = (value) => `"${String(value).replaceAll('"', '""')}"`;
  const rows = ["id,name,role,lon,lat,enabled"];
  for (const site of sites) {
    rows.push([quote(site.id), quote(site.name), site.role, site.lon, site.lat, site.enabled].join(","));
  }
  return rows.join("\r\n") + "\r\n";
}

/** Parse a sites CSV: id,name,role,lon,lat[,enabled]; accepts ; separators. */
export function sitesFromCsv(text) {
  const lines = text.replace(/^﻿/, "").split(/\r?\n/).filter((line) => line.trim());
  if (!lines.length) return { sites: [], errors: ["The file is empty."] };
  const separator = lines[0].includes(";") && !lines[0].includes(",") ? ";" : ",";
  const split = (line) => {
    const cells = [];
    let cell = "";
    let quoted = false;
    for (let i = 0; i < line.length; i++) {
      const char = line[i];
      if (quoted) {
        if (char === '"' && line[i + 1] === '"') { cell += '"'; i++; }
        else if (char === '"') quoted = false;
        else cell += char;
      } else if (char === '"') quoted = true;
      else if (char === separator) { cells.push(cell); cell = ""; }
      else cell += char;
    }
    cells.push(cell);
    return cells.map((value) => value.trim());
  };
  const header = split(lines[0]).map((name) => name.toLowerCase());
  const column = (...names) => header.findIndex((name) => names.includes(name));
  const columns = {
    id: column("id"), name: column("name", "navn"), role: column("role", "type"),
    lon: column("lon", "longitude", "x"), lat: column("lat", "latitude", "y"),
    enabled: column("enabled"),
  };
  const errors = [];
  if (columns.lon < 0 || columns.lat < 0) {
    return { sites: [], errors: ["The CSV needs lon and lat columns (WGS84 degrees)."] };
  }
  const sites = [];
  lines.slice(1).forEach((line, index) => {
    const cells = split(line);
    const number = (i) => Number(String(cells[i] ?? "").replace(",", "."));
    const lon = number(columns.lon);
    const lat = number(columns.lat);
    if (!Number.isFinite(lon) || !Number.isFinite(lat) || lon < 3 || lon > 20 || lat < 53 || lat > 60) {
      errors.push(`Row ${index + 2}: coordinates outside Denmark's area, skipped.`);
      return;
    }
    const role = String(cells[columns.role] ?? "").toLowerCase();
    sites.push({
      id: cells[columns.id] || `site_${index + 1}`,
      name: cells[columns.name] || cells[columns.id] || `Site ${index + 1}`,
      role: role.startsWith("stor") || role.startsWith("lager") ? "storage" : "source",
      lon,
      lat,
      enabled: columns.enabled < 0 || !/^(false|0|no|nej)$/i.test(cells[columns.enabled] ?? ""),
    });
  });
  return { sites, errors };
}
