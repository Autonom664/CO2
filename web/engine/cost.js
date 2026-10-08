// The 250 m cost surface, computed in the browser from the model pack and
// the user's scenario. Follows docs/model_formula.md step by step; the same
// steps produce the per-cell explanation shown on hover.
//
// Per-layer weights: a cost key shared by several layers (for example
// natura2000 for habitat and bird sites) contributes the highest weight of
// its layers present in the cell, so the default reproduces "union the
// masks and add the key's cost once".

const DYNAMIC = new Set(["population", "population_risk", "dwelling_proximity"]);

function bitSet(pack, cell, bit) {
  return bit < 32
    ? (pack.presenceLo[cell] >>> bit) & 1
    : (pack.presenceHi[cell] >>> (bit - 32)) & 1;
}

// numpy.quantile (linear) of sorted values at the given probabilities.
function quantiles(sorted, probabilities) {
  const n = sorted.length;
  return probabilities.map((p) => {
    const position = p * (n - 1);
    const low = Math.floor(position);
    const high = Math.min(low + 1, n - 1);
    return sorted[low] + (sorted[high] - sorted[low]) * (position - low);
  });
}

// Thresholds and scores as in cost_surface.py: duplicate thresholds take the
// mean of their score levels; a single unique threshold gets `single`.
export function quantileScale(values, minimum, maximum, count, single) {
  const sorted = Float64Array.from(values).sort();
  const probabilities = Array.from({ length: count + 1 }, (_, i) => i / count);
  const thresholds = quantiles(sorted, probabilities);
  const levels = probabilities.map((p) => minimum + (maximum - minimum) * p);
  const xs = [];
  const ys = [];
  const sums = [];
  for (let i = 0; i < thresholds.length; i++) {
    const last = xs.length - 1;
    if (last >= 0 && thresholds[i] === xs[last]) {
      sums[last].push(levels[i]);
    } else {
      xs.push(thresholds[i]);
      sums.push([levels[i]]);
    }
  }
  for (const group of sums) ys.push(group.reduce((a, b) => a + b, 0) / group.length);
  if (xs.length === 1) ys[0] = single;
  return { xs, ys };
}

// numpy.interp: linear, clamped to the end values.
export function interp(x, xs, ys) {
  if (x <= xs[0]) return ys[0];
  const last = xs.length - 1;
  if (x >= xs[last]) return ys[last];
  let lo = 0;
  let hi = last;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (xs[mid] <= x) lo = mid;
    else hi = mid;
  }
  return ys[lo] + (ys[hi] - ys[lo]) * (x - xs[lo]) / (xs[hi] - xs[lo]);
}

/** Static description of the model for a scenario: what each key costs, groups, barriers. */
export function prepareModel(pack, scenario) {
  const { config } = pack;
  const s = pack.grid.cost_scale;
  const p = scenario.params;
  const layers = pack.layers.layers.filter((layer) => layer.available);
  const derived = Object.fromEntries(pack.layers.derived.map((d) => [d.name, d]));

  const barrierLayers = [];
  const keyLayers = new Map(); // cost key -> [{bit, weight, landOnly, name}]
  for (const layer of layers) {
    const choice = scenario.layers[layer.name] || { treatment: layer.default_action, weight: 0 };
    if (choice.treatment === "ignore") continue;
    if (choice.treatment === "barrier") {
      barrierLayers.push(layer);
      continue;
    }
    const list = keyLayers.get(layer.cost) || [];
    list.push({ bit: layer.bit, weight: choice.weight, landOnly: layer.surface === "land", name: layer.name });
    keyLayers.set(layer.cost, list);
  }
  if (p.landfall > 0 && derived.landfall) {
    keyLayers.set("landfall", [{ bit: derived.landfall.bit, weight: p.landfall, landOnly: true, name: "landfall" }]);
  }

  const groups = [];
  const grouped = new Set();
  for (const [name, group] of Object.entries(config.combine_groups || {})) {
    const rule = scenario.groups[name]?.rule || group.rule || "max";
    const deferred = group.members.some((member) => DYNAMIC.has(member));
    groups.push({ name, members: group.members, rule, deferred });
    for (const member of group.members) grouped.add(member);
  }
  const discounts = new Set(config.discount_classes || []);
  const ungrouped = [...keyLayers.keys()].filter((key) => !grouped.has(key));
  return {
    s, p, derived, barrierLayers, keyLayers, groups, discounts, ungrouped,
    buildingThreshold: Math.round(p.buildings_share * 255),
    openLand: p.open_land * s,
    openSea: p.open_sea * s,
  };
}

