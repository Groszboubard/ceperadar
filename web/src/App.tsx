import { useEffect, useMemo, useRef, useState } from "react";
import { loadGbif, loadLatest, loadStatic } from "./data";
import {
  CLASS_LABEL, LEVELS, SPECIES_LABEL, ageHours, buildSectors, cellLatLon, cellScoreV1, cellW, computeDay, confLabel, defaultDateIndex,
  levelOf, parisToday, passes, passesNonScore, regionalIndex, wIndex,
} from "./model";
import type { Filters, Latest, Mode, StaticData } from "./types";
import { SPECIES } from "./types";
import type { Favorite } from "./storage";
import { loadFavorites, saveFavorites, uid } from "./storage";
import MapView, { type Basemap } from "./components/MapView";
import CellPanel from "./components/CellPanel";
import { Favorites, Journal } from "./components/Personal";
import Infos from "./components/Infos";

type Tab = "secteurs" | "zone" | "favoris" | "journal" | "infos";
type Layer = "score" | "weather" | "habitat" | "essence" | "rew" | "rain7" | "rain14" | "rain30" | "tmean7" | "tsoil7" | "quality" | "delta";
const LAYER_LABEL: Record<Layer, string> = {
  score: "Indice de favorabilité", weather: "Score météo seul", habitat: "Score habitat seul", essence: "Essence dominante",
  rew: "Humidité du sol (relative)", rain7: "Pluie sur 7 jours", rain14: "Pluie sur 14 jours", rain30: "Pluie sur 30 jours",
  tmean7: "Température moyenne 7 j", tsoil7: "Température du sol 7 j", quality: "Qualité des données", delta: "Écart V1.1 − V1",
};
const ABSENT = "#a3a9a5";

const ESS_COLORS: Record<number, string> = {
  1: "#2f6b3a", 2: "#4f8a3c", 3: "#28524a", 4: "#a8692b", 5: "#7d5a2a", 6: "#c48a3a", 7: "#8f3f2a", 8: "#b8a04a",
  9: "#7b8f3a", 10: "#557a45", 11: "#c9c27a", 12: "#d0b070", 13: "#c9b98a", 14: "#d9d2b5", 15: "#c2a9c9", 16: "#8cb08a",
  17: "#9fc48f", 18: "#b7c9b0",
};
const ramp = (stops: [number, string][], v: number) => {
  let c = stops[0][1];
  for (const [t, col] of stops) if (v >= t) c = col;
  return c;
};
const RAIN: [number, string][] = [[0, "#f3efe3"], [5, "#cfe3ee"], [15, "#9ccbe0"], [30, "#5aa3c9"], [50, "#2a6fa8"], [80, "#173f7a"]];
const BUCKET: [number, string][] = [[0, "#c8a165"], [15, "#dcc58f"], [30, "#e9e3c3"], [50, "#b9d8c9"], [70, "#6fb3a5"], [85, "#2e7d74"]];
const RAIN30: [number, string][] = [[0, "#f3efe3"], [15, "#cfe3ee"], [40, "#9ccbe0"], [70, "#5aa3c9"], [110, "#2a6fa8"], [160, "#173f7a"]];
const QUAL: [number, string][] = [[0, "#7a5b9a"], [50, "#c9b3d9"], [75, "#e8eef0"], [85, "#8fbfb0"]];
const DELTA: [number, string][] = [[-100, "#b2182b"], [-15, "#ef8a62"], [-5, "#f7f7f7"], [5, "#a6dba0"], [15, "#1b7837"]];
const TEMP: [number, string][] = [[-50, "#3b5b92"], [5, "#6c8fc4"], [9, "#a9c4dc"], [12, "#e6ead8"], [15, "#f1d38a"], [18, "#e59a52"], [22, "#c8553d"]];

const DEFAULT_FILTERS: Filters = { mode: "all", minScore: 0, maxDist: 100, forestType: "all", minConf: 0, access: "all" };
const weekday = (iso: string) => new Date(iso + "T12:00:00Z").toLocaleDateString("fr-FR", { weekday: "short" });
const dayNum = (iso: string) => new Date(iso + "T12:00:00Z").getUTCDate();

export default function App() {
  const [st, setSt] = useState<StaticData | null>(null);
  const [lt, setLt] = useState<Latest | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    Promise.all([loadStatic(), loadLatest()]).then(([a, b]) => { setSt(a); setLt(b); }).catch((e) => setErr(String(e)));
  }, []);
  if (err) return <div className="splash"><h1>CèpeRadar</h1><p className="warn">Les données n'ont pas pu être chargées ({err}).</p><p>Le premier calcul n'a peut-être pas encore été publié, ou la connexion est interrompue. Réessayez dans quelques minutes.</p></div>;
  if (!st || !lt) return <div className="splash"><h1>CèpeRadar</h1><p>Chargement de la carte et des prévisions…</p></div>;
  return <Main st={st} lt={lt} />;
}

