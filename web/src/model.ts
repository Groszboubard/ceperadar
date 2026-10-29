import params from "./params.json";
import type { Filters, Latest, Mode, Sector, SpeciesKey, StaticData, Comp, PointDay } from "./types";
import { SPECIES } from "./types";

export const CLASS_LABEL: Record<number, string> = Object.fromEntries(params.forest_classes.map((c) => [c.id, c.label]));
export const SPECIES_LABEL: Record<SpeciesKey, string> = Object.fromEntries(
  SPECIES.map((s) => [s, (params.species as any)[s].label])
) as Record<SpeciesKey, string>;
export const SPECIES_LATIN: Record<SpeciesKey, string> = Object.fromEntries(
  SPECIES.map((s) => [s, (params.species as any)[s].latin])
) as Record<SpeciesKey, string>;
export const LEVELS = params.levels;

export function levelOf(score: number) {
  let l = LEVELS[0];
  for (const x of LEVELS) if (score >= x.min) l = x;
  return l;
}

export function confLabel(c: number) {
  return c >= 75 ? "Élevée" : c >= 50 ? "Moyenne" : "Faible";
}

const PINS = new Set([1, 2, 3, 16]);
const CHENES = new Set([4, 5, 6, 7]);
const MIXTE = new Set([9, 10]);
const FEUILLUS = new Set([4, 5, 6, 7, 8, 12, 13]);

export function forestGroupOk(cls: number, group: Filters["forestType"]) {
  if (group === "all") return true;
  if (group === "pins") return PINS.has(cls);
  if (group === "chenes") return CHENES.has(cls);
  if (group === "mixte") return MIXTE.has(cls);
  return FEUILLUS.has(cls);
}

/** Indice de l'entrée météo d'une maille : unité sol × météo (V1.1) ou point météo (V1). */
export const wIndex = (st: StaticData, lt: Latest, c: number) =>
  st.cells.unit && lt.uconf ? st.cells.unit[c] : st.cells.wp[c];

/** Score météo W (0-100) ; NaN si inconnu. */
export function cellW(st: StaticData, lt: Latest, c: number, sp: SpeciesKey, d: number): number {
  const w = lt.W[sp][d][wIndex(st, lt, c)];
  return w === undefined || w === 255 ? NaN : w;
}

/** Score d'une cellule pour une espèce et une date : round(H × W / 100) ; NaN si inconnu. */
export function cellScore(st: StaticData, lt: Latest, c: number, sp: SpeciesKey, d: number): number {
  const w = cellW(st, lt, c, sp, d);
  return Number.isNaN(w) ? NaN : Math.round((st.cells.H[sp][c] * w) / 100);
}

/** Score V1 (comparaison) ; NaN si non disponible. */
export function cellScoreV1(st: StaticData, lt: Latest, c: number, sp: SpeciesKey, d: number): number {
  if (!lt.W_v1 || !st.cells.H_v1) return NaN;
  const w = lt.W_v1[sp][d][st.cells.wp[c]];
  return w === undefined || w === 255 ? NaN : Math.round((st.cells.H_v1[sp][c] * w) / 100);
}

/** 0 = score fiable, 1 = incertain (confiance < 50), 2 = données absentes. */
export type DataState = 0 | 1 | 2;

export interface DayScores {
  score: Float32Array; // NaN = inconnu
  species: Int8Array; // espèce dominante (index dans SPECIES) ou -1
  conf: Uint8Array;
  state: Uint8Array;
}

