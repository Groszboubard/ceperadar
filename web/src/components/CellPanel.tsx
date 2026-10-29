import { useEffect, useState } from "react";
import { loadPoint } from "../data";
import { CLASS_LABEL, SPECIES_LABEL, SPECIES_LATIN, cellLatLon, cellScore, cellScoreV1, cellW, componentBars, confLabel, explain, levelOf, limitingFactor, wIndex } from "../model";
import type { Latest, Mode, PointDetail, SpeciesKey, StaticData } from "../types";
import { SPECIES } from "../types";
import { ScoreBars, WeatherChart } from "./Spark";

interface Props {
  st: StaticData; lt: Latest; cell: number; d: number; mode: Mode; sectorName?: string; diag: boolean;
  isFav: boolean; onToggleFav: () => void; onAddJournal: () => void;
}

const fmt = (v: any, digits = 0, unit = "") => (v == null || Number.isNaN(v) ? "n. d." : `${Number(v).toFixed(digits)}${unit}`);
const dayLabel = (iso: string) => new Date(iso + "T12:00:00Z").toLocaleDateString("fr-FR", { weekday: "short", day: "numeric" });

export default function CellPanel({ st, lt, cell, d, mode, sectorName, diag, isFav, onToggleFav, onAddJournal }: Props) {
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
  const unit = st.cells.unit ? st.cells.unit[cell] : null;
  const wconf = lt.uconf && unit != null ? lt.uconf[d][unit] : lt.conf[sp][d];
  const conf = lt.bad_points.includes(wp) ? 0 : Math.min(st.cells.conf[cell], wconf);
  const [lat, lon] = cellLatLon(st, cell);
  const day = pt?.d[d];
  const ud = pt?.units && unit != null ? pt.units[String(unit)] : undefined;
  const comp = ud ? ud.comp[d]?.[sp] : day?.comp?.[sp];
  const lim = limitingFactor(st.cells.H[sp][cell], comp);
  const sIdx = pt ? pt.series_dates.indexOf(lt.dates[d]) - 1 : -1; // veille de la date cible
  const v1 = mode === "all" ? Math.max(...SPECIES.map((s) => cellScoreV1(st, lt, cell, s, d)).filter((x) => !Number.isNaN(x))) : cellScoreV1(st, lt, cell, mode, d);
  const lith0 = st.lithology && st.cells.lith ? st.lithology[st.cells.lith[cell]] : null;
  const lith = lith0 && lith0.key !== "inconnue" ? lith0 : null;
  const ruSrc = lith ? "géologie BRGM 1/50 000" : (st.cells as any).ru && (st.cells as any).ru[cell] >= 0 ? "carte des sols INRAE 1/1 000 000" : "valeur par défaut";
  const absent = Number.isNaN(score);
  const uncertain = !absent && conf < 50;
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
      {absent && <p className="warn">Données météo absentes ou inexploitables pour cette maille : aucun score n'est calculé (ce n'est pas un score défavorable).</p>}
      {uncertain && <p className="note">Score incertain : sources d'humidité contradictoires, échéance lointaine ou peuplement mal connu (confiance {conf}/100).</p>}
      <p className="lvl-line"><b>{Number.isNaN(score) ? "Données manquantes" : lvl.label}</b> pour le {dayLabel(lt.dates[d])}
        {Number.isFinite(prev) && !Number.isNaN(score) && <> · {score - prev >= 0 ? "+" : ""}{score - prev} par rapport à la veille</>}
        {" "}· confiance {confLabel(conf).toLowerCase()}</p>

      <div className="actions">
        <button onClick={onToggleFav}>{isFav ? "Retirer des favoris" : "Ajouter aux favoris"}</button>
        <a className="btn" href={navUrl} target="_blank" rel="noopener">Ouvrir dans la navigation</a>
        <button onClick={onAddJournal}>Noter une sortie ici</button>
      </div>
      <p className="note">Point d'arrivée indicatif. L'accès aux parcelles n'est pas vérifié : suivre uniquement les voies ouvertes au public.</p>

      {diag && (
        <section className="diag">
          <h3>Diagnostic du calcul</h3>
          {lim && <p><b>{lim.text}</b></p>}
          <table className="kv">
            <tbody>
              <tr><th>Score final</th><td>{absent ? "n. d." : score} / 100 ({SPECIES_LABEL[sp].toLowerCase()})</td></tr>
              <tr><th>Habitat H</th><td>{st.cells.H[sp][cell]} / 100</td></tr>
              <tr><th>Météo W</th><td>{Number.isNaN(cellW(st, lt, cell, sp, d)) ? "n. d." : cellW(st, lt, cell, sp, d)} / 100</td></tr>
              <tr><th>Pluie R · humidité M</th><td>{comp?.R != null ? Math.round(comp.R * 100) : "n. d."} · {comp?.M != null ? Math.round(comp.M * 100) : "n. d."}</td></tr>
              <tr><th>Température T · saison S</th><td>{comp?.T != null ? Math.round(comp.T * 100) : "n. d."} · {comp?.S != null ? Math.round(comp.S * 100) : "n. d."}</td></tr>
              <tr><th>Qualité des données</th><td>{conf} / 100 (maille {st.cells.conf[cell]}, météo {wconf}){pt?.suspect ? " · point météo atypique" : ""}</td></tr>
              {ud && <tr><th>Humidité du sol (veille)</th><td>bilan hydrique {ud.rew_a[sIdx] ?? "n. d."} % · modèle météo {ud.rew_b[sIdx] ?? "n. d."} % → retenu {ud.rew[sIdx] ?? "n. d."} %{ud.dis[d] != null && ud.dis[d]! > 0.35 ? " (sources en désaccord)" : ""}</td></tr>}
              {ud && <tr><th>Sol</th><td>{lith ? lith.label + " · " : ""}réserve utile 0–30 cm ≈ {Math.round(ud.ru)} mm ({ruSrc})</td></tr>}
              {st.cells.unk && st.cells.unk[cell] > 0 && <tr><th>Essence non cartographiée</th><td>{st.cells.unk[cell]} % des boisements de la maille</td></tr>}
              {!Number.isNaN(v1) && <tr><th>Score V1 → V1.1</th><td>{v1} → {absent ? "n. d." : score} ({st.cells.H_v1 ? `habitat ${st.cells.H_v1[sp][cell]} → ${st.cells.H[sp][cell]}` : ""}{lt.W_v1 ? `, météo ${lt.W_v1[sp][d][wp]} → ${cellW(st, lt, cell, sp, d)}` : ""})</td></tr>}
            </tbody>
          </table>
        </section>
      )}

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
        <p className="muted small">Score = habitat × météo. Habitat {SPECIES_LABEL[sp].toLowerCase()} : {st.cells.H[sp][cell]}/100 ; météo : {Number.isNaN(cellW(st, lt, cell, sp, d)) ? "inconnue" : cellW(st, lt, cell, sp, d) + "/100"}.</p>
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
            {lim && !diag && <p className="small"><b>{lim.text}</b></p>}
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
              <tr><th>Humidité relative du sol</th><td>{ud ? `${ud.rew[sIdx] ?? "n. d."} %` : `${fmt(day.bucket_pct)} %`} <span className="muted">(calcul CèpeRadar)</span></td></tr>
              <tr><th>Humidité sol 3–9 cm</th><td>{fmt(day.sm_model, 2)} m³/m³ <span className="muted">(modèle, tendance 7 j {fmt(day.sm_model_trend7, 2)})</span></td></tr>
              <tr><th>Bilan pluie − ETP 14 / 30 j</th><td>{fmt(day.balance14, 0)} / {fmt(day.balance30, 0)} mm</td></tr>
              <tr><th>Humidité air / point de rosée</th><td>{fmt(day.rh7)} % / {fmt(day.dew7, 1)} °C</td></tr>
              <tr><th>Ensoleillement moyen</th><td>{fmt(day.sun7_h, 1)} h/j</td></tr>
            </tbody>
          </table>
          {pt && <WeatherChart dates={pt.series_dates} precip={pt.s.precip} tmin={pt.s.tmin} tmax={pt.s.tmax} todayIdx={sTodayIdx} />}
          <p className="muted small">Point météo {pt?.lat.toFixed(2)}, {pt?.lon.toFixed(2)} (maille du modèle {pt?.model_lat?.toFixed(2)}, {pt?.model_lon?.toFixed(2)}) : pluie et températures s'appliquent à un carré d'environ 6,5 km ; l'humidité du sol est ensuite différenciée selon la géologie de chaque maille. Source : Open-Meteo, calcul du {new Date(lt.generated_at).toLocaleString("fr-FR")}.</p>
        </section>
      )}

      <section>
        <h3>Terrain</h3>
        <table className="kv">
          <tbody>
            <tr><th>Peuplement</th><td>{comps.map((x) => `${CLASS_LABEL[x.c]} (${x.p} %)`).join(", ") || "n. d."}</td></tr>
            <tr><th>Lisières / mélange</th><td>densité de lisière {st.cells.edge[cell]} % · mélange d'essences {st.cells.mix[cell]} %</td></tr>
            <tr><th>Sol</th><td>{lith ? `${lith.label}${lith.ph ? ` · pH indicatif ≈ ${lith.ph}` : ""}` : "géologie non disponible"}{(st.cells as any).ru && (st.cells as any).ru[cell] >= 0 ? ` · réserve utile 0–30 cm ≈ ${(st.cells as any).ru[cell]} mm (${ruSrc})` : ""}{st.cells.hydro && st.cells.hydro[cell] >= 30 ? " · sols souvent engorgés" : ""}</td></tr>
            <tr><th>Relief</th><td>{st.cells.elev[cell] >= -50 ? `${st.cells.elev[cell]} m` : "n. d."} · pente {st.cells.slope[cell] >= 0 ? (st.cells.slope[cell] / 10).toFixed(1) + "°" : "n. d."} · position {st.cells.tpi[cell] < -2 ? "basse" : st.cells.tpi[cell] > 2 ? "haute" : "neutre"}</td></tr>
          </tbody>
        </table>
        <p className="muted small">Peuplements : IGN BD Forêt® V2 actualisée par le couvert arboré ESA WorldCover 2021 et les coupes détectées par satellite (Hansen/UMD). Sol : géologie BRGM 1/50 000 si disponible, sinon réserve utile INRAE 1/1 000 000 (valeurs indicatives, pas des mesures à la parcelle). Relief : Copernicus DEM.</p>
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
