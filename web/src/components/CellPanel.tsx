import { useEffect, useState } from "react";
import { loadPoint } from "../data";
import { CLASS_LABEL, SPECIES_LABEL, SPECIES_LATIN, cellLatLon, cellScore, componentBars, confLabel, explain, levelOf } from "../model";
import type { Latest, Mode, PointDetail, SpeciesKey, StaticData } from "../types";
import { SPECIES } from "../types";
import { ScoreBars, WeatherChart } from "./Spark";

interface Props {
  st: StaticData; lt: Latest; cell: number; d: number; mode: Mode; sectorName?: string;
  isFav: boolean; onToggleFav: () => void; onAddJournal: () => void;
}

const fmt = (v: any, digits = 0, unit = "") => (v == null || Number.isNaN(v) ? "n. d." : `${Number(v).toFixed(digits)}${unit}`);
const dayLabel = (iso: string) => new Date(iso + "T12:00:00Z").toLocaleDateString("fr-FR", { weekday: "short", day: "numeric" });

export default function CellPanel({ st, lt, cell, d, mode, sectorName, isFav, onToggleFav, onAddJournal }: Props) {
  const wp = st.cells.wp[cell];
  const [pt, setPt] = useState<PointDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    setPt(null); setErr(null);
    loadPoint(wp, lt.generated_at).then(setPt).catch((e) => setErr(String(e)));
  }, [wp, lt.generated_at]);

  const scores = SPECIES.map((s) => ({ s, v: cellScore(st, lt, cell, s, d) })).sort((a, b) => (b.v || 0) - (a.v || 0));
  const sp: SpeciesKey = mode === "all" ? scores[0].s : mode;
  const score = mode === "all" ? scores[0].v : cellScore(st, lt, cell, mode, d);
  const lvl = levelOf(score || 0);
  const conf = Math.min(st.cells.conf[cell], lt.conf[sp][d]);
  const [lat, lon] = cellLatLon(st, cell);
  const day = pt?.d[d];
  const comp = day?.comp[sp];
  const ex = explain(comp, day, sp);
  const todayIdx = lt.dates.indexOf(lt.today);
  const trendIdx = lt.dates.map((_, k) => k).filter((k) => k >= todayIdx - 7 && k <= todayIdx + 3);
  const trend = trendIdx.map((k) => {
    const v = mode === "all" ? Math.max(...SPECIES.map((s) => cellScore(st, lt, cell, s, k)).filter((x) => !Number.isNaN(x))) : cellScore(st, lt, cell, mode, k);
    return Number.isFinite(v) ? v : null;
  });
  const prev = d > 0 ? (mode === "all" ? Math.max(...SPECIES.map((s) => cellScore(st, lt, cell, s, d - 1))) : cellScore(st, lt, cell, mode, d - 1)) : NaN;
  const comps = [1, 2, 3].map((k) => ({ c: (st.cells as any)[`c${k}`][cell] as number, p: (st.cells as any)[`p${k}`][cell] as number })).filter((x) => x.p > 0);
  const pub = st.cells.pub[cell], prot = st.cells.prot[cell];
  const sTodayIdx = pt ? pt.series_dates.indexOf(lt.today) : -1;
  const isAndroid = /Android/i.test(navigator.userAgent);
  const navUrl = isAndroid ? `geo:${lat.toFixed(5)},${lon.toFixed(5)}?q=${lat.toFixed(5)},${lon.toFixed(5)}` : `https://www.google.com/maps/search/?api=1&query=${lat.toFixed(5)},${lon.toFixed(5)}`;

  return (
    <article className="cell">
      <header className="cell-head">
        <div>
          <h2>{sectorName ?? `Secteur forestier de ${st.communes[st.cells.com[cell]]}`}</h2>
          <p className="muted">Maille de 1 km centrée sur {lat.toFixed(4)}, {lon.toFixed(4)} · {st.cells.dist[cell]} km de Bordeaux</p>
        </div>
        <div className="score-badge" style={{ background: lvl.color }}>
          <strong>{Number.isNaN(score) ? "?" : score}</strong><span>/100</span>
        </div>
      </header>
      <p className="lvl-line"><b>{Number.isNaN(score) ? "Données manquantes" : lvl.label}</b> pour le {dayLabel(lt.dates[d])}
        {Number.isFinite(prev) && !Number.isNaN(score) && <> · {score - prev >= 0 ? "+" : ""}{score - prev} par rapport à la veille</>}
        {" "}· confiance {confLabel(conf).toLowerCase()}</p>

      <div className="actions">
        <button onClick={onToggleFav}>{isFav ? "Retirer des favoris" : "Ajouter aux favoris"}</button>
        <a className="btn" href={navUrl} target="_blank" rel="noopener">Ouvrir dans la navigation</a>
        <button onClick={onAddJournal}>Noter une sortie ici</button>
      </div>
      <p className="note">Point d'arrivée indicatif. L'accès aux parcelles n'est pas vérifié : suivre uniquement les voies ouvertes au public.</p>

      <section>
        <h3>Espèces</h3>
        <ul className="sp-list">
          {scores.map(({ s, v }) => (
            <li key={s}>
              <span className="dot" style={{ background: levelOf(v || 0).color }} />
              <span>{SPECIES_LABEL[s]} <i>{SPECIES_LATIN[s]}</i></span>
              <b>{Number.isNaN(v) ? "?" : v}</b>
            </li>
          ))}
        </ul>
        <p className="muted small">Score = habitat × météo. Habitat {SPECIES_LABEL[sp].toLowerCase()} : {st.cells.H[sp][cell]}/100 ; météo : {lt.W[sp][d][wp] === 255 ? "inconnue" : lt.W[sp][d][wp] + "/100"}.</p>
      </section>

      <section>
        <h3>Pourquoi ce score</h3>
        {!pt && !err && <p className="muted">Chargement des conditions…</p>}
        {err && <p className="warn">Détail météo indisponible : {err}</p>}
        {comp && (
          <>
            <div className="comp-bars">
              {componentBars(comp).map((b) => (
                <div key={b.k} className="comp">
                  <span>{b.k}</span>
                  <div className="track"><div className="fill" style={{ width: `${b.v == null ? 0 : b.v * 100}%` }} /></div>
                  <b>{b.pct}</b>
                </div>
              ))}
            </div>
            <ul className="why">
              {ex.good.map((t) => <li key={t} className="pos">{t}</li>)}
              {ex.bad.map((t) => <li key={t} className="neg">{t}</li>)}
              {comps.length > 0 && <li className="neu">Peuplement : {comps.map((x) => `${CLASS_LABEL[x.c]} ${x.p} %`).join(", ")} (forêt sur {st.cells.forest[cell]} % de la maille).</li>}
            </ul>
          </>
        )}
        <p className="disclaimer">Il s'agit d'un indice environnemental, pas d'une observation confirmée de champignons.</p>
      </section>

      <section>
        <h3>Tendance</h3>
        <ScoreBars values={trend} labels={trendIdx.map((k) => dayLabel(lt.dates[k]).split(" ")[1])} todayIndex={trendIdx.indexOf(todayIdx)} selected={trendIdx.indexOf(d)} />
        <p className="muted small">7 jours passés (recalculés avec la météo observée) et 3 jours à venir (hachurés, prévision).</p>
      </section>

      {day && (
        <section>
          <h3>Conditions météo ({dayLabel(lt.dates[d])})</h3>
          <table className="kv">
            <tbody>
              <tr><th>Pluie 24 h / 3 j / 7 j</th><td>{fmt(day.rain1, 1)} / {fmt(day.rain3, 0)} / {fmt(day.rain7, 0)} mm</td></tr>
              <tr><th>Pluie 10 / 14 / 21 / 30 j</th><td>{fmt(day.rain10, 0)} / {fmt(day.rain14, 0)} / {fmt(day.rain21, 0)} / {fmt(day.rain30, 0)} mm</td></tr>
              <tr><th>Jours sans pluie</th><td>{fmt(day.dry_days)} · max journalier 14 j : {fmt(day.max_day_14, 0)} mm</td></tr>
              <tr><th>Pluie prévue 24 h / 72 h</th><td>{fmt(day.rain_next24, 1)} / {fmt(day.rain_next72, 0)} mm</td></tr>
              <tr><th>T. moy. 3 / 7 / 14 / 21 j</th><td>{fmt(day.tmean3, 1)} / {fmt(day.tmean7, 1)} / {fmt(day.tmean14, 1)} / {fmt(day.tmean21, 1)} °C</td></tr>
              <tr><th>Min / max sur 7 j</th><td>{fmt(day.tmin7, 1)} / {fmt(day.tmax7, 1)} °C · amplitude {fmt(day.amp7, 1)} °C</td></tr>
              <tr><th>Nuits ≤ 8 °C / gel (7 j)</th><td>{fmt(day.cold_nights7)} / {fmt(day.frost_nights7)}</td></tr>
              <tr><th>Sol 6 cm (moy. 7 j)</th><td>{fmt(day.tsoil7, 1)} °C</td></tr>
              <tr><th>Réserve en eau estimée</th><td>{fmt(day.bucket_pct)} % <span className="muted">(calcul CèpeRadar)</span></td></tr>
              <tr><th>Humidité sol 3–9 cm</th><td>{fmt(day.sm_model, 2)} m³/m³ <span className="muted">(modèle, tendance 7 j {fmt(day.sm_model_trend7, 2)})</span></td></tr>
              <tr><th>Bilan pluie − ETP 14 / 30 j</th><td>{fmt(day.balance14, 0)} / {fmt(day.balance30, 0)} mm</td></tr>
              <tr><th>Humidité air / point de rosée</th><td>{fmt(day.rh7)} % / {fmt(day.dew7, 1)} °C</td></tr>
              <tr><th>Ensoleillement moyen</th><td>{fmt(day.sun7_h, 1)} h/j</td></tr>
            </tbody>
          </table>
          {pt && <WeatherChart dates={pt.series_dates} precip={pt.s.precip} tmin={pt.s.tmin} tmax={pt.s.tmax} todayIdx={sTodayIdx} />}
          <p className="muted small">Point météo {pt?.lat.toFixed(2)}, {pt?.lon.toFixed(2)} (maille du modèle {pt?.model_lat?.toFixed(2)}, {pt?.model_lon?.toFixed(2)}) : une même valeur s'applique à toutes les mailles d'un carré d'environ 9 km. Source : Open-Meteo, calcul du {new Date(lt.generated_at).toLocaleString("fr-FR")}.</p>
        </section>
      )}

      <section>
        <h3>Terrain</h3>
        <table className="kv">
          <tbody>
            <tr><th>Peuplement</th><td>{comps.map((x) => `${CLASS_LABEL[x.c]} (${x.p} %)`).join(", ") || "n. d."}</td></tr>
            <tr><th>Lisières / mélange</th><td>densité de lisière {st.cells.edge[cell]} % · mélange d'essences {st.cells.mix[cell]} %</td></tr>
            <tr><th>Sol (5–15 cm)</th><td>pH ≈ {st.cells.ph[cell] >= 0 ? (st.cells.ph[cell] / 10).toFixed(1) : "n. d."} · sable {st.cells.sand[cell] >= 0 ? st.cells.sand[cell] + " %" : "n. d."} · argile {st.cells.clay[cell] >= 0 ? st.cells.clay[cell] + " %" : "n. d."}</td></tr>
            <tr><th>Relief</th><td>{st.cells.elev[cell] >= -50 ? `${st.cells.elev[cell]} m` : "n. d."} · pente {st.cells.slope[cell] >= 0 ? (st.cells.slope[cell] / 10).toFixed(1) + "°" : "n. d."} · position {st.cells.tpi[cell] < -2 ? "basse" : st.cells.tpi[cell] > 2 ? "haute" : "neutre"}</td></tr>
          </tbody>
        </table>
        <p className="muted small">Peuplements : IGN BD Forêt® V2 (millésime départemental, parfois ancien). Sol : SoilGrids 250 m, valeur modélisée et non mesurée à la parcelle. Relief : Copernicus DEM.</p>
      </section>

      <section>
        <h3>Accès et réglementation</h3>
        <ul className="why">
          {pub >= 30 ? <li className="neu">Forêt publique sur {pub} % de la maille (gestion ONF) : cueillette familiale généralement tolérée, sauf arrêté ou signalisation contraire.</li>
            : <li className="neg">Autorisation du propriétaire à vérifier : la forêt girondine et landaise est majoritairement privée.</li>}
          {prot > 0 && <li className="neg">Aire protégée sur {prot} % de la maille{st.cells.protn[cell] >= 0 ? ` (${st.protected_names[st.cells.protn[cell]]})` : ""} : réglementation spécifique, cueillette souvent interdite.</li>}
          <li className="neu">Vérifier les arrêtés préfectoraux (risque incendie, restrictions d'accès aux massifs) avant de partir.</li>
        </ul>
      </section>
    </article>
  );
}