export function computeDay(st: StaticData, lt: Latest, mode: Mode, d: number): DayScores {
  const n = st.cells.i.length;
  const score = new Float32Array(n);
  const species = new Int8Array(n).fill(-1);
  const conf = new Uint8Array(n);
  const state = new Uint8Array(n);
  const bad = new Set(lt.bad_points);
  const list = mode === "all" ? SPECIES : [mode];
  for (let c = 0; c < n; c++) {
    let best = NaN;
    let bs = -1;
    for (const sp of list) {
      const v = cellScore(st, lt, c, sp, d);
      if (!Number.isNaN(v) && (Number.isNaN(best) || v > best)) {
        best = v;
        bs = SPECIES.indexOf(sp);
      }
    }
    score[c] = best;
    species[c] = bs;
    const spc = bs >= 0 ? SPECIES[bs] : list[0];
    const wconf = lt.uconf && st.cells.unit ? lt.uconf[d][st.cells.unit[c]] : lt.conf[spc][d];
    conf[c] = bad.has(st.cells.wp[c]) ? 0 : Math.min(st.cells.conf[c], wconf);
    state[c] = Number.isNaN(best) ? 2 : conf[c] < 50 ? 1 : 0;
  }
  return { score, species, conf, state };
}

/** Filtres hors score (une maille sans donnée reste affichée en gris). */
export function passesNonScore(st: StaticData, f: Filters, c: number, day: DayScores) {
  if (st.cells.dist[c] > f.maxDist) return false;
  if (day.state[c] !== 2 && day.conf[c] < f.minConf) return false;
  if (!forestGroupOk(st.cells.c1[c], f.forestType)) return false;
  if (f.access === "public" && !(st.cells.pub[c] >= 30)) return false;
  if (f.access === "noprotected" && st.cells.prot[c] > 0) return false;
  return true;
}

export function passes(st: StaticData, f: Filters, c: number, day: DayScores) {
  const s = day.score[c];
  if (Number.isNaN(s) || s < f.minScore) return false;
  if (st.cells.dist[c] > f.maxDist) return false;
  if (day.conf[c] < f.minConf) return false;
  if (!forestGroupOk(st.cells.c1[c], f.forestType)) return false;
  if (f.access === "public" && !(st.cells.pub[c] >= 30)) return false;
  if (f.access === "noprotected" && st.cells.prot[c] > 0) return false;
  return true;
}

/** Indice régional = moyenne du décile supérieur des cellules forestières. */
export function regionalIndex(day: DayScores) {
  const v = Array.from(day.score).filter((x) => !Number.isNaN(x)).sort((a, b) => a - b);
  if (!v.length) return NaN;
  const top = v.slice(v.length - Math.max(1, Math.floor(v.length / 10)));
  return top.reduce((a, b) => a + b, 0) / top.length;
}

export function cellLatLon(st: StaticData, c: number): [number, number] {
  return [st.grid.lat0 + st.cells.i[c] * st.grid.dlat, st.grid.lon0 + st.cells.j[c] * st.grid.dlon];
}

function topMean(vals: number[], k = 5) {
  const v = vals.filter((x) => !Number.isNaN(x)).sort((a, b) => b - a).slice(0, k);
  return v.length ? v.reduce((a, b) => a + b, 0) / v.length : NaN;
}

const DIRS = ["nord", "nord-est", "est", "sud-est", "sud", "sud-ouest", "ouest", "nord-ouest"];

/**
 * Regroupe les cellules contiguës favorables en secteurs de prospection.
 * Seuil = max(seuil filtre, 30, 85e centile du jour). Les grands massifs sont découpés en blocs
 * de 6 × 6 km pour ne pas réduire un massif entier à un seul point.
 */
