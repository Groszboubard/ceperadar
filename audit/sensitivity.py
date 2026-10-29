"""Sensibilité du facteur humidité et du score W (cèpe de Bordeaux, 30/10/2026) — données réelles."""
import json, datetime as dt, numpy as np, os, copy
from pipeline import engine
from pipeline.common import load_params
from pipeline.update import load_series
D=os.environ["CEPERADAR_DATA"]; P=load_params(); P1=json.load(open("model/params_v1.json"))
cache=json.load(open(f"{D}/cache/weather.json")); st=json.load(open(f"{D}/static/cells.json"))
dates=[dt.date.fromisoformat(x) for x in cache["dates"]]; n=len(cache["lat"])
S=load_series(cache,n,P1["weather"]); t=dates.index(dt.date(2026,10,30)); doy=303
wp=np.array(st["cells"]["wp"]); H1=np.array(st["cells"]["H"]["edulis"],float)
def run(series,params):
    c=engine.components_for_date(series,t,doy,params["species"]["edulis"],params["weather"]); return c
def scores(W): return np.rint(H1*W[wp]*100/100)
c1=run(S,P1); s1=scores(c1["W"])
print(f"V1                         : M=0 {np.mean(c1['M']<0.01):5.0%}  W p50 {np.median(c1['W']):.2f}  scores=0 {np.mean(s1==0):5.0%}  <20 {np.mean(s1<20):5.0%}  ≥60 {np.mean(s1>=60):5.0%}")
sm=S["sm"]; env=(np.nanpercentile(sm,5),np.nanpercentile(sm,95))
B=engine.rew_from_model([sm],[env])
first=np.argmax(np.isfinite(S["precip"][0])); init=B[:,first]
mp0=P["moisture"]
for label,ru,kc,mlo,mhi,wm in [("A' RU 35, kc .65",35,.65,.05,.5,0),("A' RU 22 (sable)",22,.65,.05,.5,0),("A' RU 55 (limon)",55,.65,.05,.5,0),
                           ("A' RU 35, kc .8",35,.8,.05,.5,0),("A' RU 35, kc .5",35,.5,.05,.5,0),
                           ("C RU 35 (0.6A'+0.4B)",35,.65,.05,.5,.4),("C RU 22",22,.65,.05,.5,.4),("C seuils .10-.60",35,.65,.10,.6,.4),("B seul",35,.65,.05,.5,1.0)]:
    mp=dict(mp0,kc_forest=kc,m_low=mlo,m_high=mhi,weight_model=wm,weight_bucket=1-wm)
    A=engine.rew_bucket(S["precip"],S["et0"],np.full(n,ru),mp,init=init)
    C,dis=engine.moisture_hybrid(A,B,mp) if wm<1 else (B,np.zeros_like(B))
    S2=dict(S); S2["rew"]=C; S2["moisture_params"]=mp
    c=run(S2,P); sc=scores(c["W"])
    print(f"{label:27s}: M=0 {np.mean(c['M']<0.01):5.0%}  W p50 {np.median(c['W']):.2f}  scores=0 {np.mean(sc==0):5.0%}  <20 {np.mean(sc<20):5.0%}  ≥60 {np.mean(sc>=60):5.0%}  désaccord>0.35 {np.nanmean(dis[:,t-1]>0.35):4.0%}")
# Affinités ±20 %
print("\nSensibilité habitat (V1 météo): affinités ×0.8 / ×1.2 → part des cellules ≥60:")
from pipeline import habitat
