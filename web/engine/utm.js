// ETRS89 / UTM zone 32N (EPSG:25832) <-> longitude/latitude, using the
// Krüger series as in PROJ's "etmerc" (sub-millimetre accuracy in Denmark).
// ETRS89 and WGS84 differ by well under a metre here, which is far below the
// 250 m grid, so map coordinates can be used directly.

const A = 6378137;
const F = 1 / 298.257222101; // GRS80
const K0 = 0.9996;
const LON0 = (9 * Math.PI) / 180;
const FALSE_EASTING = 500000;

const N = F / (2 - F);
const N2 = N * N, N3 = N2 * N, N4 = N3 * N, N5 = N4 * N, N6 = N5 * N;
const A_HAT = (A / (1 + N)) * (1 + N2 / 4 + N4 / 64 + N6 / 256);
const ALPHA = [
  N / 2 - (2 * N2) / 3 + (5 * N3) / 16 + (41 * N4) / 180 - (127 * N5) / 288 + (7891 * N6) / 37800,
  (13 * N2) / 48 - (3 * N3) / 5 + (557 * N4) / 1440 + (281 * N5) / 630 - (1983433 * N6) / 1935360,
  (61 * N3) / 240 - (103 * N4) / 140 + (15061 * N5) / 26880 + (167603 * N6) / 181440,
  (49561 * N4) / 161280 - (179 * N5) / 168 + (6601661 * N6) / 7257600,
  (34729 * N5) / 80640 - (3418889 * N6) / 1995840,
  (212378941 * N6) / 319334400,
];
const BETA = [
  N / 2 - (2 * N2) / 3 + (37 * N3) / 96 - N4 / 360 - (81 * N5) / 512 + (96199 * N6) / 604800,
  N2 / 48 + N3 / 15 - (437 * N4) / 1440 + (46 * N5) / 105 - (1118711 * N6) / 3870720,
  (17 * N3) / 480 - (37 * N4) / 840 - (209 * N5) / 4480 + (5569 * N6) / 90720,
  (4397 * N4) / 161280 - (11 * N5) / 504 - (830251 * N6) / 7257600,
  (4583 * N5) / 161280 - (108847 * N6) / 3991680,
  (20648693 * N6) / 638668800,
];
const E = Math.sqrt(F * (2 - F));

/** [lon, lat] in degrees -> [x, y] in metres (EPSG:25832). */
export function toUtm32(lon, lat) {
  const phi = (lat * Math.PI) / 180;
  const lambda = (lon * Math.PI) / 180 - LON0;
  const t = Math.sinh(Math.atanh(Math.sin(phi)) - E * Math.atanh(E * Math.sin(phi)));
  const xiPrime = Math.atan2(t, Math.cos(lambda));
  const etaPrime = Math.atanh(Math.sin(lambda) / Math.sqrt(1 + t * t));
  let xi = xiPrime;
  let eta = etaPrime;
  for (let j = 1; j <= 6; j++) {
    xi += ALPHA[j - 1] * Math.sin(2 * j * xiPrime) * Math.cosh(2 * j * etaPrime);
    eta += ALPHA[j - 1] * Math.cos(2 * j * xiPrime) * Math.sinh(2 * j * etaPrime);
  }
  return [FALSE_EASTING + K0 * A_HAT * eta, K0 * A_HAT * xi];
}

/** [x, y] in metres (EPSG:25832) -> [lon, lat] in degrees. */
export function fromUtm32(x, y) {
  const xi = y / (K0 * A_HAT);
  const eta = (x - FALSE_EASTING) / (K0 * A_HAT);
  let xiPrime = xi;
  let etaPrime = eta;
  for (let j = 1; j <= 6; j++) {
    xiPrime -= BETA[j - 1] * Math.sin(2 * j * xi) * Math.cosh(2 * j * eta);
    etaPrime -= BETA[j - 1] * Math.cos(2 * j * xi) * Math.sinh(2 * j * eta);
  }
  const tauPrime = Math.sin(xiPrime) / Math.sqrt(Math.sinh(etaPrime) ** 2 + Math.cos(xiPrime) ** 2);
  // Solve tau from tau' (Karney 2011, Newton iteration).
  let tau = tauPrime;
  for (let i = 0; i < 5; i++) {
    const sigma = Math.sinh(E * Math.atanh((E * tau) / Math.sqrt(1 + tau * tau)));
    const tauGuess = tau * Math.sqrt(1 + sigma * sigma) - sigma * Math.sqrt(1 + tau * tau);
    const derivative = ((1 - E * E) * Math.sqrt(1 + tau * tau) * Math.sqrt(1 + tauGuess * tauGuess))
      / (1 + (1 - E * E) * tau * tau);
    tau += (tauPrime - tauGuess) / derivative;
  }
  const lat = (Math.atan(tau) * 180) / Math.PI;
  const lon = ((LON0 + Math.atan2(Math.sinh(etaPrime), Math.cos(xiPrime))) * 180) / Math.PI;
  return [lon, lat];
}
