import type { Latest, PointDetail, StaticData } from "./types";

const BASE = `${import.meta.env.BASE_URL}data/`;

async function getJSON<T>(path: string, fresh = false): Promise<T> {
  const r = await fetch(BASE + path, { cache: fresh ? "no-cache" : "default" });
  if (!r.ok) throw new Error(`${path} : HTTP ${r.status}`);
  return (await r.json()) as T;
}

export const loadStatic = () => getJSON<StaticData>("static/cells.json");
export const loadLatest = () => getJSON<Latest>("forecast/latest.json", true);
export const loadStatus = () => getJSON<any>("status.json", true).catch(() => null);
export const loadFailedStatus = () => getJSON<any>("status_failed.json", true).catch(() => null);
export const loadHistory = () => getJSON<any>("history.json", true).catch(() => null);
export const loadStaticMeta = () => getJSON<any>("static/static_meta.json").catch(() => null);
export const loadBacktest = () => getJSON<any>("static/backtest.json").catch(() => null);
export const loadGbif = () => getJSON<any>("static/gbif.json").catch(() => null);
export const loadNormals = () => getJSON<any>("static/normals.json").catch(() => null);

const pointCache = new Map<number, Promise<PointDetail>>();
export function loadPoint(k: number, generatedAt: string) {
  const key = k;
  if (!pointCache.has(key)) pointCache.set(key, getJSON<PointDetail>(`forecast/points/${k}.json?v=${encodeURIComponent(generatedAt)}`));
  return pointCache.get(key)!;
}
