// Run: node tests/js/scenario_test.mjs <config.json> <hotspots.geojson>
import { readFileSync } from "node:fs";
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const m = await import(pathToFileURL(join(root, "web", "engine", "scenario.js")).href);
const [configPath, hotspotsPath] = process.argv.slice(2);
const config = JSON.parse(readFileSync(configPath, "utf8"));
const hotspots = JSON.parse(readFileSync(hotspotsPath, "utf8")).features;

const base = m.defaultScenario(config, hotspots);
// Every configured layer appears; barrier layers default to barrier.
assert.equal(Object.keys(base.layers).length, Object.keys(config.layers).length);
for (const [name, layer] of Object.entries(config.layers)) {
  const expected = config.barriers.includes(layer.cost) ? "barrier" : "cost";
  assert.equal(base.layers[name].treatment, expected, name);
}
assert.equal(base.layers.bnbo.treatment, "barrier");
assert.equal(base.layers.wetlands.weight, config.costs.wetland);
assert.equal(base.params.parallel_factor, config.parallel_corridor.factor);
assert.equal(base.sites.length, hotspots.length);
assert.deepEqual(m.describeChanges(base, base), []);

// A loaded file keeps known values, ignores unknown ones and reports them.
const edited = structuredClone(base);
edited.layers.bnbo.treatment = "cost";
edited.layers.bnbo.weight = 3;
edited.layers.not_a_layer = { treatment: "cost", weight: 1 };
edited.params.open_sea = 1.5;
edited.sites[0].enabled = false;
const { scenario, notes } = m.reconcile(JSON.parse(JSON.stringify(edited)), base);
assert.equal(scenario.layers.bnbo.treatment, "cost");
assert.equal(scenario.layers.bnbo.weight, 3);
assert.equal(scenario.params.open_sea, 1.5);
assert.ok(!("not_a_layer" in scenario.layers));
assert.ok(notes.some((note) => note.includes("not_a_layer")));
const changes = m.describeChanges(scenario, base);
assert.ok(changes.some((line) => line.includes("bnbo") && line.includes("barrier → cost")));
assert.ok(changes.some((line) => line.startsWith("Disabled site")));

// Garbage in gives the defaults back, with a note.
assert.equal(m.reconcile("nonsense", base).scenario.name, base.name);

// Sites survive a CSV round trip, including commas and quotes in names.
const sites = [...base.sites.slice(0, 2), { id: "x", name: 'Plant "A", Aarhus', role: "storage", lon: 10.2, lat: 56.15, enabled: false }];
const parsed = m.sitesFromCsv(m.sitesToCsv(sites));
assert.deepEqual(parsed.errors, []);
assert.deepEqual(parsed.sites, sites);
// Danish Excel export: semicolons and decimal commas.
const danish = m.sitesFromCsv("navn;type;x;y\r\nAalborg;lager;9,92;57,05\r\nUdenfor;kilde;30;10\r\n");
assert.equal(danish.sites.length, 1);
assert.equal(danish.sites[0].role, "storage");
assert.equal(danish.sites[0].lon, 9.92);
assert.equal(danish.errors.length, 1);
console.log("scenario tests passed");
