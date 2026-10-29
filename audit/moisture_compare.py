import json, datetime as dt, numpy as np, os
from pipeline import engine
from pipeline.common import load_params
from pipeline.update import load_series
D=os.environ["CEPERADAR_DATA"]; P=load_params()
cache=json.load(open(f"{D}/cache/weather.json")); st=json.load(open(f"{D}/static/cells.json"))
dates=[dt.date.fromisoformat(x) for x in cache["dates"]]; n=len(cache["lat"])
S=load_series(cache,n,P["weather"]); t=dates.index(dt.date(2026,10,30))
lat=np.array(cache["lat"]); lon=np.array(cache["lon"])
B=S["bucket"][:,t-1]; sm=S["sm"][:,t-1]; r30=S["precip"][:,t-30:t].sum(1); r60=S["precip"][:,t-60:t].sum(1)
print("valid days precip per point (first 15 days):", np.isfinite(S["precip"][0,:15]).astype(int).tolist())
print("first finite bucket idx:", np.argmax(np.isfinite(S["bucket"][0])), dates[np.argmax(np.isfinite(S["bucket"][0]))])
z=B<6
print("points bucket<6mm:", z.sum(), " leur SM modèle p10/50/90:", np.percentile(sm[z],[10,50,90]).round(3), " pluie30:", np.percentile(r30[z],[10,50,90]).round(0))
print("autres points: SM", np.percentile(sm[~z],[10,50,90]).round(3), " pluie30:", np.percentile(r30[~z],[10,50,90]).round(0))
print("corr(bucket, sm)=%.2f corr(bucket,r30)=%.2f corr(sm,r30)=%.2f"%(np.corrcoef(B,sm)[0,1],np.corrcoef(B,r30)[0,1],np.corrcoef(sm,r30)[0,1]))
# géographie des points secs
print("lon des points bucket<6: p10/50/90", np.percentile(lon[z],[10,50,90]).round(2), "lat", np.percentile(lat[z],[10,50,90]).round(2))
print("lon tous points", np.percentile(lon,[10,50,90]).round(2))
# sm minimal en été par point vs octobre
smin=np.nanmin(S["sm"][:, :t],axis=1); smax=np.nanmax(S["sm"][:, :t],axis=1)
print("SM min été p10/50/90", np.percentile(smin,[10,50,90]).round(3), " max p10/50/90", np.percentile(smax,[10,50,90]).round(3))
# Points très bas en SM: probablement texture sableuse dans le modèle
low=smax<0.15; print("points dont SM max < 0.15 (texture sableuse modèle?):", low.sum(), "lon médiane", np.median(lon[low]) if low.any() else None)
# pluie par point: distribution de rain60
print("pluie 60 j p10/50/90", np.percentile(r60,[10,50,90]).round(0))
# discontinuités spatiales de pluie 30 j
from scipy.spatial import cKDTree
xy=np.c_[lat*111, lon*111*np.cos(np.radians(44.8))]; tr=cKDTree(xy)
d,idx=tr.query(xy,k=7)
neigh=np.median(r30[idx[:,1:]],axis=1); mad=np.median(np.abs(r30[idx[:,1:]]-neigh[:,None]),axis=1)+3
outl=np.abs(r30-neigh)>4*mad
print("points à pluie 30 j atypique vs voisins:", outl.sum(), list(zip(lat[outl].round(2),lon[outl].round(2),r30[outl].round(0),neigh[outl].round(0)))[:10])
