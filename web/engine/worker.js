// Background worker: holds the model pack, recomputes the cost surface and
// routes for a scenario, renders overlays and explains single cells, so the
// map stays responsive. Messages: load, run, explain, corridor.

import { browserReader, loadPack } from "./pack.js";
import { cellCost, computeCost, prepareModel, prepareScales } from "./cost.js";
import { accumulate, nearestPassable, traceback } from "./paths.js";
import { fromUtm32, toUtm32 } from "./utm.js";

let pack = null;
let current = null; // last run: { scenario, cost, model, scales, sites }
let explainModel = null; // { key, model, scales } for hover, follows the live settings

const post = (message, transfer) => self.postMessage(message, transfer || []);

function gridGeometry() {
  const [x0, dx, , y0, , dy] = pack.grid.transform_gdal;
  return { x0, dx, y0, dy, width: pack.grid.width, height: pack.grid.height };
}

function cellAt(lon, lat) {
  const g = gridGeometry();
  const [x, y] = toUtm32(lon, lat);
  const col = Math.floor((x - g.x0) / g.dx);
  const row = Math.floor((y - g.y0) / g.dy);
  if (row < 0 || col < 0 || row >= g.height || col >= g.width) return -1;
  return row * g.width + col;
}

function cellCentreLonLat(cell) {
  const g = gridGeometry();
  const row = Math.floor(cell / g.width);
  const col = cell - row * g.width;
  return fromUtm32(g.x0 + (col + 0.5) * g.dx, g.y0 + (row + 0.5) * g.dy);
}

function pathLengthKm(path) {
  const g = gridGeometry();
  let metres = 0;
  for (let i = 1; i < path.length; i++) {
    const a = path[i - 1];
    const b = path[i];
    metres += (Math.abs(a - b) === 1 || Math.abs(a - b) === g.width ? 1 : Math.SQRT2) * g.dx;
  }
  return metres / 1000;
}

function seaKm(path) {
  const seaBit = current.model.derived.sea.bit;
  const g = gridGeometry();
  let metres = 0;
  for (let i = 1; i < path.length; i++) {
    const cell = path[i];
    const isSea = seaBit < 32 ? (pack.presenceLo[cell] >>> seaBit) & 1 : (pack.presenceHi[cell] >>> (seaBit - 32)) & 1;
    if (isSea) metres += (Math.abs(cell - path[i - 1]) === 1 || Math.abs(cell - path[i - 1]) === g.width ? 1 : Math.SQRT2) * g.dx;
  }
  return metres / 1000;
}

// Prim's minimum spanning tree over a dense matrix of pair costs.
function minimumSpanningTree(count, pairCost) {
  const inTree = new Array(count).fill(false);
  const best = new Array(count).fill(Infinity);
  const parent = new Array(count).fill(-1);
  best[0] = 0;
  const edges = [];
  for (let step = 0; step < count; step++) {
    let next = -1;
    for (let i = 0; i < count; i++) if (!inTree[i] && (next < 0 || best[i] < best[next])) next = i;
    if (next < 0 || best[next] === Infinity) break;
    inTree[next] = true;
    if (parent[next] >= 0) edges.push([parent[next], next]);
    for (let i = 0; i < count; i++) {
      const c = pairCost(next, i);
      if (!inTree[i] && c < best[i]) { best[i] = c; parent[i] = next; }
    }
  }
  return edges;
}

