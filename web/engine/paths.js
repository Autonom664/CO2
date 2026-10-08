// Least-cost paths on a raster, matching skimage.graph.MCP_Geometric with
// fully_connected=True: moving from cell a to a neighbour b costs
// (cost[a] + cost[b]) / 2 × step length (1 for edges, √2 for diagonals).
// Impassable cells have cost Infinity (or NaN), and paths never enter them.

const DIAGONAL = Math.SQRT2;

// Binary min-heap over (priority, cell) pairs, stored in growable typed arrays.
class CellHeap {
  constructor(capacity = 1 << 16) {
    this.keys = new Float64Array(capacity);
    this.cells = new Int32Array(capacity);
    this.size = 0;
  }

  push(key, cell) {
    if (this.size === this.keys.length) {
      const keys = new Float64Array(this.size * 2);
      const cells = new Int32Array(this.size * 2);
      keys.set(this.keys);
      cells.set(this.cells);
      this.keys = keys;
      this.cells = cells;
    }
    let i = this.size++;
    while (i > 0) {
      const parent = (i - 1) >> 1;
      if (this.keys[parent] <= key) break;
      this.keys[i] = this.keys[parent];
      this.cells[i] = this.cells[parent];
      i = parent;
    }
    this.keys[i] = key;
    this.cells[i] = cell;
  }

  // Removes the smallest entry; returns its cell and leaves its key in this.top.
  pop() {
    const cell = this.cells[0];
    this.top = this.keys[0];
    const lastKey = this.keys[--this.size];
    const lastCell = this.cells[this.size];
    let i = 0;
    for (;;) {
      let child = 2 * i + 1;
      if (child >= this.size) break;
      if (child + 1 < this.size && this.keys[child + 1] < this.keys[child]) child += 1;
      if (this.keys[child] >= lastKey) break;
      this.keys[i] = this.keys[child];
      this.cells[i] = this.cells[child];
      i = child;
    }
    this.keys[i] = lastKey;
    this.cells[i] = lastCell;
    return cell;
  }
}

/**
 * Accumulated cost from one start cell to every reachable cell.
 *
 * @param {Float32Array|Float64Array} cost  row-major cell costs; Infinity/NaN = impassable
 * @param {number} width
 * @param {number} height
 * @param {number} start  start cell index (row * width + col)
 * @param {object} [options]
 * @param {number[]} [options.targets]  stop once all these cells are settled
 * @returns {{acc: Float64Array, prev: Int32Array}} acc is Infinity where unreachable;
 *          prev holds the previous cell on the best path (-1 at the start)
 */
export function accumulate(cost, width, height, start, options = {}) {
  const n = width * height;
  const acc = new Float64Array(n).fill(Infinity);
  const prev = new Int32Array(n).fill(-1);
  const done = new Uint8Array(n);
  if (!(cost[start] < Infinity)) return { acc, prev };

  let remaining = options.targets ? new Set(options.targets) : null;
  const heap = new CellHeap();
  acc[start] = 0;
  heap.push(0, start);

  while (heap.size > 0) {
    const cell = heap.pop();
    if (done[cell] || heap.top > acc[cell]) continue;
    done[cell] = 1;
    if (remaining) {
      remaining.delete(cell);
      if (remaining.size === 0) break;
    }
    const row = (cell / width) | 0;
    const col = cell - row * width;
    const here = cost[cell];
    const base = acc[cell];
    for (let dr = -1; dr <= 1; dr++) {
      const r = row + dr;
      if (r < 0 || r >= height) continue;
      for (let dc = -1; dc <= 1; dc++) {
        if (dr === 0 && dc === 0) continue;
        const c = col + dc;
        if (c < 0 || c >= width) continue;
        const next = r * width + c;
        if (done[next]) continue;
        const there = cost[next];
        if (!(there < Infinity)) continue;
        const step = (here + there) / 2 * (dr !== 0 && dc !== 0 ? DIAGONAL : 1);
        const candidate = base + step;
        if (candidate < acc[next]) {
          acc[next] = candidate;
          prev[next] = cell;
          heap.push(candidate, next);
        }
      }
    }
  }
  return { acc, prev };
}

/** Cells on the best path from the start to `end`, start first; [] if unreachable. */
export function traceback(prev, acc, end) {
  if (!(acc[end] < Infinity)) return [];
  const path = [];
  for (let cell = end; cell !== -1; cell = prev[cell]) path.push(cell);
  return path.reverse();
}

/**
 * Nearest passable cell to (row, col) within maxCells, searching outward in
 * square rings, nearest by Euclidean distance. Returns -1 if none.
 */
export function nearestPassable(cost, width, height, row, col, maxCells) {
  let best = -1;
  let bestDistance = Infinity;
  for (let ring = 0; ring <= maxCells; ring++) {
    // A cell found in an earlier ring may still be beaten by a diagonal
    // neighbour of this ring, so stop only when the ring is farther away.
    if (best !== -1 && ring > bestDistance) break;
    for (let r = row - ring; r <= row + ring; r++) {
      if (r < 0 || r >= height) continue;
      const edge = r === row - ring || r === row + ring;
      for (let c = col - ring; c <= col + ring; c += edge ? 1 : 2 * ring || 1) {
        if (c < 0 || c >= width) continue;
        const cell = r * width + c;
        if (!(cost[cell] < Infinity)) continue;
        const distance = Math.hypot(r - row, c - col);
        if (distance < bestDistance) {
          best = cell;
          bestDistance = distance;
        }
      }
    }
  }
  return best;
}
