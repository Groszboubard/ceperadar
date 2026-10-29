// Jeu de données SYNTHÉTIQUE minimal, utilisé uniquement par les tests.
import { describe, expect, it } from "vitest";
import { buildSectors, computeDay, defaultDateIndex, levelOf, regionalIndex } from "./model";
import type { Filters, Latest, StaticData } from "./types";

function fixture(): { st: StaticData; lt: Latest } {
  // 3 bois : un bloc 3×3 (habitat fort), un bloc 2×2 (habitat moyen), une maille isolée
  const coords: [number, number][] = [];
  for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) coords.push([i, j]);
  for (let i = 10; i < 12; i++) for (let j = 10; j < 12; j++) coords.push([i, j]);
  coords.push([20, 20]);
  const n = coords.length;
  const H = coords.map(([i]) => (i < 3 ? 90 : i < 12 ? 60 : 30));
  const arr = (v: number) => new Array(n).fill(v);
  const st: StaticData = {
    version: "t", generated_at: "", grid: { lat0: 44.8, lon0: -0.6, dlat: 0.009, dlon: 0.0127, n: 100, radius_km: 100 },
    communes: ["Alpha", "Beta"], protected_names: [], weather_points: { lat: [44.8, 44.9], lon: [-0.6, -0.5] },
    cells: {
      i: coords.map((c) => c[0]), j: coords.map((c) => c[1]), wp: coords.map(([i]) => (i < 3 ? 0 : 1)), com: coords.map(([i]) => (i < 3 ? 0 : 1)),
      dist: arr(20), forest: arr(80), c1: arr(9), p1: arr(80), c2: arr(1), p2: arr(10), c3: arr(4), p3: arr(5), edge: arr(5), mix: arr(30),
      ph: arr(50), sand: arr(80), clay: arr(5), soc: arr(20), elev: arr(50), slope: arr(5), north: arr(0), tpi: arr(0), pub: arr(0), prot: arr(0), protn: arr(-1), conf: arr(85),
      H: { edulis: H, pinophilus: H.map((h) => h - 20), aereus: H.map((h) => h / 2), reticulatus: H.map((h) => h / 3) },
    },
  };
  const W = (a: number, b: number) => [[a, b], [a, b], [a, b]];
  const lt: Latest = {
    generated_at: "2026-10-29T19:30:00+01:00", today: "2026-10-29", kind: "evening", model_version: "t",
    dates: ["2026-10-28", "2026-10-29", "2026-10-30"], lead: [-1, 0, 1],
    W: { edulis: W(90, 80), pinophilus: W(70, 70), aereus: W(20, 20), reticulatus: [[10, 255], [10, 255], [10, 255]] },
    conf: { edulis: [95, 90, 80], pinophilus: [95, 90, 80], aereus: [95, 90, 80], reticulatus: [95, 90, 80] },
    bad_points: [], layers: {}, summary: {}, weather_source: { name: "", licence: "", url: "", point_spacing_km: "", past: "" },
  };
  return { st, lt };
}
const F: Filters = { mode: "all", minScore: 0, maxDist: 100, forestType: "all", minConf: 0, access: "all" };

describe("scores", () => {
  it("score = H × W / 100, maximum sur les espèces en mode « tous »", () => {
    const { st, lt } = fixture();
    const day = computeDay(st, lt, "all", 2);
    expect(day.score[0]).toBe(81); // 90 × 90 / 100
    expect(day.score[9]).toBe(48); // 60 × 80 / 100
    const ret = computeDay(st, lt, "reticulatus", 2);
    expect(Number.isNaN(ret.score[9])).toBe(true); // W inconnu → pas de score inventé
  });
  it("niveaux", () => {
    expect(levelOf(85).label).toBe("Très favorable");
    expect(levelOf(10).label).toBe("Très défavorable");
  });
  it("indice régional = moyenne du décile supérieur", () => {
    const { st, lt } = fixture();
    expect(regionalIndex(computeDay(st, lt, "all", 2))).toBe(81);
  });
});

describe("secteurs", () => {
  it("regroupe les mailles contiguës et ne liste pas 9 fois le même bois", () => {
    const { st, lt } = fixture();
    const day = computeDay(st, lt, "all", 2);
    const sec = buildSectors(st, F, day, computeDay(st, lt, "all", 1));
    expect(sec.length).toBe(1); // seuil = 85e centile → seul le bloc fort passe
    expect(sec[0].cells.length).toBe(9);
    expect(sec[0].name).toContain("Alpha");
    expect(sec[0].prev).toBe(81);
  });
  it("respecte le score minimal", () => {
    const { st, lt } = fixture();
    const day = computeDay(st, lt, "all", 2);
    expect(buildSectors(st, { ...F, minScore: 90 }, day, null)).toEqual([]);
  });
});

describe("date cible", () => {
  it("demain après 14 h (Paris), aujourd'hui le matin", () => {
    const { lt } = fixture();
    expect(defaultDateIndex(lt, new Date("2026-10-29T19:00:00Z"))).toBe(2);
    expect(defaultDateIndex(lt, new Date("2026-10-29T06:00:00Z"))).toBe(1);
  });
});