async function run({ scenario, network, maxSnapM }) {
  const started = performance.now();
  post({ type: "progress", stage: "Building the cost surface", done: 0, total: 1 });
  const { cost, model, scales } = computeCost(pack, scenario);
  const costSeconds = (performance.now() - started) / 1000;
  current = { scenario, cost, model, scales };

  const g = gridGeometry();
  const maxCells = Math.ceil((maxSnapM ?? 2000) / g.dx);
  const enabled = scenario.sites.filter((site) => site.enabled);
  const sites = [];
  const problems = [];
  for (const site of [...enabled.filter((s) => s.role === "source"), ...enabled.filter((s) => s.role === "storage")]) {
    const cell = cellAt(site.lon, site.lat);
    if (cell < 0) { problems.push(`${site.name} is outside the analysis area.`); continue; }
    const row = Math.floor(cell / g.width);
    const snapped = nearestPassable(cost, g.width, g.height, row, cell - row * g.width, maxCells);
    if (snapped < 0) { problems.push(`${site.name}: no passable cell within ${maxSnapM} m.`); continue; }
    sites.push({ ...site, cell: snapped });
  }
  const sources = sites.filter((s) => s.role === "source");
  const storage = sites.filter((s) => s.role === "storage");
  const origins = network ? sites : sources;

  const pairs = new Map(); // "i|j" (i < j) -> { cost, path }
  const routeStarted = performance.now();
  for (let i = 0; i < origins.length; i++) {
    post({ type: "progress", stage: `Routing from ${origins[i].name}`, done: i, total: origins.length });
    const targets = sites.map((s) => s.cell);
    const { acc, prev } = accumulate(cost, g.width, g.height, origins[i].cell, { targets });
    const from = sites.indexOf(origins[i]);
    for (let to = 0; to < sites.length; to++) {
      if (to === from) continue;
      const key = from < to ? `${from}|${to}` : `${to}|${from}`;
      if (pairs.has(key)) continue;
      const end = sites[to].cell;
      if (!(acc[end] < Infinity)) { pairs.set(key, { cost: Infinity, path: [], from, to }); continue; }
      pairs.set(key, { cost: acc[end], path: traceback(prev, acc, end), from, to });
    }
  }
  const secondsPerAccumulation = (performance.now() - routeStarted) / 1000 / Math.max(1, origins.length);

  const feature = (pair, properties) => ({
    type: "Feature",
    properties: {
      ...properties,
      accumulated_cost: Number(pair.cost.toFixed(2)),
      length_km: Number(pathLengthKm(pair.path).toFixed(2)),
      km_open_sea: Number(seaKm(pair.path).toFixed(2)),
    },
    geometry: { type: "LineString", coordinates: pair.path.map(cellCentreLonLat) },
  });

  const routes = [];
  for (const source of sources) {
    const from = sites.indexOf(source);
    const options = storage
      .map((target) => {
        const to = sites.indexOf(target);
        return { target, pair: pairs.get(from < to ? `${from}|${to}` : `${to}|${from}`) };
      })
      .filter((option) => option.pair && option.pair.cost < Infinity)
      .sort((a, b) => a.pair.cost - b.pair.cost);
    if (!options.length) problems.push(`${source.name} cannot reach any storage site.`);
    options.forEach((option, rank) => {
      const pair = option.pair;
      // Draw the line from the source, even if it was traced from the storage end.
      const ordered = pair.from === from ? pair : { ...pair, path: [...pair.path].reverse() };
      routes.push(feature(ordered, {
        from_id: source.id, from_name: source.name, to_id: option.target.id, to_name: option.target.name,
        rank: rank + 1, best: rank === 0,
      }));
    });
  }

  let networkFeatures = [];
  if (network && sites.length > 1) {
    const edges = minimumSpanningTree(sites.length, (i, j) => pairs.get(i < j ? `${i}|${j}` : `${j}|${i}`)?.cost ?? Infinity);
    networkFeatures = edges.map(([i, j]) => feature(pairs.get(i < j ? `${i}|${j}` : `${j}|${i}`), {
      from_id: sites[i].id, from_name: sites[i].name, to_id: sites[j].id, to_name: sites[j].name,
    }));
  }

  current.sites = sites;
  post({
    type: "result",
    routes: { type: "FeatureCollection", features: routes },
    network: { type: "FeatureCollection", features: networkFeatures },
    snapped: sites.map((s) => ({ id: s.id, lonlat: cellCentreLonLat(s.cell) })),
    problems,
    timing: {
      total: (performance.now() - started) / 1000, costSeconds, secondsPerAccumulation, accumulations: origins.length,
    },
  });
}

// Hover explanations follow the settings as they are now, even before Run.
function explain({ lon, lat, requestId, scenario }) {
  if (!pack) return post({ type: "explain", requestId, available: false });
  const key = JSON.stringify([scenario.params, scenario.layers, scenario.groups]);
  if (!explainModel || explainModel.key !== key) {
    const model = prepareModel(pack, scenario);
    explainModel = { key, model, scales: prepareScales(pack, model) };
  }
  const cell = cellAt(lon, lat);
  if (cell < 0) return post({ type: "explain", requestId, available: true, outside: true });
  const result = cellCost(pack, explainModel.model, explainModel.scales, cell, true);
  post({
    type: "explain", requestId, available: true,
    cost: Number.isFinite(result.cost) ? result.cost : null,
    costScale: pack.grid.cost_scale,
    openLand: explainModel.model.openLand,
    blocked: result.blocked,
    steps: result.steps ? [...result.steps] : [],
    context: result.steps?.context || null,
  });
}

// Accumulated cost from both ends; cells within (1 + tolerance) × optimum.
function corridor({ fromId, toId, tolerances, requestId }) {
  const g = gridGeometry();
  const a = current.sites.find((s) => s.id === fromId);
  const b = current.sites.find((s) => s.id === toId);
  if (!a || !b) return post({ type: "corridor", requestId, error: "Run the model first." });
  const fromA = accumulate(current.cost, g.width, g.height, a.cell).acc;
  const fromB = accumulate(current.cost, g.width, g.height, b.cell).acc;
  const optimum = fromA[b.cell];
  const band = new Uint8Array(g.width * g.height);
  const sorted = [...tolerances].sort((x, y) => x - y);
  for (let cell = 0; cell < band.length; cell++) {
    const through = fromA[cell] + fromB[cell];
    for (let k = 0; k < sorted.length; k++) {
      if (through <= optimum * (1 + sorted[k])) { band[cell] = k + 1; break; }
    }
  }
  post({ type: "corridor", requestId, band, optimum, tolerances: sorted, grid: g }, [band.buffer]);
}

self.onmessage = async ({ data }) => {
  try {
    if (data.type === "load") {
      pack = await loadPack(browserReader(data.base), (done, total, name) =>
        post({ type: "progress", stage: `Loading model data (${name})`, done, total }));
      post({
        type: "ready",
        grid: pack.grid,
        layers: pack.layers,
        config: pack.config,
        bytes: pack.manifest.files.reduce((sum, file) => sum + (file.bytes || 0), 0),
      });
    } else if (data.type === "run") {
      await run(data);
    } else if (data.type === "explain") {
      explain(data);
    } else if (data.type === "corridor") {
      corridor(data);
    }
  } catch (error) {
    post({ type: "error", stage: data.type, message: error.message || String(error) });
  }
};