export function buildSectors(st: StaticData, f: Filters, day: DayScores, prevDay: DayScores | null, limit = 20): Sector[] {
  const n = st.cells.i.length;
  const ok: number[] = [];
  for (let c = 0; c < n; c++) if (passes(st, f, c, day)) ok.push(c);
  if (!ok.length) return [];
  const sorted = ok.map((c) => day.score[c]).sort((a, b) => a - b);
  const p85 = sorted[Math.floor(0.85 * (sorted.length - 1))];
  const thr = Math.max(f.minScore, 30, p85);
  const N = st.grid.n;
  const key = (i: number, j: number) => (i + N) * (2 * N + 1) + (j + N);
  const sel = new Map<number, number>();
  for (const c of ok) if (day.score[c] >= thr) sel.set(key(st.cells.i[c], st.cells.j[c]), c);
  const seen = new Set<number>();
  const units: number[][] = [];
  for (const [k0, c0] of sel) {
    if (seen.has(k0)) continue;
    const comp: number[] = [];
    const stack = [c0];
    seen.add(k0);
    while (stack.length) {
      const c = stack.pop()!;
      comp.push(c);
      const i = st.cells.i[c], j = st.cells.j[c];
      for (let di = -1; di <= 1; di++)
        for (let dj = -1; dj <= 1; dj++) {
          if (!di && !dj) continue;
          const kk = key(i + di, j + dj);
          const cc = sel.get(kk);
          if (cc !== undefined && !seen.has(kk)) {
            seen.add(kk);
            stack.push(cc);
          }
        }
    }
    // les petits bois restent entiers ; les grands massifs sont découpés en blocs de 6 km
    if (comp.length <= 25) {
      units.push(comp);
      continue;
    }
    const blocks = new Map<string, number[]>();
    for (const c of comp) {
      const b = `${Math.floor((st.cells.i[c] + N) / 6)}:${Math.floor((st.cells.j[c] + N) / 6)}`;
      if (!blocks.has(b)) blocks.set(b, []);
      blocks.get(b)!.push(c);
    }
    for (const b of blocks.values()) units.push(b);
  }
  // centre de chaque commune (pour nommer nord/sud…)
  const comCenter = new Map<number, [number, number, number]>();
  for (let c = 0; c < n; c++) {
    const k = st.cells.com[c];
    const v = comCenter.get(k) ?? [0, 0, 0];
    v[0] += st.cells.i[c]; v[1] += st.cells.j[c]; v[2] += 1;
    comCenter.set(k, v);
  }
  const sectors: Sector[] = units.map((cells) => {
    const scores = cells.map((c) => day.score[c]);
    const best = cells[scores.indexOf(Math.max(...scores))];
    const score = Math.round(topMean(scores));
    const prev = prevDay ? Math.round(topMean(cells.map((c) => prevDay.score[c]))) : null;
    const mi = cells.reduce((a, c) => a + st.cells.i[c], 0) / cells.length;
    const mj = cells.reduce((a, c) => a + st.cells.j[c], 0) / cells.length;
    const com = st.cells.com[best];
    const cc = comCenter.get(com)!;
    const ci = cc[0] / cc[2], cj = cc[1] / cc[2];
    let suffix = "";
    if (Math.hypot(mi - ci, mj - cj) > 1.5) {
      const ang = (Math.atan2(mj - cj, mi - ci) * 180) / Math.PI; // 0 = nord
      suffix = " " + DIRS[Math.round(((ang + 360) % 360) / 45) % 8];
    }
    const lat = st.grid.lat0 + mi * st.grid.dlat;
    const lon = st.grid.lon0 + mj * st.grid.dlon;
    // essence majoritaire pondérée par la surface
    const ess = new Map<number, number>();
    for (const c of cells) {
      for (const [cl, p] of [[st.cells.c1[c], st.cells.p1[c]], [st.cells.c2[c], st.cells.p2[c]]]) ess.set(cl, (ess.get(cl) ?? 0) + p);
    }
    const essList = [...ess.entries()].filter(([, p]) => p > 0).sort((a, b) => b[1] - a[1]);
    const essence = essList.slice(0, 2).map(([cl]) => CLASS_LABEL[cl]).join(" / ");
    const conf = Math.min(...cells.map((c) => day.conf[c]));
    const spCount = new Map<number, number>();
    for (const c of cells) spCount.set(day.species[c], (spCount.get(day.species[c]) ?? 0) + 1);
    const domSp = [...spCount.entries()].sort((a, b) => b[1] - a[1])[0][0];
    const name = `Forêt de ${st.communes[com]}${suffix ? " —" + suffix : ""}`;
    return {
      id: `${st.cells.i[best]},${st.cells.j[best]}`, cells, best, score, prev: Number.isNaN(prev as number) ? null : prev,
      name, commune: st.communes[com], lat, lon, dist: Math.round(st.cells.dist[best]), essence, conf,
      species: domSp >= 0 ? SPECIES[domSp] : null,
    };
  });
  // une maille isolée n'est retenue que si elle est réellement bonne
  const kept = sectors.filter((s) => s.cells.length >= 2 || s.score >= 60);
  sectors.length = 0;
  sectors.push(...kept);
  sectors.sort((a, b) => b.score - a.score || b.cells.length - a.cells.length);
  // noms uniques
  const used = new Map<string, number>();
  for (const s of sectors) {
    const k = used.get(s.name) ?? 0;
    used.set(s.name, k + 1);
    if (k) s.name = `${s.name} (${k + 1})`;
  }
  return sectors.slice(0, limit);
}

