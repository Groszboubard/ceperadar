"""Audit V1 sur données réelles (branche data). Usage: CEPERADAR_DATA=... python -m audit.audit_v1"""
import json, datetime as dt, numpy as np, os, collections
from pipeline import engine
from pipeline.common import load_params
from pipeline.update import load_series
D=os.environ["CEPERADAR_DATA"]
P=load_params()
st=json.load(open(f"{D}/static/cells.json")); lt=json.load(open(f"{D}/forecast/latest.json")); cache=json.load(open(f"{D}/cache/weather.json"))
dates=[dt.date.fromisoformat(x) for x in cache["dates"]]
n=len(cache["lat"]); S=load_series(cache,n,P["weather"])
tgt=dt.date(2026,10,30); t=dates.index(tgt); run=dates.index(dt.date(2026,10,29))
wp=np.array(st["cells"]["wp"])
print("=== Météo réelle (points) au", tgt)
ind=engine.indicators_for_date(S,t)
for k in ["rain7","rain14","rain30","dry_days","tmean7","tmean21","tsoil7","bucket_pct","sm_model","et0_7","balance30"]:
    v=ind[k]; print(f"{k:10s} p10={np.nanpercentile(v,10):6.2f} p50={np.nanmedian(v):6.2f} p90={np.nanpercentile(v,90):6.2f}")
print("pluie 60 j avant (médiane points) par semaine:", [round(float(np.median(S['precip'][:, t-7*(k+1):t-7*k].sum(1))),1) for k in range(8,-1,-1)])
print("SM model médiane par semaine:", [round(float(np.nanmedian(S['sm'][:, t-7*(k+1):t-7*k])),3) for k in range(12,-1,-1)])
print("Bucket médian (mm) par semaine:", [round(float(np.nanmedian(S['bucket'][:, t-7*k-1])),1) for k in range(12,-1,-1)])
for s in engine.SPECIES_ORDER:
    c=engine.components_for_date(S,t,tgt.timetuple().tm_yday,P["species"][s],P["weather"])
    H=np.array(st["cells"]["H"][s],float); W=c["W"][wp]*100
    sc=np.rint(H*W/100)
    print(f"\n=== {s}: score cellules; zéros={np.mean(sc==0):.1%} <20={np.mean(sc<20):.1%} 20-40={np.mean((sc>=20)&(sc<40)):.1%} ≥60={np.mean(sc>=60):.1%}")
    print(" hist/10:", np.histogram(sc,bins=range(0,111,10))[0].tolist())
    for k in ["R","M","T"]: v=c[k]; print(f" {k} points: p10={np.nanpercentile(v,10):.2f} p50={np.nanmedian(v):.2f} p90={np.nanpercentile(v,90):.2f} zéros={np.mean(v<0.01):.1%}")
    print(f" S={c['S'][0]:.2f}  W points: zéros={np.mean(c['W']<0.01):.1%} p50={np.median(c['W']):.2f}; H cellules p50={np.median(H):.0f}")
    # cause dominante des scores faibles
    Hc=H/100; Rc=c["R"][wp]; Mc=c["M"][wp]; Tc=c["T"][wp]
    low=sc<20
    lim=np.argmin(np.stack([Hc,Rc**0.45,Mc**0.3,Tc**0.25]),axis=0)
    cnt=collections.Counter(lim[low]); print(" facteur limitant (score<20):", {["habitat","pluie","humidité","température"][k]:f"{v/low.sum():.0%}" for k,v in cnt.items()})
    print(" zéros dus à M=0:", f"{np.mean((Mc<0.01)[sc==0]) if (sc==0).any() else 0:.0%}")
# habitat par classe dominante
c1=np.array(st["cells"]["c1"]); He=np.array(st["cells"]["H"]["edulis"])
labels={c["id"]:c["key"] for c in P["forest_classes"]}
print("\nHabitat edulis médian par classe dominante (n):", {labels[k]:(int(np.median(He[c1==k])),int((c1==k).sum())) for k in np.unique(c1)})
fr=np.array(st["cells"]["forest"]); print("forest% p10/50/90", np.percentile(fr,[10,50,90]))
