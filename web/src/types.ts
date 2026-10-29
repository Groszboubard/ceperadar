export type SpeciesKey = "edulis" | "pinophilus" | "aereus" | "reticulatus";
export type Mode = SpeciesKey | "all";
export const SPECIES: SpeciesKey[] = ["edulis", "pinophilus", "aereus", "reticulatus"];

export interface StaticData {
  version: string;
  generated_at: string;
  grid: { lat0: number; lon0: number; dlat: number; dlon: number; n: number; radius_km: number };
  communes: string[];
  protected_names: string[];
  weather_points: { lat: number[]; lon: number[] };
  units?: { wp: number[]; lith: number[]; ru: number[] };
  lithology?: { key: string; label: string; ru_mm: number | null; ph: number | null; hydro: number }[];
  cells: {
    i: number[]; j: number[]; wp: number[]; com: number[]; dist: number[]; forest: number[];
    c1: number[]; p1: number[]; c2: number[]; p2: number[]; c3: number[]; p3: number[];
    edge: number[]; mix: number[]; ph: number[]; sand: number[]; clay: number[]; soc: number[];
    elev: number[]; slope: number[]; north: number[]; tpi: number[];
    pub: number[]; prot: number[]; protn: number[]; conf: number[];
    H: Record<SpeciesKey, number[]>;
    // V1.1
    unit?: number[]; lith?: number[]; hydro?: number[]; unk?: number[]; forest_v1?: number[];
    H_v1?: Record<SpeciesKey, number[]>;
  };
}

export interface RegionalSummary { regional: number; p50: number; p90: number; max: number; n60: number; n80: number; share80: number }

export interface Latest {
  generated_at: string;
  today: string;
  kind: string;
  model_version: string;
  dates: string[];
  lead: number[];
  W: Record<SpeciesKey, number[][]>;
  conf: Record<SpeciesKey, number[]>;
  bad_points: number[];
  suspect_points?: number[];
  layers: Record<string, (number | null)[][]>;
  summary: Record<string, (RegionalSummary | null)[]>;
  // V1.1
  W_v1?: Record<SpeciesKey, number[][]>;
  uconf?: number[][];
  ulayers?: Record<string, (number | null)[][]>;
  summary_v1?: Record<string, (RegionalSummary | null)[]>;
  qc?: any;
  weather_source: { name: string; licence: string; url: string; point_spacing_km: string; past: string };
}

export interface Comp { R: number | null; M: number | null; T: number | null; S: number | null; frost: number | null; heat: number | null; bonus: number | null; eff_rain: number | null; trigger: number | null; t20: number | null; t7: number | null; ts7: number | null }
export interface PointDay { [k: string]: any; comp?: Record<SpeciesKey, Comp> }
export interface UnitDetail {
  lith: number; ru: number;
  rew_a: (number | null)[]; rew_b: (number | null)[]; rew: (number | null)[];
  comp: Record<SpeciesKey, Comp & { W: number | null; m: number | null }>[];
  dis: (number | null)[];
}
export interface PointDetail {
  generated_at: string; dates: string[]; series_dates: string[]; today: string; lat: number; lon: number;
  model_lat: number | null; model_lon: number | null; model_elev: number | null; suspect?: boolean;
  s: Record<string, (number | null)[]>;
  d: PointDay[];
  units?: Record<string, UnitDetail>;
}

export interface Filters {
  mode: Mode;
  minScore: number;
  maxDist: number;
  forestType: "all" | "pins" | "chenes" | "mixte" | "feuillus";
  minConf: 0 | 50 | 75;
  access: "all" | "public" | "noprotected";
}

export interface Sector {
  id: string;
  cells: number[];
  best: number;
  score: number;
  prev: number | null;
  name: string;
  commune: string;
  lat: number;
  lon: number;
  dist: number;
  essence: string;
  conf: number;
  species: SpeciesKey | null;
}