// Score of one cost key at a cell: the highest weight of its present layers.
function keyScore(pack, model, key, cell, isLand) {
  const list = model.keyLayers.get(key);
  if (!list) return null;
  let best = null;
  for (const layer of list) {
    if (layer.landOnly && !isLand) continue;
    if (!bitSet(pack, cell, layer.bit)) continue;
    if (best === null || layer.weight > best.weight) best = layer;
  }
  return best;
}

function combine(values, rule) {
  if (!values.length) return 0;
  return rule === "sum" ? values.reduce((a, b) => a + b, 0) : Math.max(...values);
}

/**
 * Per-cell inputs that need the whole grid (quantile scales), computed once
 * per scenario: population and population-risk scale tables.
 */
export function prepareScales(pack, model) {
  const { p } = model;
  const n = pack.grid.width * pack.grid.height;
  const land = model.derived.land.bit;
  const scales = {};
  if (p.population.enabled) {
    const threshold = p.population.min_per_cell * (pack.grid.resolution_m / 100) ** 2;
    const values = [];
    for (let cell = 0; cell < n; cell++) {
      const v = pack.population[cell];
      if (v !== pack.floatNodata && v > 0 && v >= threshold && bitSet(pack, cell, land)) values.push(v);
    }
    scales.populationThreshold = threshold;
    if (values.length) {
      const count = pack.config.costs.population?.quantiles ?? 100;
      scales.population = quantileScale(values, p.population.minimum, p.population.maximum, count, p.population.minimum);
    }
  }
  if (p.population_risk.enabled) {
    const values = [];
    for (let cell = 0; cell < n; cell++) {
      const v = pack.population1km[cell];
      if (v !== pack.floatNodata && v > p.population_risk.threshold_people && bitSet(pack, cell, land)) values.push(v);
    }
    if (values.length) {
      const count = pack.config.costs.population_risk?.quantiles ?? 5;
      scales.risk = quantileScale(values, 0, p.population_risk.maximum, count, p.population_risk.maximum);
    }
  }
  return scales;
}

/**
 * Cost of one cell with every step recorded. Returns {cost, blocked, steps}
 * where cost is Infinity for barriers and cells outside the analysis area.
 * computeCost() calls this for every cell, so hover and routing always agree.
 */
