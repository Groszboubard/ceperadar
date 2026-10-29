import { useEffect, useState } from "react";
import { loadBacktest, loadFailedStatus, loadHistory, loadStaticMeta, loadStatus } from "../data";
import { SPECIES_LABEL } from "../model";
import type { Latest } from "../types";

const auc = (x: any) => (x && x.n ? `${x.auc.toFixed(2)} [${x.ci90[0].toFixed(2)}–${x.ci90[1].toFixed(2)}], n = ${x.n}` : "données insuffisantes");

export default function Infos({ lt }: { lt: Latest }) {
  const [status, setStatus] = useState<any>(null);
  const [failed, setFailed] = useState<any>(null);
  const [meta, setMeta] = useState<any>(null);
  const [bt, setBt] = useState<any>(null);
  const [hist, setHist] = useState<any>(null);
  useEffect(() => {
    loadStatus().then(setStatus);
    loadFailedStatus().then(setFailed);
    loadStaticMeta().then(setMeta);
    loadBacktest().then(setBt);
    loadHistory().then(setHist);
  }, []);
  const lastFail = failed && status && failed.finished_at > status.finished_at ? failed : null;
  return (
    <div className="infos">
      <section>
        <h3>À lire avant de partir</h3>
        <ul>
          <li>Le score est un <b>indice de favorabilité environnementale</b> (0–100), pas une probabilité de trouver des cèpes. Il n'a pas encore été calibré sur des récoltes réelles.</li>
          <li>La forêt des Landes de Gascogne et du Médoc est en grande majorité <b>privée</b> : la cueillette y nécessite l'accord du propriétaire. Un chemin visible sur la carte ne donne pas de droit d'accès.</li>
          <li>Respecter les <b>arrêtés préfectoraux</b> (risque incendie, fermeture des massifs), les limitations de récolte locales et les réglementations des aires protégées.</li>
          <li>Ne consommer un champignon qu'après une <b>identification certaine</b> ; en cas de doute, demander à un pharmacien ou à une société mycologique.</li>
        </ul>
      </section>

      <section>
        <h3>Fraîcheur des données</h3>
        <p>Calcul du {new Date(lt.generated_at).toLocaleString("fr-FR", { timeZone: "Europe/Paris" })} (exécution {lt.kind === "evening" ? "du soir" : lt.kind === "morning" ? "du matin" : "manuelle"}). Actualisations automatiques prévues vers 19 h 30 et 5 h 30, heure de Paris.</p>
        {status && <p className="muted small">Dernière exécution réussie : {status.duration_s} s, {status.steps?.[0]?.requests} requêtes Open-Meteo (poids {status.steps?.[0]?.weight}). {status.warnings?.length ? `Avertissements : ${status.warnings.join(" ; ")}` : "Aucun avertissement."}</p>}
        {lastFail && <p className="warn">Dernière tentative en échec le {new Date(lastFail.finished_at).toLocaleString("fr-FR")} : {lastFail.error}. Les données affichées sont celles du dernier calcul réussi.</p>}
        {hist?.runs?.length > 1 && (
          <details>
            <summary>Historique des calculs ({hist.runs.length})</summary>
            <table className="kv small">
              <thead><tr><th>Calcul</th><th>Indice régional (tous cèpes) par date cible</th></tr></thead>
              <tbody>
                {hist.runs.slice(-14).reverse().map((r: any) => (
                  <tr key={r.date + r.kind}><th>{r.date} {r.kind === "evening" ? "soir" : r.kind === "morning" ? "matin" : "manuel"}</th>
                    <td>{Object.entries(r.summary.all || {}).slice(0, 4).map(([d, s]: any) => `${d.slice(5)} : ${s?.regional ?? "–"}`).join(" · ")}</td></tr>
                ))}
              </tbody>
            </table>
          </details>
        )}
      </section>

      <section>
        <h3>Comment le score est calculé</h3>
        <p><b>Score = Habitat × Météo / 100</b>, calculé par espèce. Un habitat inadapté ou une météo défavorable suffit donc à faire chuter le score.</p>
        <p><b>Habitat</b> (permanent, maille de 1 km) : affinité de l'espèce pour chaque essence de la BD Forêt® V2, part boisée, lisières et mélange d'essences, pH du sol (SoilGrids) et, faiblement, la topographie.</p>
        <p><b>Météo</b> (point tous les ~9 km, mise à jour quotidienne) : pluie efficace sur une fenêtre de 1 à 5 semaines selon l'espèce et épisode pluvieux déclencheur, humidité du sol issue d'un bilan pluie − évapotranspiration, températures moyennes sur 20 j, 7 j et du sol, saisonnalité, pénalités de gel et de forte chaleur.</p>
        <p className="muted small">Les fenêtres reprennent notamment un suivi de dix ans de <i>B. edulis</i> en hêtraie (pluie utile sur ~26 jours, optimum thermique ~13 °C sur 20 jours). Les autres paramètres sont des a priori écologiques à recalibrer avec vos relevés. Détail complet : docs/MODELE.md dans le dépôt.</p>
        <p><b>Confiance</b> : élevée, moyenne ou faible selon la part de prévision dans le calcul, l'échéance, et la disponibilité des données de sol et de relief. Au-delà de J+3, la tendance est indicative.</p>
      </section>

      <section>
        <h3>Validation historique</h3>
        {!bt && <p className="muted">Le test historique n'a pas encore été exécuté.</p>}
        {bt && (
          <>
            <p className="small">AUC : probabilité qu'une observation publique (GBIF) soit mieux classée qu'un témoin tiré au hasard ; 0,5 = pas mieux que le hasard. Intervalle à 90 % entre crochets.</p>
            <table className="kv small">
              <tbody>
                <tr><th>Date d'observation vs reste de l'année</th><td>{auc(bt.temporal?.all?.model_vs_year)}</td></tr>
                <tr><th>… saison seule (référence)</th><td>{auc(bt.temporal?.all?.season_only_vs_year)}</td></tr>
                <tr><th>Date d'observation vs ±30 jours</th><td>{auc(bt.temporal?.all?.model_vs_pm30days)}</td></tr>
                <tr><th>Maille observée vs mailles forestières (habitat)</th><td>{auc(bt.spatial?.all)}</td></tr>
                <tr><th>… couverture forestière seule (référence)</th><td>{auc(bt.spatial?.baseline_forest_cover)}</td></tr>
                {Object.keys(SPECIES_LABEL).map((s) => (
                  <tr key={s}><th>{SPECIES_LABEL[s as keyof typeof SPECIES_LABEL]} (temporel / spatial)</th><td>{auc(bt.temporal?.[s]?.model_vs_year)} / {auc(bt.spatial?.[s])}</td></tr>
                ))}
              </tbody>
            </table>
            <ul className="muted small">{(bt.notes || []).map((n: string) => <li key={n}>{n}</li>)}</ul>
          </>
        )}
      </section>

      <section>
        <h3>Sources</h3>
        <ul className="small">
          <li>Peuplements forestiers : IGN BD Forêt® V2 via la Géoplateforme (Licence Ouverte 2.0){meta?.sources?.bdforet ? ` — ${meta.sources.bdforet.polygons.toLocaleString("fr-FR")} polygones` : ""}.</li>
          <li>Forêts publiques et aires protégées : Géoplateforme IGN / INPN.</li>
          <li>Météo : {lt.weather_source.name} — {lt.weather_source.licence}. {lt.weather_source.past}.</li>
          <li>Sol : SoilGrids 2.0, ISRIC (CC BY 4.0), 250 m, valeurs modélisées.</li>
          <li>Relief : Copernicus DEM GLO-30 (© DLR / Airbus, programme Copernicus).</li>
          <li>Observations : GBIF.org, contributeurs iNaturalist et autres jeux de données (CC0 / CC BY / CC BY-NC).</li>
          <li>Communes : API Découpage administratif (geo.api.gouv.fr). Fonds de carte : Plan IGN et orthophotos (Géoplateforme).</li>
        </ul>
        {meta && <p className="muted small">Couches permanentes construites le {new Date(meta.generated_at).toLocaleDateString("fr-FR")}.</p>}
      </section>
    </div>
  );
}
