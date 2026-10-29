import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { StaticData } from "../types";

export type Basemap = "plan" | "ortho";

interface Props {
  st: StaticData;
  colors: (string | null)[]; // couleur par cellule (null = masquée)
  selected: number | null;
  highlight: number[];
  overlayAccess: boolean;
  gbif: { lat: number; lon: number; sp: string; date: string }[] | null;
  favorites: { i: number; j: number; name: string }[];
  basemap: Basemap;
  flyTo: { lat: number; lon: number; zoom?: number; t: number } | null;
  onSelect: (cell: number | null) => void;
}

const WMTS = (layer: string, fmt: string, style = "normal") =>
  `https://data.geopf.fr/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=${layer}&STYLE=${style}&FORMAT=${fmt}&TILEMATRIXSET=PM&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}`;

function cellPolygon(st: StaticData, c: number) {
  const lat = st.grid.lat0 + st.cells.i[c] * st.grid.dlat;
  const lon = st.grid.lon0 + st.cells.j[c] * st.grid.dlon;
  const a = st.grid.dlat / 2, b = st.grid.dlon / 2;
  return [[[lon - b, lat - a], [lon + b, lat - a], [lon + b, lat + a], [lon - b, lat + a], [lon - b, lat - a]]];
}

export default function MapView(p: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const ready = useRef(false);
  const onSelect = useRef(p.onSelect);
  onSelect.current = p.onSelect;

  // initialisation
  useEffect(() => {
    if (!ref.current) return;
    const m = new maplibregl.Map({
      container: ref.current,
      center: [p.st.grid.lon0, p.st.grid.lat0],
      zoom: 7.6,
      minZoom: 6.5,
      maxZoom: 17,
      attributionControl: false,
      style: {
        version: 8,
        sources: {
          plan: { type: "raster", tiles: [WMTS("GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2", "image/png")], tileSize: 256, maxzoom: 18,
            attribution: '<a href="https://geoservices.ign.fr" target="_blank">© IGN – Géoplateforme</a>' },
          ortho: { type: "raster", tiles: [WMTS("ORTHOIMAGERY.ORTHOPHOTOS", "image/jpeg")], tileSize: 256, maxzoom: 19,
            attribution: '<a href="https://geoservices.ign.fr" target="_blank">© IGN – Orthophotos</a>' },
        },
        layers: [
          { id: "plan", type: "raster", source: "plan", paint: { "raster-saturation": -0.35, "raster-opacity": 0.95 } },
          { id: "ortho", type: "raster", source: "ortho", layout: { visibility: "none" } },
        ],
      },
    });
    m.addControl(new maplibregl.AttributionControl({ compact: true, customAttribution: "BD Forêt® V2 IGN · Open-Meteo (CC BY 4.0) · SoilGrids ISRIC · Copernicus DEM · GBIF" }));
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    m.addControl(new maplibregl.GeolocateControl({ positionOptions: { enableHighAccuracy: true }, trackUserLocation: false }), "top-right");
    m.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-left");

    m.on("load", () => {
      const n = p.st.cells.i.length;
      const feats = new Array(n);
      for (let c = 0; c < n; c++) feats[c] = { type: "Feature", id: c, properties: { c, col: "#0000", pub: p.st.cells.pub[c], prot: p.st.cells.prot[c] }, geometry: { type: "Polygon", coordinates: cellPolygon(p.st, c) } };
      m.addSource("cells", { type: "geojson", data: { type: "FeatureCollection", features: feats } as any });
      m.addLayer({ id: "cells", type: "fill", source: "cells", paint: { "fill-color": ["get", "col"], "fill-opacity": ["interpolate", ["linear"], ["zoom"], 7, 0.78, 12, 0.55, 15, 0.35] }, filter: ["!=", ["get", "col"], "#0000"] });
      m.addLayer({ id: "pub", type: "line", source: "cells", layout: { visibility: "none" }, filter: [">=", ["get", "pub"], 30], paint: { "line-color": "#2b6cb0", "line-width": 1.2 } });
      m.addLayer({ id: "prot", type: "line", source: "cells", layout: { visibility: "none" }, filter: [">", ["get", "prot"], 0], paint: { "line-color": "#7b3fa0", "line-width": 1.6, "line-dasharray": [2, 1] } });
      m.addSource("hl", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      m.addLayer({ id: "hl", type: "line", source: "hl", paint: { "line-color": "#14231a", "line-width": ["case", ["==", ["get", "k"], "sel"], 3, 1.4] } });
      m.addSource("gbif", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      m.addLayer({ id: "gbif", type: "circle", source: "gbif", paint: { "circle-radius": 3.5, "circle-color": "#5b3a1a", "circle-stroke-color": "#fff", "circle-stroke-width": 1 } });
      m.addSource("favs", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      m.addLayer({ id: "favs", type: "circle", source: "favs", paint: { "circle-radius": 6, "circle-color": "#e0b400", "circle-stroke-color": "#24382c", "circle-stroke-width": 2 } });
      m.addSource("circle", { type: "geojson", data: radiusCircle(p.st) as any });
      m.addLayer({ id: "circle", type: "line", source: "circle", paint: { "line-color": "#24382c", "line-width": 1, "line-dasharray": [4, 3], "line-opacity": 0.6 } });
      m.on("click", (e) => {
        const f = m.queryRenderedFeatures(e.point, { layers: ["cells"] });
        onSelect.current(f.length ? (f[0].properties as any).c : null);
      });
      m.on("mouseenter", "cells", () => (m.getCanvas().style.cursor = "pointer"));
      m.on("mouseleave", "cells", () => (m.getCanvas().style.cursor = ""));
      ready.current = true;
      m.fire("ceperadar:ready");
    });
    map.current = m;
    return () => m.remove();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p.st]);

  const whenReady = (fn: (m: maplibregl.Map) => void) => {
    const m = map.current;
    if (!m) return;
    if (ready.current) fn(m);
    else m.once("ceperadar:ready" as any, () => fn(m));
  };

  // couleurs
  useEffect(() => {
    whenReady((m) => {
      const n = p.st.cells.i.length;
      const feats = new Array(n);
      for (let c = 0; c < n; c++) feats[c] = { type: "Feature", id: c, properties: { c, col: p.colors[c] ?? "#0000", pub: p.st.cells.pub[c], prot: p.st.cells.prot[c] }, geometry: { type: "Polygon", coordinates: cellPolygon(p.st, c) } };
      (m.getSource("cells") as maplibregl.GeoJSONSource).setData({ type: "FeatureCollection", features: feats } as any);
    });
  }, [p.colors, p.st]);

  useEffect(() => {
    whenReady((m) => {
      const feats: any[] = p.highlight.map((c) => ({ type: "Feature", properties: { k: "sec" }, geometry: { type: "Polygon", coordinates: cellPolygon(p.st, c) } }));
      if (p.selected != null) feats.push({ type: "Feature", properties: { k: "sel" }, geometry: { type: "Polygon", coordinates: cellPolygon(p.st, p.selected) } });
      (m.getSource("hl") as maplibregl.GeoJSONSource).setData({ type: "FeatureCollection", features: feats });
    });
  }, [p.selected, p.highlight, p.st]);

  useEffect(() => {
    whenReady((m) => {
      m.setLayoutProperty("pub", "visibility", p.overlayAccess ? "visible" : "none");
      m.setLayoutProperty("prot", "visibility", p.overlayAccess ? "visible" : "none");
    });
  }, [p.overlayAccess]);

  useEffect(() => {
    whenReady((m) => {
      m.setLayoutProperty("ortho", "visibility", p.basemap === "ortho" ? "visible" : "none");
      m.setLayoutProperty("plan", "visibility", p.basemap === "plan" ? "visible" : "none");
    });
  }, [p.basemap]);

  useEffect(() => {
    whenReady((m) => {
      const feats = (p.gbif ?? []).map((o) => ({ type: "Feature", properties: { sp: o.sp, date: o.date }, geometry: { type: "Point", coordinates: [o.lon, o.lat] } }));
      (m.getSource("gbif") as maplibregl.GeoJSONSource).setData({ type: "FeatureCollection", features: feats } as any);
    });
  }, [p.gbif]);

  useEffect(() => {
    whenReady((m) => {
      const feats = p.favorites.map((f) => ({ type: "Feature", properties: { name: f.name }, geometry: { type: "Point", coordinates: [p.st.grid.lon0 + f.j * p.st.grid.dlon, p.st.grid.lat0 + f.i * p.st.grid.dlat] } }));
      (m.getSource("favs") as maplibregl.GeoJSONSource).setData({ type: "FeatureCollection", features: feats } as any);
    });
  }, [p.favorites, p.st]);

  useEffect(() => {
    if (p.flyTo && map.current) map.current.flyTo({ center: [p.flyTo.lon, p.flyTo.lat], zoom: p.flyTo.zoom ?? 12, speed: 1.6 });
  }, [p.flyTo]);

  return <div ref={ref} className="map" role="application" aria-label="Carte des indices de favorabilité" />;
}

function radiusCircle(st: StaticData) {
  const pts: number[][] = [];
  const R = 6371.0088;
  const lat0 = (st.grid.lat0 * Math.PI) / 180, lon0 = (st.grid.lon0 * Math.PI) / 180;
  const d = st.grid.radius_km / R;
  for (let k = 0; k <= 180; k++) {
    const br = (2 * Math.PI * k) / 180;
    const lat = Math.asin(Math.sin(lat0) * Math.cos(d) + Math.cos(lat0) * Math.sin(d) * Math.cos(br));
    const lon = lon0 + Math.atan2(Math.sin(br) * Math.sin(d) * Math.cos(lat0), Math.cos(d) - Math.sin(lat0) * Math.sin(lat));
    pts.push([(lon * 180) / Math.PI, (lat * 180) / Math.PI]);
  }
  return { type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: pts } };
}
