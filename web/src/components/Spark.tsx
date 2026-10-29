import { levelOf } from "../model";

/** Petit histogramme de scores (passé plein, futur hachuré). */
export function ScoreBars({ values, labels, todayIndex, selected }: { values: (number | null)[]; labels: string[]; todayIndex: number; selected?: number }) {
  const w = 22, gap = 4, h = 64;
  return (
    <svg className="bars" viewBox={`0 0 ${values.length * (w + gap)} ${h + 16}`} role="img" aria-label="Évolution du score">
      <defs>
        <pattern id="fc" width="4" height="4" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <rect width="2" height="4" fill="rgba(255,255,255,.45)" />
        </pattern>
      </defs>
      {values.map((v, k) => {
        const x = k * (w + gap);
        const bh = v == null ? 2 : Math.max(2, (v / 100) * h);
        const col = v == null ? "#ccc" : levelOf(v).color;
        return (
          <g key={k}>
            <rect x={x} y={h - bh} width={w} height={bh} rx={2} fill={col} stroke={k === selected ? "#14231a" : "none"} strokeWidth={2} />
            {k > todayIndex && <rect x={x} y={h - bh} width={w} height={bh} rx={2} fill="url(#fc)" />}
            <text x={x + w / 2} y={h - bh - 3} textAnchor="middle" className="bars-v">{v == null ? "–" : v}</text>
            <text x={x + w / 2} y={h + 12} textAnchor="middle" className="bars-l">{labels[k]}</text>
          </g>
        );
      })}
    </svg>
  );
}

/** Pluie journalière (barres) + températures min/max (lignes). */
export function WeatherChart({ dates, precip, tmin, tmax, todayIdx }: { dates: string[]; precip: (number | null)[]; tmin: (number | null)[]; tmax: (number | null)[]; todayIdx: number }) {
  const W = 320, H = 110, pad = 18;
  const n = dates.length;
  const bw = (W - pad) / n;
  const pmax = Math.max(10, ...precip.map((x) => x ?? 0));
  const temps = [...tmin, ...tmax].filter((x): x is number => x != null);
  const tlo = Math.min(0, ...temps), thi = Math.max(20, ...temps);
  const ty = (t: number) => 8 + (H - 30) * (1 - (t - tlo) / (thi - tlo));
  const line = (arr: (number | null)[]) => arr.map((t, k) => (t == null ? "" : `${k && arr[k - 1] != null ? "L" : "M"}${pad + k * bw + bw / 2},${ty(t)}`)).join("");
  return (
    <svg className="wchart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Pluie et températures">
      <rect x={pad + (todayIdx + 0.5) * bw} y={0} width={W - pad - (todayIdx + 0.5) * bw} height={H - 18} fill="rgba(36,56,44,.06)" />
      {precip.map((p, k) => p ? <rect key={k} x={pad + k * bw + 1} y={H - 18 - (p / pmax) * (H - 30)} width={bw - 2} height={(p / pmax) * (H - 30)} fill="#3d7ea6" /> : null)}
      <path d={line(tmax)} fill="none" stroke="#c0552b" strokeWidth={1.5} />
      <path d={line(tmin)} fill="none" stroke="#5a7d9a" strokeWidth={1.5} />
      <text x={2} y={12} className="bars-l">{Math.round(thi)}°</text>
      <text x={2} y={H - 22} className="bars-l">{Math.round(tlo)}°</text>
      <text x={pad} y={H - 4} className="bars-l">{dates[0]?.slice(5)}</text>
      <text x={W - 2} y={H - 4} textAnchor="end" className="bars-l">{dates[n - 1]?.slice(5)}</text>
      <text x={W - 2} y={12} textAnchor="end" className="bars-l">max pluie {Math.round(pmax)} mm</text>
    </svg>
  );
}
