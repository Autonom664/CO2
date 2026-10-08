// Browser-engine parity against validation/model_parity references (L3).
// Run: node tests/js/cost_parity.mjs <model_dir> <reference_dir>
// Prints one JSON line per scenario and exits 1 if any scenario fails the
// acceptance in model_parity.json (0.5 % per cell and per route).
import { readFile } from "node:fs/promises";
import { gunzipSync } from "node:zlib";
import { join, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const load = (name) => import(pathToFileURL(join(root, "web", "engine", name)).href);
const { loadPack } = await load("pack.js");
const { computeCost } = await load("cost.js");
const { accumulate } = await load("paths.js");
const { defaultScenario } = await load("scenario.js");

const [modelDir, referenceDir] = process.argv.slice(2);
const pack = await loadPack(async (name) => {
  const buffer = await readFile(join(modelDir, name));
  return buffer.buffer.slice(buffer.byteOffset, buffer.byteOffset + buffer.byteLength);
});
const reference = JSON.parse(await readFile(join(referenceDir, "model_parity.json"), "utf8"));
const tolerance = reference.acceptance.cost_cell_relative_tolerance;
const width = pack.grid.width;
let failed = false;

for (const scenarioDoc of reference.scenarios) {
  const scenario = defaultScenario(pack.config, []);
  for (const [costKey, multiplier] of Object.entries(scenarioDoc.weight_multipliers || {})) {
    for (const layer of pack.layers.layers) {
      if (layer.cost === costKey && scenario.layers[layer.name]) {
        scenario.layers[layer.name].weight = pack.config.costs[costKey] * multiplier;
      }
    }
  }
  const started = performance.now();
  const { cost } = computeCost(pack, scenario);
  const costSeconds = (performance.now() - started) / 1000;

  const refBytes = gunzipSync(await readFile(join(referenceDir, scenarioDoc.cost_grid)));
  const ref = new Float32Array(refBytes.buffer, refBytes.byteOffset, refBytes.byteLength / 4);
  let traversabilityMismatch = 0;
  let maxRelative = 0;
  let worstCell = -1;
  for (let cell = 0; cell < ref.length; cell++) {
    const refValid = ref[cell] !== pack.floatNodata;
    const ours = cost[cell];
    if (refValid !== Number.isFinite(ours)) {
      traversabilityMismatch++;
      continue;
    }
    if (!refValid) continue;
    const relative = Math.abs(ours - ref[cell]) / ref[cell];
    if (relative > maxRelative) {
      maxRelative = relative;
      worstCell = cell;
    }
  }

  let maxRouteRelative = 0;
  const bySource = new Map();
  for (const route of scenarioDoc.routes) {
    const list = bySource.get(route.from) || [];
    list.push(route);
    bySource.set(route.from, list);
  }
  const routeStarted = performance.now();
  let accumulations = 0;
  for (const routes of bySource.values()) {
    const [r, c] = routes[0].start_cell;
    const { acc } = accumulate(cost, width, pack.grid.height, r * width + c);
    accumulations++;
    for (const route of routes) {
      const [er, ec] = route.end_cell;
      const ours = acc[er * width + ec];
      const relative = Math.abs(ours - route.accumulated_cost) / route.accumulated_cost;
      maxRouteRelative = Math.max(maxRouteRelative, relative);
    }
  }
  const secondsPerAccumulation = (performance.now() - routeStarted) / 1000 / Math.max(1, accumulations);

  const pass = traversabilityMismatch === 0 && maxRelative <= tolerance && maxRouteRelative <= tolerance;
  failed ||= !pass;
  const worst = worstCell < 0 ? null : {
    row: Math.floor(worstCell / width), col: worstCell % width, ours: cost[worstCell], reference: ref[worstCell],
  };
  console.log(JSON.stringify({
    scenario: scenarioDoc.id, pass, traversabilityMismatch,
    maxCellRelative: maxRelative, worst, maxRouteRelative,
    routes: scenarioDoc.routes.length, costSeconds: +costSeconds.toFixed(2),
    secondsPerAccumulation: +secondsPerAccumulation.toFixed(2),
  }));
}
process.exit(failed ? 1 : 0);