const pct = (x: number | null | undefined) => (x == null ? "?" : Math.round(x * 100));

const WP = params.weather as any;
/**
 * Facteur limitant : contribution logarithmique de chaque terme au score final
 * (score = H × R^a × M^b × T^c × saison × gel × chaleur). Le terme le plus pénalisant est cité,
 * ainsi que les facteurs favorables (≥ 0,8) pour nuancer.
 */
export function limitingFactor(H: number, comp: Comp | undefined): { key: string; text: string; terms: { k: string; v: number }[] } | null {
  if (!comp) return null;
  const S = comp.S ?? 1;
  const season = WP.season_floor + (1 - WP.season_floor) * S;
  const terms = [
    { k: "habitat", v: H / 100, w: 1 },
    { k: "pluie", v: comp.R ?? 1, w: WP.exp_rain },
    { k: "humidité", v: comp.M ?? 1, w: WP.exp_moist },
    { k: "température", v: comp.T ?? 1, w: WP.exp_temp },
    { k: "saison", v: season, w: 1 },
    { k: "gel", v: comp.frost ?? 1, w: 1 },
    { k: "chaleur", v: comp.heat ?? 1, w: 1 },
  ];
  const contrib = terms.map((t) => ({ k: t.k, c: t.w * Math.log(Math.max(t.v, 1e-3)), v: t.v }));
  const worst = [...contrib].sort((a, b) => a.c - b.c)[0];
  const phrases: Record<string, string> = {
    habitat: "un habitat peu adapté à l'espèce (essences, couverture forestière ou sol)",
    pluie: "des pluies insuffisantes sur la fenêtre utile",
    humidité: "une réserve hydrique du sol estimée insuffisante",
    température: "des températures hors de la plage favorable",
    saison: "une période hors de la saison habituelle de l'espèce",
    gel: "une gelée récente",
    chaleur: "des fortes chaleurs récentes",
  };
  const good = contrib.filter((x) => x.k !== worst.k && x.v >= 0.8 && ["pluie", "humidité", "température", "habitat"].includes(x.k)).map((x) => x.k);
  const goodTxt: Record<string, string> = { pluie: "les pluies", humidité: "l'humidité du sol", température: "les températures", habitat: "l'habitat" };
  let text: string;
  if (worst.c > Math.log(0.8)) text = "Aucun facteur nettement limitant : conditions globalement favorables.";
  else {
    text = `Score limité principalement par ${phrases[worst.k]}.`;
    if (good.length) text += ` ${good.map((g) => goodTxt[g]).join(", ").replace(/^./, (m) => m.toUpperCase())} ${good.length > 1 ? "sont" : "est"} pourtant favorable${good.length > 1 ? "s" : ""}.`;
  }
  return { key: worst.k, text, terms: terms.map((t) => ({ k: t.k, v: t.v })) };
}

