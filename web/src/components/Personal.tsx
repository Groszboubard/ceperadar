import { useEffect, useState } from "react";
import { cellScore, levelOf } from "../model";
import type { Latest, StaticData } from "../types";
import { SPECIES } from "../types";
import type { Favorite, JournalEntry } from "../storage";
import { download, exportAll, importAll, journalToCSV, loadJournal, saveJournal, shrinkPhoto, uid } from "../storage";
import { ScoreBars } from "./Spark";

export function Favorites({ st, lt, favs, cellIndex, onChange, onOpen }: {
  st: StaticData; lt: Latest; favs: Favorite[]; cellIndex: Map<string, number>;
  onChange: (f: Favorite[]) => void; onOpen: (cell: number) => void;
}) {
  const todayIdx = lt.dates.indexOf(lt.today);
  const idxs = lt.dates.map((_, k) => k).filter((k) => k >= todayIdx - 7 && k <= todayIdx + 3);
  const [msg, setMsg] = useState("");
  if (!favs.length)
    return (
      <div className="empty">
        <p>Aucun favori pour l'instant.</p>
        <p className="muted">Touchez une maille sur la carte puis « Ajouter aux favoris » pour suivre son évolution jour après jour. Les favoris restent dans ce navigateur.</p>
        <ImportExport onDone={setMsg} />
        {msg && <p className="muted">{msg}</p>}
      </div>
    );
  return (
    <div className="favs">
      {favs.map((f) => {
        const c = cellIndex.get(`${f.i},${f.j}`);
        const vals = idxs.map((k) => {
          if (c === undefined) return null;
          const v = Math.max(...SPECIES.map((s) => cellScore(st, lt, c, s, k)).filter((x) => !Number.isNaN(x)));
          return Number.isFinite(v) ? v : null;
        });
        const now = c !== undefined ? vals[idxs.indexOf(Math.min(todayIdx + 1, lt.dates.length - 1))] : null;
        return (
          <div key={f.id} className="fav">
            <div className="fav-head">
              <input aria-label="Nom du favori" value={f.name} onChange={(e) => onChange(favs.map((x) => (x.id === f.id ? { ...x, name: e.target.value } : x)))} />
              <span className="pill" style={{ background: levelOf(now ?? 0).color }}>{now ?? "?"}</span>
            </div>
            <ScoreBars values={vals} labels={idxs.map((k) => lt.dates[k].slice(8))} todayIndex={idxs.indexOf(todayIdx)} />
            <textarea aria-label="Notes" placeholder="Notes personnelles" value={f.note} onChange={(e) => onChange(favs.map((x) => (x.id === f.id ? { ...x, note: e.target.value } : x)))} />
            <div className="actions">
              {c !== undefined && <button onClick={() => onOpen(c)}>Voir sur la carte</button>}
              <button className="ghost" onClick={() => confirm(`Supprimer « ${f.name} » ?`) && onChange(favs.filter((x) => x.id !== f.id))}>Supprimer</button>
            </div>
          </div>
        );
      })}
      <ImportExport onDone={setMsg} />
      {msg && <p className="muted">{msg}</p>}
    </div>
  );
}

function ImportExport({ onDone }: { onDone: (m: string) => void }) {
  return (
    <div className="actions io">
      <button onClick={async () => download(`ceperadar-sauvegarde-${new Date().toISOString().slice(0, 10)}.json`, await exportAll())}>Exporter favoris et journal (JSON)</button>
      <label className="btn ghost">
        Importer une sauvegarde
        <input type="file" accept="application/json" hidden onChange={async (e) => {
          const f = e.target.files?.[0];
          if (!f) return;
          try {
            const r = await importAll(await f.text());
            onDone(`Importé : ${r.favorites} favoris, ${r.journal} sorties. Rechargez la page pour les voir.`);
          } catch (err) {
            onDone(`Import impossible : ${err}`);
          }
        }} />
      </label>
    </div>
  );
}

const SPECIES_CHOICES = ["Cèpe de Bordeaux", "Cèpe des pins", "Cèpe bronzé", "Cèpe d'été", "Cèpe (non déterminé)", "Aucun cèpe trouvé"];

