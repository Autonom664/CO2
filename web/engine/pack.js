// Loads the model pack (web/data/model/, written by src/export_model.py):
// reads manifest.json, checks each file's SHA-256, gunzips the binary
// planes and returns typed arrays. `readFile(name)` returns an ArrayBuffer;
// in the browser it fetches, in tests it reads from disk.

const TYPED = {
  uint8: Uint8Array,
  uint16: Uint16Array,
  uint32: Uint32Array,
  float32: Float32Array,
};

async function sha256Hex(buffer) {
  const digest = await crypto.subtle.digest("SHA-256", buffer);
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function gunzip(buffer) {
  const stream = new Blob([buffer]).stream().pipeThrough(new DecompressionStream("gzip"));
  return new Response(stream).arrayBuffer();
}

export function browserReader(base) {
  return async (name) => {
    const response = await fetch(`${base}/${name}`, { cache: "no-cache" });
    if (!response.ok) throw new Error(`${name}: HTTP ${response.status}`);
    return response.arrayBuffer();
  };
}

/**
 * @param {(name: string) => Promise<ArrayBuffer>} readFile
 * @param {(done: number, total: number, name: string) => void} [progress]
 */
export async function loadPack(readFile, progress = () => {}) {
  const decoder = new TextDecoder();
  const manifest = JSON.parse(decoder.decode(await readFile("manifest.json")));
  const entries = new Map(manifest.files.map((entry) => [entry.file || entry.path || entry.name, entry]));
  const names = [...entries.keys()];
  const raw = new Map();
  let done = 0;
  await Promise.all(names.map(async (name) => {
    const buffer = await readFile(name);
    // For gzip files, sha256 covers the unpacked data and compressed_sha256 the file.
    const entry = entries.get(name);
    const expected = entry.compressed_sha256 || entry.sha256;
    if (expected && (await sha256Hex(buffer)) !== expected) {
      throw new Error(`${name} is damaged or out of date (checksum mismatch); reload the page.`);
    }
    raw.set(name, buffer);
    progress(++done, names.length, name);
  }));

  const json = (name) => JSON.parse(decoder.decode(raw.get(name)));
  const grid = json("grid.json");
  const config = json("config.json");
  const layers = json("layers.json");
  const cells = grid.width * grid.height;

  async function plane(file, dtype) {
    const bytes = file.endsWith(".gz") ? await gunzip(raw.get(file)) : raw.get(file);
    const Typed = TYPED[dtype];
    if (!Typed) throw new Error(`${file}: unsupported dtype ${dtype}`);
    const array = new Typed(bytes);
    if (array.length !== cells) {
      throw new Error(`${file}: ${array.length} values, expected ${cells} (${grid.height} × ${grid.width})`);
    }
    return array;
  }

  const c = layers.continuous;
  const [presenceLo, presenceHi, buildingsShare, buildingDistance, population, population1km, parallel, landfall] =
    await Promise.all([
      plane(layers.bitplanes.low.file, layers.bitplanes.low.dtype),
      plane(layers.bitplanes.high.file, layers.bitplanes.high.dtype),
      plane(c.buildings_share.file, c.buildings_share.dtype),
      plane(c.building_distance.file, c.building_distance.dtype),
      plane(c.population.file, c.population.dtype),
      plane(c.population_1km.file, c.population_1km.dtype),
      plane(c.parallel.file, c.parallel.dtype),
      plane(c.landfall.file, c.landfall.dtype),
    ]);

  return {
    manifest, grid, config, layers,
    presenceLo, presenceHi, buildingsShare, buildingDistance,
    population, population1km, parallel, landfall,
    floatNodata: Math.fround(grid.float_nodata),
    distanceNodata: grid.distance_nodata,
  };
}