/** Phrases explicatives construites à partir des composantes réelles du calcul. */
export function explain(comp: Comp | undefined, day: PointDay | undefined, sp: SpeciesKey): { good: string[]; bad: string[] } {
  const good: string[] = [];
  const bad: string[] = [];
  if (!comp || !day) return { good, bad };
  const eff = comp.eff_rain ?? 0;
  if (comp.R != null) {
    if (comp.R >= 0.7) good.push(`Pluies efficaces abondantes sur la fenêtre utile (≈ ${Math.round(eff)} mm pondérés par le délai).`);
    else if (comp.R < 0.35) bad.push(`Pluies insuffisantes sur la fenêtre utile (≈ ${Math.round(eff)} mm pondérés).`);
  }
  if (comp.trigger != null && comp.trigger >= 0.7) good.push("Épisode pluvieux marqué 1 à 3 semaines avant : délai compatible avec une sortie de fructifications.");
  if (comp.M != null) {
    const m = (comp as any).m != null ? Math.round((comp as any).m * 100) : Math.round(day.bucket_pct ?? 0);
    if (comp.M >= 0.7) good.push(`Sol humide (humidité relative estimée ≈ ${m} %, bilan hydrique et modèle météo).`);
    else if (comp.M < 0.3) bad.push(`Sol probablement sec (humidité relative estimée ≈ ${m} %).`);
  }
  if (comp.T != null && comp.t20 != null) {
    if (comp.T >= 0.8) good.push(`Températures dans la plage favorable (moyenne 20 j : ${comp.t20.toFixed(1)} °C).`);
    else if (comp.T < 0.4) {
      const lo = (params.species as any)[sp].temp_air20[1];
      bad.push(`Températures peu adaptées à l'espèce (moyenne 20 j : ${comp.t20.toFixed(1)} °C, ${comp.t20 < lo ? "trop frais" : "trop chaud"}).`);
    }
  }
  if (comp.S != null && comp.S < 0.3) bad.push("Hors de la période de fructification habituelle de l'espèce.");
  if (comp.frost != null && comp.frost < 1) bad.push("Gelée récente : fructifications compromises.");
  if (comp.heat != null && comp.heat < 1) bad.push("Plusieurs jours ≥ 30 °C : dessèchement probable.");
  if (comp.bonus != null && comp.bonus > 0.03) good.push("Rafraîchissement récent des températures, souvent associé aux poussées d'automne.");
  return { good, bad };
}

export function componentBars(comp: Comp | undefined) {
  if (!comp) return [];
  return [
    { k: "Pluie utile", v: comp.R },
    { k: "Humidité du sol", v: comp.M },
    { k: "Température", v: comp.T },
    { k: "Saison", v: comp.S },
  ].map((x) => ({ ...x, pct: pct(x.v) }));
}

/** Date cible par défaut : demain à partir de 14 h (heure de Paris), sinon aujourd'hui. */
export function defaultDateIndex(lt: Latest, now = new Date()): number {
  const fmt = new Intl.DateTimeFormat("fr-CA", { timeZone: "Europe/Paris", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", hourCycle: "h23" });
  const parts = Object.fromEntries(fmt.formatToParts(now).map((p) => [p.type, p.value]));
  const today = `${parts.year}-${parts.month}-${parts.day}`;
  const hour = parseInt(parts.hour, 10);
  const target = new Date(`${today}T12:00:00Z`);
  if (hour >= 14) target.setUTCDate(target.getUTCDate() + 1);
  const iso = target.toISOString().slice(0, 10);
  const k = lt.dates.indexOf(iso);
  if (k >= 0) return k;
  // données anciennes : dernière date disponible ≤ cible, sinon la dernière
  const before = lt.dates.filter((d) => d <= iso);
  return before.length ? lt.dates.indexOf(before[before.length - 1]) : lt.dates.length - 1;
}

export function parisToday(now = new Date()) {
  return new Intl.DateTimeFormat("fr-CA", { timeZone: "Europe/Paris" }).format(now);
}

export function ageHours(iso: string, now = new Date()) {
  return (now.getTime() - new Date(iso).getTime()) / 3.6e6;
}