export function Journal({ prefill, onPrefillUsed }: { prefill: { place: string; lat: number; lon: number } | null; onPrefillUsed: () => void }) {
  const [items, setItems] = useState<JournalEntry[]>([]);
  const [draft, setDraft] = useState<JournalEntry | null>(null);
  const [photoUrls, setPhotoUrls] = useState<Record<string, string>>({});
  useEffect(() => { loadJournal().then(setItems); }, []);
  useEffect(() => {
    if (prefill) {
      setDraft(blank(prefill));
      onPrefillUsed();
    }
  }, [prefill]);
  useEffect(() => {
    const urls: Record<string, string> = {};
    for (const it of items) if (it.photo) urls[it.id] = URL.createObjectURL(it.photo);
    setPhotoUrls(urls);
    return () => Object.values(urls).forEach(URL.revokeObjectURL);
  }, [items]);

  const persist = async (next: JournalEntry[]) => { setItems(next); await saveJournal(next); };

  return (
    <div className="journal">
      {!draft && <button className="primary" onClick={() => setDraft(blank(null))}>Noter une sortie</button>}
      {draft && (
        <form className="jform" onSubmit={async (e) => {
          e.preventDefault();
          const next = items.some((x) => x.id === draft.id) ? items.map((x) => (x.id === draft.id ? draft : x)) : [draft, ...items];
          await persist(next.sort((a, b) => b.date.localeCompare(a.date)));
          setDraft(null);
        }}>
          <label>Date <input type="date" required value={draft.date} onChange={(e) => setDraft({ ...draft, date: e.target.value })} /></label>
          <label>Lieu <input value={draft.place} onChange={(e) => setDraft({ ...draft, place: e.target.value })} placeholder="ex. Forêt du Barp, allée des chênes" /></label>
          <label>Espèce
            <select value={draft.species} onChange={(e) => setDraft({ ...draft, species: e.target.value })}>
              {SPECIES_CHOICES.map((s) => <option key={s}>{s}</option>)}
            </select>
          </label>
          <div className="row2">
            <label>Nombre <input type="number" min={0} value={draft.count ?? ""} onChange={(e) => setDraft({ ...draft, count: e.target.value === "" ? null : Number(e.target.value) })} /></label>
            <label>Quantité <input value={draft.qty} onChange={(e) => setDraft({ ...draft, qty: e.target.value })} placeholder="ex. 1,2 kg" /></label>
          </div>
          <label>Conditions observées <input value={draft.conditions} onChange={(e) => setDraft({ ...draft, conditions: e.target.value })} placeholder="sol humide, mousse sèche, autres espèces…" /></label>
          <label>Note <textarea value={draft.note} onChange={(e) => setDraft({ ...draft, note: e.target.value })} /></label>
          <label>Photo (reste sur cet appareil)
            <input type="file" accept="image/*" capture="environment" onChange={async (e) => {
              const f = e.target.files?.[0];
              if (f) setDraft({ ...draft, photo: await shrinkPhoto(f) });
            }} />
          </label>
          {draft.lat != null && <p className="muted small">Position : {draft.lat.toFixed(4)}, {draft.lon?.toFixed(4)}</p>}
          <div className="actions">
            <button className="primary" type="submit">Enregistrer la sortie</button>
            <button type="button" className="ghost" onClick={() => setDraft(null)}>Annuler</button>
          </div>
        </form>
      )}
      {items.length === 0 && !draft && <p className="muted">Votre journal est vide. Chaque sortie notée (y compris les sorties sans cèpe) servira à recalibrer le modèle.</p>}
      <ul className="jlist">
        {items.map((it) => (
          <li key={it.id}>
            <div>
              <b>{new Date(it.date + "T12:00:00").toLocaleDateString("fr-FR", { weekday: "short", day: "numeric", month: "short", year: "numeric" })}</b> · {it.place || "lieu non précisé"}
              <div>{it.species}{it.count != null ? ` · ${it.count}` : ""}{it.qty ? ` · ${it.qty}` : ""}</div>
              {it.conditions && <div className="muted small">{it.conditions}</div>}
              {it.note && <div className="small">{it.note}</div>}
            </div>
            {photoUrls[it.id] && <img src={photoUrls[it.id]} alt="" />}
            <div className="actions">
              <button className="ghost" onClick={() => setDraft(it)}>Modifier</button>
              <button className="ghost" onClick={() => confirm("Supprimer cette sortie ?") && persist(items.filter((x) => x.id !== it.id))}>Supprimer</button>
            </div>
          </li>
        ))}
      </ul>
      {items.length > 0 && (
        <div className="actions io">
          <button onClick={() => download("ceperadar-journal.csv", journalToCSV(items), "text/csv")}>Exporter en CSV</button>
          <button onClick={async () => download("ceperadar-sauvegarde.json", await exportAll())}>Exporter en JSON</button>
        </div>
      )}
    </div>
  );
}

function blank(pre: { place: string; lat: number; lon: number } | null): JournalEntry {
  return {
    id: uid(), date: new Date().toISOString().slice(0, 10), place: pre?.place ?? "", lat: pre?.lat ?? null, lon: pre?.lon ?? null,
    species: SPECIES_CHOICES[0], count: null, qty: "", conditions: "", note: "", photo: null, created: new Date().toISOString(),
  };
}