export function cellCost(pack, model, scales, cell, explain = false) {
  const { s, p, derived } = model;
  const steps = explain ? [] : null;
  const isLand = bitSet(pack, cell, derived.land.bit) === 1;
  const isSea = !isLand && bitSet(pack, cell, derived.sea.bit) === 1;
  if (!isLand && !isSea) return { cost: Infinity, blocked: "outside the analysis area", steps };
  if (pack.buildingsShare[cell] >= model.buildingThreshold && model.buildingThreshold > 0) {
    return { cost: Infinity, blocked: `buildings cover ${Math.round(pack.buildingsShare[cell] / 2.55)}% of the cell`, steps };
  }
  for (const layer of model.barrierLayers) {
    if (bitSet(pack, cell, layer.bit)) return { cost: Infinity, blocked: layer.name, steps };
  }

  // 1. Base.
  let cost = isLand ? model.openLand : model.openSea;
  if (explain) steps.push({ step: "base", label: isLand ? "open_land" : "open_sea", value: cost });

  // 2. Static groups (highest only, or sum if the user chose it).
  for (const group of model.groups) {
    if (group.deferred) continue;
    const parts = [];
    for (const key of group.members) {
      const hit = keyScore(pack, model, key, cell, isLand);
      if (hit) parts.push({ key, layer: hit.name, value: hit.weight * s });
    }
    if (!parts.length) continue;
    const value = combine(parts.map((part) => part.value), group.rule);
    cost += value;
    if (explain) steps.push({ step: "group", label: group.name, rule: group.rule, value, parts });
  }

  // 3. Other static layers; discounts subtract with a floor at open land.
  for (const key of model.ungrouped) {
    if (DYNAMIC.has(key)) continue;
    const hit = keyScore(pack, model, key, cell, isLand);
    if (!hit) continue;
    const value = hit.weight * s;
    if (model.discounts.has(key)) {
      const before = cost;
      cost = Math.max(model.openLand, cost - value);
      if (explain) steps.push({ step: "discount", label: key, layer: hit.name, value: cost - before });
    } else {
      cost += value;
      if (explain) steps.push({ step: "layer", label: key, layer: hit.name, value });
    }
  }

  // 4. Dwelling proximity (dynamic; may sit in a deferred group).
  const dynamic = {};
  const distance = pack.buildingDistance[cell];
  if (p.dwelling_proximity.enabled && isLand && distance !== pack.distanceNodata
      && distance > 0 && distance < p.dwelling_proximity.max_distance_m) {
    dynamic.dwelling_proximity = p.dwelling_proximity.max_score
      * (1 - distance / p.dwelling_proximity.max_distance_m) * s;
  }

  // 5. Parallel corridor: multiply what we have so far, floor at open land.
  if (p.parallel_factor !== 1 && pack.parallel[cell]) {
    const before = cost;
    cost = Math.max(model.openLand, cost * p.parallel_factor);
    if (explain) steps.push({ step: "parallel", label: "parallel_factor", factor: p.parallel_factor, value: cost - before });
  }

  // 6–7. Population and population risk (quantile-scaled).
  if (scales.population && isLand) {
    const v = pack.population[cell];
    if (v !== pack.floatNodata && v > 0 && v >= scales.populationThreshold) {
      dynamic.population = interp(v, scales.population.xs, scales.population.ys) * s;
    }
  }
  if (scales.risk && isLand) {
    const v = pack.population1km[cell];
    if (v !== pack.floatNodata && v > p.population_risk.threshold_people) {
      dynamic.population_risk = interp(v, scales.risk.xs, scales.risk.ys) * s;
    }
  }

  // 8. Deferred groups (people): highest of the members present, or sum.
  const usedDynamic = new Set();
  for (const group of model.groups) {
    if (!group.deferred) continue;
    const parts = [];
    for (const key of group.members) {
      if (DYNAMIC.has(key)) {
        usedDynamic.add(key);
        if (dynamic[key] > 0) parts.push({ key, value: dynamic[key] });
      } else {
        const hit = keyScore(pack, model, key, cell, isLand);
        if (hit) parts.push({ key, layer: hit.name, value: hit.weight * s });
      }
    }
    if (!parts.length) continue;
    const value = combine(parts.map((part) => part.value), group.rule);
    cost += value;
    if (explain) steps.push({ step: "group", label: group.name, rule: group.rule, value, parts });
  }
  for (const [key, value] of Object.entries(dynamic)) {
    if (usedDynamic.has(key) || !(value > 0)) continue;
    cost += value;
    if (explain) steps.push({ step: "layer", label: key, value });
  }

  if (explain) {
    steps.context = {
      isLand,
      buildingDistance: distance === pack.distanceNodata ? null : distance,
      buildingShare: pack.buildingsShare[cell] / 255,
      population: pack.population[cell] === pack.floatNodata ? null : pack.population[cell],
      population1km: pack.population1km[cell] === pack.floatNodata ? null : pack.population1km[cell],
      parallel: pack.parallel[cell] === 1,
      landfall: pack.landfall[cell] === 1,
    };
  }
  return { cost, blocked: null, steps };
}

/** Whole cost surface for a scenario. Infinity marks barriers and outside cells. */
export function computeCost(pack, scenario) {
  const model = prepareModel(pack, scenario);
  const scales = prepareScales(pack, model);
  const n = pack.grid.width * pack.grid.height;
  const cost = new Float32Array(n);
  for (let cell = 0; cell < n; cell++) cost[cell] = cellCost(pack, model, scales, cell).cost;
  return { cost, model, scales };
}
