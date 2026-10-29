import { useEffect, useState } from "react";
import { loadBacktest, loadFailedStatus, loadHistory, loadStaticMeta, loadStatus } from "../data";
import { SPECIES_LABEL } from "../model";
import type { Latest, StaticData } from "../types";

const auc = (x: any) => {
  if (!x || !x.n) return "aucune donnée";
  const base = `${x.auc.toFixed(2)} [${x.ci90[0].toFixed(2)}–${x.ci90[1].toFixed(2)}], n = ${x.n}`;
  return x.conclusive === false || x.n < 30 ? `${base} — non concluant` : base;
};
const pc = (x: number | undefined | null) => (x == null ? "–" : `${Math.round(x * 100)} %`);

export default function Infos({ lt, st }: { lt: Latest; st: StaticData }) {
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

      {lt.summary_v1 && (
        <section>
          <h3>Comparaison V1 / V1.1</h3>
          <p className="small">Mêmes données météo, calculées avec les deux versions du modèle (« tous les cèpes »). Pour chaque jour : indice régional, part des mailles à 0, sous 20 et à 60 ou plus.</p>
          <table className="kv small">
            <thead><tr><th>Date</th><td><b>V1</b></td><td><b>V1.1</b></td></tr></thead>
            <tbody>
              {lt.dates.map((d, k) => {
                const a = lt.summary_v1!.all[k] as any, b = lt.summary.all[k] as any;
                if (!a || !b || lt.lead[k] < 0) return null;
                return (
                  <tr key={d}><th>{new Date(d + "T12:00:00Z").toLocaleDateString("fr-FR", { weekday: "short", day: "numeric" })}</th>
                    <td>{a.regional} · 0 : {pc(a.share0)} · &lt;20 : {pc(a.share_lt20)} · ≥60 : {a.n60}</td>
                    <td>{b.regional} · 0 : {pc(b.share0)} · &lt;20 : {pc(b.share_lt20)} · ≥60 : {b.n60}</td></tr>
                );
              })}
            </tbody>
          </table>
          <p className="muted small">En mode diagnostic, la couche « Écart V1.1 − V1 » montre où et de combien les scores ont changé, et la fiche d'une maille détaille l'évolution de l'habitat et de la météo.</p>
        </section>
      )}

      {lt.qc && (
        <section>
          <h3>Contrôles automatiques du dernier calcul</h3>
          <ul className="small">
            <li>Historique météo exploitable : {lt.qc.history_days} jours (depuis le {lt.qc.first_valid_day}).</li>
            <li>Données manquantes (40 derniers jours + prévisions) : pluie {pc(lt.qc.missing_rate?.precip)}, température {pc(lt.qc.missing_rate?.tmean)}, humidité du sol modélisée {pc(lt.qc.missing_rate?.sm)} / {pc(lt.qc.missing_rate?.sm2)}.</li>
            <li>Points météo sans données : {lt.bad_points.length} (mailles grises) ; points à cumul de pluie atypique : {lt.suspect_points?.length ?? 0} (confiance réduite).</li>
            <li>Valeurs hors bornes physiques écartées : {Object.values(lt.qc.out_of_range || {}).reduce((a: number, b: any) => a + (b as number), 0)}.</li>
          </ul>
        </section>
      )}

      <section>
        <h3>Comment le score est calculé</h3>
        <p><b>Score = Habitat × Météo / 100</b>, calculé par espèce. Un habitat inadapté ou une météo défavorable suffit donc à faire chuter le score.</p>
        <p><b>Habitat</b> (permanent, maille de 1 km) : affinité de l'espèce pour chaque essence de la BD Forêt® V2 actualisée par satellite (couvert arboré 2021, coupes rases jusqu'en 2024), part boisée, lisières et mélange d'essences, pH indicatif et engorgement selon la géologie BRGM et, faiblement, la topographie.</p>
        <p><b>Météo</b> (point tous les ~6,5 km, mise à jour quotidienne) : pluie efficace sur une fenêtre de 1 à 5 semaines selon l'espèce et épisode pluvieux déclencheur, températures moyennes sur 20 j, 7 j et du sol, saisonnalité, pénalités de gel et de forte chaleur.</p>
        <p><b>Humidité du sol</b> (V1.1) : réservoir de la couche 0–30 cm dont la capacité dépend de la géologie (sables landais ≈ 22 mm, alluvions ≈ 70 mm), avec interception par la canopée et pertes qui ralentissent quand le sol s'assèche, combiné à 40 % avec l'humidité modélisée par Open-Meteo (3–27 cm). Quand les deux sources divergent, la maille est hachurée « incertaine » plutôt que déclarée défavorable.</p>
        <p className="muted small">Les fenêtres reprennent notamment un suivi de dix ans de <i>B. edulis</i> en hêtraie (pluie utile sur ~26 jours, optimum thermique ~13 °C sur 20 jours). Les autres paramètres sont des a priori écologiques à recalibrer avec vos relevés. Détail complet : docs/MODELE.md dans le dépôt.</p>
        <p><b>Confiance</b> : élevée, moyenne ou faible selon la part de prévision dans le calcul, l'échéance, et la disponibilité des données de sol et de relief. Au-delà de J+3, la tendance est indicative.</p>
      </section>

      <section>
        <h3>Validation historique</h3>
        {!bt && <p className="muted">Le test historique n'a pas encore été exécuté.</p>}
        {bt && (
          <>
            <p className="small">AUC : probabilité qu'une observation publique (GBIF) soit mieux classée qu'un témoin tiré au hasard ; 0,5 = pas mieux que le hasard. Intervalle à 90 % entre crochets.</p>
            {bt.temporal?.all?.v11 ? (
              <>
                <p className="small">Observations : {bt.n_obs_total} ({Object.entries(bt.n_obs_by_source || {}).map(([k, v]) => `${k} ${v}`).join(", ")}). Aucune n'a servi à régler les paramètres.</p>
                <table className="kv small">
                  <thead><tr><th>Test</th><td><b>V1</b></td><td><b>V1.1</b></td></tr></thead>
                  <tbody>
                    <tr><th>Date observée vs reste de l'année</th><td>{auc(bt.temporal.all.v1.model_vs_year)}</td><td>{auc(bt.temporal.all.v11.model_vs_year)}</td></tr>
                    <tr><th>… saison seule (référence)</th><td colSpan={2}>{auc(bt.temporal.all.v11.season_only_vs_year)}</td></tr>
                    <tr><th>Date observée vs ±30 jours</th><td>{auc(bt.temporal.all.v1.model_vs_pm30days)}</td><td>{auc(bt.temporal.all.v11.model_vs_pm30days)}</td></tr>
                    <tr><th>Maille observée vs mailles forestières</th><td>{auc(bt.spatial?.all?.v1)}</td><td>{auc(bt.spatial?.all?.v11)}</td></tr>
                    <tr><th>… couverture forestière seule</th><td colSpan={2}>{auc(bt.spatial?.baseline_forest_cover)}</td></tr>
                    <tr><th>Automnes humides / secs (V1.1)</th><td colSpan={2}>{auc(bt.temporal.wet_autumns)} / {auc(bt.temporal.dry_autumns)}</td></tr>
                    <tr><th>Années impaires / paires (V1.1)</th><td colSpan={2}>{auc(bt.temporal.odd_years?.v11?.model_vs_year)} / {auc(bt.temporal.even_years?.v11?.model_vs_year)}</td></tr>
                    {Object.keys(SPECIES_LABEL).map((s) => (
                      <tr key={s}><th>{SPECIES_LABEL[s as keyof typeof SPECIES_LABEL]} (temporel)</th><td>{auc(bt.temporal?.[s]?.v1?.model_vs_year)}</td><td>{auc(bt.temporal?.[s]?.v11?.model_vs_year)}</td></tr>
                    ))}
                  </tbody>
                </table>
                {bt.sensitivity && (
                  <details>
                    <summary>Sensibilité des coefficients (cèpe de Bordeaux, AUC temporelle)</summary>
                    <table className="kv small"><tbody>
                      {Object.entries(bt.sensitivity).map(([k, v]: any) => <tr key={k}><th>{k.replace(/_/g, " ")}</th><td>{auc(v)}</td></tr>)}
                    </tbody></table>
                  </details>
                )}
                {bt.bias && <p className="muted small">Biais de déclaration : {pc(bt.bias.weekend_share)} des observations un week-end (attendu sans biais : {pc(bt.bias.weekend_expected)}) ; distance médiane à Bordeaux {bt.bias.median_dist_obs_km} km contre {bt.bias.median_dist_forest_km} km pour l'ensemble des forêts.</p>}
              </>
            ) : (
              <table className="kv small">
                <tbody>
                  <tr><th>Date d'observation vs reste de l'année</th><td>{auc(bt.temporal?.all?.model_vs_year)}</td></tr>
                  <tr><th>Maille observée vs mailles forestières</th><td>{auc(bt.spatial?.all)}</td></tr>
                </tbody>
              </table>
            )}
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
          <li>Actualisation des peuplements : ESA WorldCover 2021 (CC BY 4.0) et Hansen/UMD Global Forest Change (CC BY 4.0).</li>
          <li>Géologie : BRGM, cartes géologiques harmonisées à 1/50 000 (BD Charm-50).</li>
          <li>Observations : GBIF.org et iNaturalist (dates et positions uniquement, pour la validation).</li>
          <li>Relief : Copernicus DEM GLO-30 (© DLR / Airbus, programme Copernicus).</li>
          <li>Observations : GBIF.org, contributeurs iNaturalist et autres jeux de données (CC0 / CC BY / CC BY-NC).</li>
          <li>Communes : API Découpage administratif (geo.api.gouv.fr). Fonds de carte : Plan IGN et orthophotos (Géoplateforme).</li>
        </ul>
        {meta && <p className="muted small">Couches permanentes construites le {new Date(meta.generated_at).toLocaleDateString("fr-FR")}.</p>}
      </section>
    </div>
  );
}
