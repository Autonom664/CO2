// Reads a JSON case from stdin, runs the browser path engine, prints JSON.
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
const [enginePath] = process.argv.slice(2);
const { accumulate, traceback, nearestPassable } = await import(pathToFileURL(enginePath).href);
const input = JSON.parse(readFileSync(0, "utf8"));
const out = input.cases.map(({ width, height, cost, start, end, snap }) => {
  const grid = Float64Array.from(cost, (v) => (v === null ? Infinity : v));
  const { acc, prev } = accumulate(grid, width, height, start);
  const path = traceback(prev, acc, end);
  return {
    acc: Array.from(acc, (v) => (Number.isFinite(v) ? v : null)),
    path,
    snapped: snap ? nearestPassable(grid, width, height, snap[0], snap[1], 5) : null,
  };
});
process.stdout.write(JSON.stringify(out));
