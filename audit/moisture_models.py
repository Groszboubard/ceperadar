import json, datetime as dt, numpy as np, os
from pipeline.common import load_params
from pipeline.update import load_series
D=os.environ["CEPERADAR_DATA"]; P=load_params()
cache=json.load(open(f"{D}/cache/weather.json")); st=json.load(open(f"{D}/static/cells.json"))
dates=[dt.date.fromisoformat(x) for x in cache["dates"]]; n=len(cache["lat"])
S=load_series(cache,n,P["weather"])
c=st["cells"]; wp=np.array(c["wp"])
def pm(a):
    a=np.array(a,float); a[a<0]=np.nan
    out=np.full(n,np.nan)
    for k in range(n):
        v=a[wp==k]; v=v[np.isfinite(v)]
        if len(v): out[k]=np.median(v)
    return out
sand=pm(c["sand"])/100; clay=pm(c["clay"])/100; soc=pm(c["soc"])
OM=np.clip(soc*1.724/10,0.5,8)
def saxton(Sa,Cl,OM):
    t15=-0.024*Sa+0.487*Cl+0.006*OM+0.005*Sa*OM-0.013*Cl*OM+0.068*Sa*Cl+0.031
    wp_=t15+(0.14*t15-0.02)
    t33=-0.251*Sa+0.195*Cl+0.011*OM+0.006*Sa*OM-0.027*Cl*OM+0.452*Sa*Cl+0.299
    fc=t33+(1.283*t33**2-0.374*t33-0.015)
    return fc,wp_
fc,wpt=saxton(sand,clay,OM)
awc=fc-wpt; RU=np.clip(awc*300,15,90)
print("sable p10/50/90",np.nanpercentile(sand,[10,50,90]).round(2),"OM",np.nanpercentile(OM,[10,50,90]).round(1))
print("CC",np.nanpercentile(fc,[10,50,90]).round(3),"PF",np.nanpercentile(wpt,[10,50,90]).round(3),"RU 0-30cm mm",np.nanpercentile(RU,[10,50,90]).round(0))
P_=S["precip"]; E=S["et0"]; T=len(dates)
first=np.argmax(np.isfinite(P_[0]))
def biljou(RU,kc=0.7,start=0.5,interc=0.15):
    w=RU*start; out=np.full((n,T),np.nan)
    for t in range(first,T):
        p=np.nan_to_num(P_[:,t]); e=np.nan_to_num(E[:,t])
        pin=np.maximum(0,p-np.minimum(p,1.0+interc*p))  # interception canopée ~1 mm + 15 %
        rew=w/RU
        loss=kc*e*np.minimum(1,rew/0.4)
        w=np.clip(w+pin-loss,0,RU); out[:,t]=w/RU
    return out
def v1():
    b=S["bucket"]/50; return b
A=v1(); A2=biljou(np.where(np.isfinite(RU),RU,30))
sm=S["sm"]; lo,hi=np.nanpercentile(sm,5),np.nanpercentile(sm,95)
B=np.clip((sm-lo)/(hi-lo),0,1)
print("enveloppe SM modèle p5/p95:",round(lo,3),round(hi,3))
C=np.where(np.isfinite(B),0.6*A2+0.4*B,A2)
Mf=lambda r,lo_,hi_: (lambda x:x*x*(3-2*x))(np.clip((r-lo_)/(hi_-lo_),0,1))
for name,day in [("sec (fin août)",dt.date(2026,8,31)),("transition (mi-sept)",dt.date(2026,9,15)),("humide (début oct)",dt.date(2026,10,8)),("cible 30/10",dt.date(2026,10,30))]:
    t=dates.index(day)-1
    def s(x): return f"p10={np.nanpercentile(x,10):.2f} p50={np.nanmedian(x):.2f} p90={np.nanpercentile(x,90):.2f} M0={np.mean(x<0.12):.0%}"
    print(f"\n{name} {day}  pluie30 méd={np.nanmedian(P_[:,t-29:t+1].sum(1)):.0f}mm")
    print("  A  V1 réservoir 50mm:", s(A[:,t]))
    print("  A' BILJOU-like RU sol:", s(A2[:,t]))
    print("  B  humidité modèle   :", s(B[:,t]))
    print("  C  hybride           :", s(C[:,t]), " désaccord|A'-B|>0.35:", f"{np.nanmean(np.abs(A2[:,t]-B[:,t])>0.35):.0%}")
