// Stockage strictement local (IndexedDB du navigateur). Rien n'est envoyé ni publié.
import { createStore, get, set } from "idb-keyval";

const store = createStore("ceperadar", "perso");

export interface Favorite { id: string; i: number; j: number; name: string; note: string; created: string }
export interface JournalEntry {
  id: string; date: string; place: string; lat: number | null; lon: number | null;
  species: string; count: number | null; qty: string; conditions: string; note: string;
  photo?: Blob | null; created: string;
}

export async function loadFavorites(): Promise<Favorite[]> {
  return (await get<Favorite[]>("favorites", store)) ?? [];
}
export async function saveFavorites(f: Favorite[]) {
  await set("favorites", f, store);
}
export async function loadJournal(): Promise<JournalEntry[]> {
  return (await get<JournalEntry[]>("journal", store)) ?? [];
}
export async function saveJournal(j: JournalEntry[]) {
  await set("journal", j, store);
}

export function download(name: string, content: string | Blob, type = "application/json") {
  const blob = typeof content === "string" ? new Blob([content], { type }) : content;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

const csvCell = (v: unknown) => {
  const s = v == null ? "" : String(v);
  return /[",;\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
};

export function journalToCSV(j: JournalEntry[]) {
  const cols: (keyof JournalEntry)[] = ["date", "place", "lat", "lon", "species", "count", "qty", "conditions", "note", "created"];
  return [cols.join(";"), ...j.map((e) => cols.map((c) => csvCell(e[c])).join(";"))].join("\n");
}

export async function exportAll() {
  const fav = await loadFavorites();
  const jr = await loadJournal();
  const journal = jr.map(({ photo, ...rest }) => ({ ...rest, has_photo: !!photo }));
  return JSON.stringify({ app: "CèpeRadar", exported_at: new Date().toISOString(), favorites: fav, journal }, null, 1);
}

export async function importAll(text: string) {
  const data = JSON.parse(text);
  if (!data || (data.app !== "CèpeRadar" && !data.favorites)) throw new Error("Fichier non reconnu");
  const fav = await loadFavorites();
  const ids = new Set(fav.map((f) => f.id));
  for (const f of data.favorites ?? []) if (!ids.has(f.id)) fav.push(f);
  await saveFavorites(fav);
  const jr = await loadJournal();
  const jids = new Set(jr.map((e) => e.id));
  for (const e of data.journal ?? []) if (!jids.has(e.id)) jr.push({ ...e, photo: null });
  await saveJournal(jr);
  return { favorites: fav.length, journal: jr.length };
}

/** Réduit une photo à 1280 px (JPEG) pour limiter la place occupée dans le navigateur. */
export async function shrinkPhoto(file: File): Promise<Blob> {
  const bmp = await createImageBitmap(file);
  const scale = Math.min(1, 1280 / Math.max(bmp.width, bmp.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(bmp.width * scale);
  canvas.height = Math.round(bmp.height * scale);
  canvas.getContext("2d")!.drawImage(bmp, 0, 0, canvas.width, canvas.height);
  return await new Promise((res) => canvas.toBlob((b) => res(b ?? file), "image/jpeg", 0.8));
}

export const uid = () => Math.random().toString(36).slice(2) + Date.now().toString(36);