function Main({ st, lt }: { st: StaticData; lt: Latest }) {
  const [d, setD] = useState(() => defaultDateIndex(lt));
  const [f, setF] = useState<Filters>(DEFAULT_FILTERS);
  const [layer, setLayer] = useState<Layer>("score");
  const [tab, setTab] = useState<Tab>("secteurs");
  const [sel, setSel] = useState<number | null>(null);
  const [selSector, setSelSector] = useState<{ name: string; cells: number[] } | null>(null);
  const [fly, setFly] = useState<{ lat: number; lon: number; zoom?: number; t: number } | null>(null);
  const [access, setAccess] = useState(false);
  const [showGbif, setShowGbif] = useState(false);
  const [gbif, setGbif] = useState<any[] | null>(null);
  const [basemap, setBasemap] = useState<Basemap>("plan");
  const [favs, setFavs] = useState<Favorite[]>([]);
  const [journalPrefill, setJournalPrefill] = useState<{ place: string; lat: number; lon: number } | null>(null);
  const [showFilters, setShowFilters] = useState(false);
  const [diag, setDiag] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => { loadFavorites().then(setFavs); }, []);
  useEffect(() => { if (showGbif && !gbif) loadGbif().then((g) => setGbif(g?.obs ?? [])); }, [showGbif, gbif]);
  const updateFavs = (x: Favorite[]) => { setFavs(x); saveFavorites(x); };

  const cellIndex = useMemo(() => {
    const m = new Map<string, number>();
    st.cells.i.forEach((i, c) => m.set(`${i},${st.cells.j[c]}`, c));
    return m;
  }, [st]);

  const day = useMemo(() => computeDay(st, lt, f.mode, d), [st, lt, f.mode, d]);
  const prevDay = useMemo(() => (d > 0 ? computeDay(st, lt, f.mode, d - 1) : null), [st, lt, f.mode, d]);
  const sectors = useMemo(() => buildSectors(st, f, day, prevDay), [st, f, day, prevDay]);
  const regional = useMemo(() => regionalIndex(day), [day]);
  const dayRegional = useMemo(() => lt.dates.map((_, k) => lt.summary[f.mode]?.[k]?.regional ?? null), [lt, f.mode]);

  const { colors, uncertain } = useMemo(() => {
    const n = st.cells.i.length;
    const out: (string | null)[] = new Array(n);
    const unc: boolean[] = new Array(n).fill(false);
    const sp = f.mode === "all" ? null : f.mode;
    for (let c = 0; c < n; c++) {
      const show = passesNonScore(st, f, c, day);
      if (!show) { out[c] = null; continue; }
      const spc = sp ?? (day.species[c] >= 0 ? (["edulis", "pinophilus", "aereus", "reticulatus"] as const)[day.species[c]] : "edulis");
      if (layer === "score") {
        if (day.state[c] === 2) out[c] = ABSENT;
        else out[c] = passes(st, f, c, day) ? levelOf(day.score[c]).color : null;
        unc[c] = day.state[c] === 1 && out[c] !== null;
      } else if (layer === "weather") {
        const w = cellW(st, lt, c, spc, d);
        out[c] = Number.isNaN(w) ? ABSENT : levelOf(w).color;
        unc[c] = day.state[c] === 1;
      } else if (layer === "habitat") out[c] = levelOf(st.cells.H[spc][c]).color;
      else if (layer === "essence") out[c] = ESS_COLORS[st.cells.c1[c]] ?? null;
      else if (layer === "quality") out[c] = day.state[c] === 2 ? ABSENT : ramp(QUAL, day.conf[c]);
      else if (layer === "delta") {
        const v1 = cellScoreV1(st, lt, c, spc, d);
        out[c] = Number.isNaN(v1) || Number.isNaN(day.score[c]) ? ABSENT : ramp(DELTA, day.score[c] - v1);
      } else if (layer === "rew") {
        const v = lt.ulayers?.rew?.[d]?.[wIndex(st, lt, c)];
        out[c] = v == null ? ABSENT : ramp(BUCKET, v);
      } else {
        const v = lt.layers[layer]?.[d]?.[st.cells.wp[c]];
        out[c] = v == null ? ABSENT : ramp(layer.startsWith("rain") ? (layer === "rain30" ? RAIN30 : RAIN) : TEMP, v);
      }
    }
    return { colors: out, uncertain: unc };
  }, [st, lt, f, day, layer, d]);

  const todayIdx = lt.dates.indexOf(lt.today);
  const age = ageHours(lt.generated_at);
  const stale = age > 30 || lt.today < parisToday();
  const visibleDates = lt.dates.map((x, k) => k).filter((k) => k >= Math.max(0, todayIdx - 1));
  const favSet = new Set(favs.map((x) => `${x.i},${x.j}`));

  const openCell = (c: number, sectorName?: string, cells?: number[]) => {
    setSel(c);
    setSelSector(sectorName ? { name: sectorName, cells: cells ?? [] } : null);
    setTab("zone");
    requestAnimationFrame(() => panelRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
  };

  const toggleFav = () => {
    if (sel == null) return;
    const k = `${st.cells.i[sel]},${st.cells.j[sel]}`;
    if (favSet.has(k)) updateFavs(favs.filter((x) => `${x.i},${x.j}` !== k));
    else updateFavs([...favs, { id: uid(), i: st.cells.i[sel], j: st.cells.j[sel], name: selSector?.name ?? `Forêt de ${st.communes[st.cells.com[sel]]}`, note: "", created: new Date().toISOString() }]);
  };

  const target = lt.dates[d];
  const targetLabel = new Date(target + "T12:00:00Z").toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long" });
  const lead = lt.lead[d];
  const headline = lead === 1 ? "Où chercher des cèpes demain ?" : lead === 0 ? "Où chercher des cèpes aujourd'hui ?" : lead < 0 ? "Où étaient les conditions favorables ?" : "Où chercher des cèpes ces prochains jours ?";

  return (
    <div className="app">
      <aside className="side">
        <header className="top">
          <div className="brand">
            <svg viewBox="0 0 32 32" className="logo" aria-hidden><path d="M4 15c0-6 5-10 12-10s12 4 12 10c0 1-1 2-2 2H6c-1 0-2-1-2-2z" fill="#6b3f1d" /><path d="M11 17h10l-1 10c0 1-1 2-2 2h-4c-1 0-2-1-2-2z" fill="#e9dcc0" /></svg>
            <span>CèpeRadar</span>
          </div>
          <h1>{headline}</h1>
          <p className="sub">Prospection du <b>{targetLabel}</b>, matinée · calcul du {new Date(lt.generated_at).toLocaleString("fr-FR", { timeZone: "Europe/Paris", weekday: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}</p>
          {stale && <p className="warn">Données anciennes ({Math.round(age)} h) : la dernière actualisation automatique n'a pas abouti. Les scores ci-dessous ne sont pas à jour.</p>}
        </header>

        <div className="days" role="tablist" aria-label="Date de prospection">
          {visibleDates.map((k) => {
            const v = dayRegional[k];
            return (
              <button key={k} role="tab" aria-selected={k === d} className={`day ${k === d ? "on" : ""} ${lt.lead[k] > 3 ? "far" : ""}`} onClick={() => setD(k)}>
                <span className="wd">{lt.lead[k] === 0 ? "auj." : lt.lead[k] === 1 ? "dem." : weekday(lt.dates[k])}</span>
                <span className="dn">{dayNum(lt.dates[k])}</span>
                <span className="meter"><span style={{ height: `${v ?? 0}%`, background: levelOf(v ?? 0).color }} /></span>
                <span className="dv">{v == null ? "–" : Math.round(v)}</span>
              </button>
            );
          })}
        </div>
        {lead > 3 && <p className="note">Échéance J+{lead} : la pluie prévue reste incertaine, la tendance est indicative.</p>}

        <div className="stats">
          <div><b>{Number.isNaN(regional) ? "–" : Math.round(regional)}</b><span>indice régional</span></div>
          <div><b>{sectors.filter((s) => s.score >= 60).length}</b><span>secteurs ≥ 60</span></div>
          <div><b>{confLabel(Math.min(...SPECIES.map((s) => lt.conf[s][d])))}</b><span>confiance météo</span></div>
        </div>

        <div className="modes" role="radiogroup" aria-label="Espèce">
          {(["all", ...SPECIES] as Mode[]).map((m) => (
            <button key={m} role="radio" aria-checked={f.mode === m} className={f.mode === m ? "on" : ""} onClick={() => setF({ ...f, mode: m })}>
              {m === "all" ? "Tous les cèpes" : SPECIES_LABEL[m].replace(" (tête-de-nègre)", "").replace(" (réticulé)", "")}
            </button>
          ))}
        </div>

        <nav className="tabs" role="tablist">
          {([["secteurs", "Secteurs"], ["zone", "Zone"], ["favoris", `Favoris${favs.length ? ` (${favs.length})` : ""}`], ["journal", "Journal"], ["infos", "Infos"]] as [Tab, string][]).map(([k, l]) => (
            <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>{l}</button>
          ))}
        </nav>

        <div className="panel" ref={panelRef}>
          {tab === "secteurs" && (
            <>
              <button className="ghost filt-toggle" onClick={() => setShowFilters(!showFilters)} aria-expanded={showFilters}>
                {showFilters ? "Masquer les filtres" : "Filtres"}{JSON.stringify({ ...f, mode: "all" }) !== JSON.stringify({ ...DEFAULT_FILTERS }) ? " (actifs)" : ""}
              </button>
              {showFilters && (
                <div className="filters">
                  <label>Score minimal <b>{f.minScore}</b><input type="range" min={0} max={80} step={5} value={f.minScore} onChange={(e) => setF({ ...f, minScore: +e.target.value })} /></label>
                  <label>Distance de Bordeaux <b>≤ {f.maxDist} km</b><input type="range" min={10} max={100} step={5} value={f.maxDist} onChange={(e) => setF({ ...f, maxDist: +e.target.value })} /></label>
                  <label>Type de forêt
                    <select value={f.forestType} onChange={(e) => setF({ ...f, forestType: e.target.value as Filters["forestType"] })}>
                      <option value="all">Tous</option><option value="pins">Pins et conifères</option><option value="chenes">Chênes, hêtre, châtaignier</option>
                      <option value="mixte">Mixtes feuillus/résineux</option><option value="feuillus">Tous feuillus</option>
                    </select>
                  </label>
                  <label>Confiance minimale
                    <select value={f.minConf} onChange={(e) => setF({ ...f, minConf: +e.target.value as Filters["minConf"] })}>
                      <option value={0}>Toutes</option><option value={50}>Moyenne ou élevée</option><option value={75}>Élevée</option>
                    </select>
                  </label>
                  <label>Accès documenté
                    <select value={f.access} onChange={(e) => setF({ ...f, access: e.target.value as Filters["access"] })}>
                      <option value="all">Toutes les forêts</option><option value="public">Forêts publiques uniquement</option><option value="noprotected">Exclure les aires protégées</option>
                    </select>
                  </label>
                  <button className="ghost" onClick={() => setF({ ...DEFAULT_FILTERS, mode: f.mode })}>Réinitialiser</button>
                </div>
              )}
              {sectors.length === 0 ? (
                <p className="empty">Aucun secteur ne dépasse le seuil ce jour-là avec ces filtres. Essayez une autre date ou assouplissez les filtres.</p>
              ) : (
                <ol className="sectors">
                  {sectors.map((s) => {
                    const delta = s.prev == null ? null : s.score - s.prev;
                    return (
                      <li key={s.id}>
                        <button onClick={() => { setFly({ lat: s.lat, lon: s.lon, zoom: 12, t: Date.now() }); openCell(s.best, s.name, s.cells); }}>
                          <span className="sc" style={{ background: levelOf(s.score).color }}>{s.score}</span>
                          <span className="body">
                            <b>{s.name}</b>
                            <span className="muted small">{s.essence} · {s.dist} km · {s.cells.length} km² · confiance {confLabel(s.conf).toLowerCase()}</span>
                            {f.mode === "all" && s.species && <span className="small">Surtout {SPECIES_LABEL[s.species].toLowerCase()}</span>}
                          </span>
                          <span className={`delta ${delta == null ? "" : delta > 0 ? "up" : delta < 0 ? "down" : ""}`}>{delta == null ? "" : `${delta > 0 ? "+" : ""}${delta}`}</span>
                        </button>
                      </li>
                    );
                  })}
                </ol>
              )}
              <p className="muted small">Cellules contiguës regroupées en secteurs (blocs de 6 km au plus). Score du secteur = moyenne de ses 5 meilleures mailles. Variation par rapport à la veille.</p>
            </>
          )}
          {tab === "zone" && (sel == null
            ? <p className="empty">Touchez une maille colorée sur la carte, ou un secteur dans la liste, pour voir le détail du calcul.</p>
            : <CellPanel st={st} lt={lt} cell={sel} d={d} mode={f.mode} sectorName={selSector?.name} diag={diag} isFav={favSet.has(`${st.cells.i[sel]},${st.cells.j[sel]}`)} onToggleFav={toggleFav}
                onAddJournal={() => { const [la, lo] = cellLatLon(st, sel); setJournalPrefill({ place: selSector?.name ?? `Forêt de ${st.communes[st.cells.com[sel]]}`, lat: la, lon: lo }); setTab("journal"); }} />)}
          {tab === "favoris" && <Favorites st={st} lt={lt} favs={favs} cellIndex={cellIndex} onChange={updateFavs} onOpen={(c) => { const [la, lo] = cellLatLon(st, c); setFly({ lat: la, lon: lo, zoom: 13, t: Date.now() }); openCell(c); }} />}
          {tab === "journal" && <Journal prefill={journalPrefill} onPrefillUsed={() => setJournalPrefill(null)} />}
          {tab === "infos" && <Infos lt={lt} st={st} />}
        </div>
        <footer className="foot small muted">Indice environnemental indicatif, sans valeur d'autorisation. Cueillette soumise à l'accord du propriétaire. Identifiez avec certitude avant toute consommation.</footer>
      </aside>

      <main className="mapwrap">
        <MapView st={st} colors={colors} selected={sel} highlight={selSector?.cells ?? []} overlayAccess={access} gbif={showGbif ? gbif : null}
          favorites={favs} basemap={basemap} flyTo={fly} uncertain={uncertain} onSelect={(c) => (c == null ? setSel(null) : openCell(c))} />
        <div className="map-ctl">
          <select aria-label="Couche affichée" value={layer} onChange={(e) => setLayer(e.target.value as Layer)}>
            {(["score", "essence", "rew", "rain7", "rain14", "rain30", "tmean7", "tsoil7"] as Layer[]).map((k) => <option key={k} value={k}>{LAYER_LABEL[k]}</option>)}
            {diag && <optgroup label="Diagnostic">
              {(["weather", "habitat", "quality", "delta"] as Layer[]).map((k) => <option key={k} value={k}>{LAYER_LABEL[k]}</option>)}
            </optgroup>}
          </select>
          <label><input type="checkbox" checked={diag} onChange={(e) => { setDiag(e.target.checked); if (!e.target.checked && ["weather", "habitat", "quality", "delta"].includes(layer)) setLayer("score"); }} /> Mode diagnostic</label>
          <label><input type="checkbox" checked={access} onChange={(e) => setAccess(e.target.checked)} /> Forêts publiques / aires protégées</label>
          <label><input type="checkbox" checked={showGbif} onChange={(e) => setShowGbif(e.target.checked)} /> Observations publiques (GBIF)</label>
          <label><input type="checkbox" checked={basemap === "ortho"} onChange={(e) => setBasemap(e.target.checked ? "ortho" : "plan")} /> Photo aérienne</label>
        </div>
        <Legend layer={layer} />
      </main>
    </div>
  );
}

function Legend({ layer }: { layer: Layer }) {
  let items: [string, string][] = [];
  if (["score", "weather", "habitat"].includes(layer)) items = LEVELS.map((l, k) => [l.color, `${l.min}–${LEVELS[k + 1] ? LEVELS[k + 1].min - 1 : 100} ${l.label.toLowerCase()}`]);
  else if (layer === "essence") items = [1, 2, 4, 7, 9, 10, 8, 17, 18, 11].map((c) => [ESS_COLORS[c], CLASS_LABEL[c]]);
  else if (layer === "rain7" || layer === "rain14") items = RAIN.map(([t, c]) => [c, `≥ ${t} mm`]);
  else if (layer === "rain30") items = RAIN30.map(([t, c]) => [c, `≥ ${t} mm`]);
  else if (layer === "rew") items = BUCKET.map(([t, c]) => [c, `≥ ${t} %`]);
  else if (layer === "quality") items = QUAL.map(([t, c]) => [c, `confiance ≥ ${t}`]);
  else if (layer === "delta") items = DELTA.map(([t, c]) => [c, t === -100 ? "< −15 points" : `≥ ${t > 0 ? "+" : ""}${t} points`]);
  else items = TEMP.slice(1).map(([t, c]) => [c, `≥ ${t} °C`]);
  return (
    <div className="legend" aria-label="Légende">
      {items.map(([c, l]) => <div key={l}><span style={{ background: c }} />{l}</div>)}
      {(layer === "score" || layer === "weather") && <div><span className="hatch-swatch" />incertain</div>}
      <div><span style={{ background: ABSENT }} />données absentes</div>
      {["rain7", "rain14", "rain30", "tmean7", "tsoil7"].includes(layer) && <div className="muted small">Résolution météo ≈ 6,5 km</div>}
      {layer === "rew" && <div className="muted small">Météo 6,5 km × géologie 1/50 000</div>}
    </div>
  );
}
