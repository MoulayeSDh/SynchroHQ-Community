"use client";

import "leaflet/dist/leaflet.css";
import { useCallback, useEffect, useRef, useState } from "react";
import type { Map as LeafletMap } from "leaflet";
import { useRouter } from "next/navigation";
import { AppLink } from "../../ui/Shell";
import { useUI } from "../../ui/session";

interface Point {
  report_id: string; revision_id: string; revision_number: number; activity_index: number;
  territory_id: string; territory_name: string; form_id: string; form_name: string;
  period_start: string; latitude: number; longitude: number;
}
interface PointsResponse { total: number; truncated: boolean; items: Point[]; available_forms: { id: string; name: string }[] }
const today = () => new Date().toISOString().slice(0, 10);
const monthAgo = () => new Date(Date.now() - 30 * 86400000).toISOString().slice(0, 10);

function MapCanvas({ points, labels, onOpen }: { points: Point[]; labels: { report: string; revision: string; activity: string; view: string }; onOpen: (reportId: string, revisionId: string) => void }) {
  const element = useRef<HTMLDivElement>(null);
  const instance = useRef<LeafletMap | null>(null);
  useEffect(() => {
    let cancelled = false;
    let created: LeafletMap | null = null;
    void import("leaflet").then(L => {
      if (cancelled || !element.current) return;
      const map = L.map(element.current, { scrollWheelZoom: false }).setView([0, 0], 2);
      created = map; instance.current = map;
      L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 18,
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      }).addTo(map);
      const bounds: [number, number][] = [];
      for (const point of points) {
        const coordinates: [number, number] = [point.latitude, point.longitude];
        bounds.push(coordinates);
        const marker = L.circleMarker(coordinates, { radius: 8, color: "#0059d6", fillColor: "#15b994", fillOpacity: .9, weight: 2 }).addTo(map);
        const popup = document.createElement("div");
        const title = document.createElement("strong");
        title.textContent = `${point.territory_name} · ${point.form_name}`;
        const details = document.createElement("p");
        details.textContent = `${labels.report} ${point.report_id.slice(0, 8)} · ${labels.revision} ${point.revision_number} · ${labels.activity} ${point.activity_index + 1}`;
        const link = document.createElement("a");
        link.href = `/reports?report=${encodeURIComponent(point.report_id)}#revision-${encodeURIComponent(point.revision_id)}`;
        link.textContent = labels.view;
        link.addEventListener("click", event => {
          event.preventDefault();
          onOpen(point.report_id, point.revision_id);
        });
        popup.append(title, details, link);
        marker.bindPopup(popup);
      }
      if (bounds.length === 1) map.setView(bounds[0], 12);
      else if (bounds.length > 1) map.fitBounds(bounds, { padding: [35, 35], maxZoom: 12 });
      requestAnimationFrame(() => map.invalidateSize());
    });
    return () => { cancelled = true; created?.remove(); instance.current = null; };
  }, [points, labels.report, labels.revision, labels.activity, labels.view, onOpen]);
  return <div ref={element} className="geospatial-map" aria-label="Map" />;
}

export default function MapPage() {
  const router = useRouter();
  const { t, token, info, online } = useUI();
  const [start, setStart] = useState(monthAgo);
  const [end, setEnd] = useState(today);
  const [territory, setTerritory] = useState("");
  const [form, setForm] = useState("");
  const [data, setData] = useState<PointsResponse | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let live = true;
    const timer = setTimeout(() => {
      setData(null);
      if (!token || !online) return;
      setBusy(true); setError("");
      const query = new URLSearchParams({ start, end });
      if (territory) query.set("territory_id", territory);
      if (form) query.set("form_id", form);
      void fetch(`/api/reports-proxy/geospatial/points?${query}`, {
        headers: { Authorization: `Bearer ${token}` }, cache: "no-store",
      }).then(async response => {
        if (!response.ok) throw new Error(response.status === 422 ? "Période invalide (maximum 365 jours)." : "Opération impossible.");
        const value: PointsResponse = await response.json();
        if (live) setData(value);
      }).catch(cause => { if (live) setError(cause instanceof Error ? cause.message : "Opération impossible."); })
        .finally(() => { if (live) setBusy(false); });
    }, 0);
    return () => { live = false; clearTimeout(timer); };
  }, [token, info?.id, online, start, end, territory, form]);
  const points = data?.items ?? [];
  const openReport = useCallback((reportId: string, revisionId: string) => {
    router.push(`/reports?report=${encodeURIComponent(reportId)}#revision-${encodeURIComponent(revisionId)}`);
  }, [router]);
  const forms = data?.available_forms ?? [];
  return <main><div className="page-heading"><p className="eyebrow">SynchroHQ Community</p>
    <h1>{t("Carte des rapports")}</h1><p>{t("Positions GPS des activités confirmées")}</p></div>
    <section className="panel"><h2>{t("Filtres")}</h2><div className="analytics-filters">
      <label>{t("Du")}<input type="date" value={start} onChange={event => setStart(event.target.value)} /></label>
      <label>{t("Au")}<input type="date" value={end} onChange={event => setEnd(event.target.value)} /></label>
      <label>{t("Territoire")}<select value={territory} onChange={event => setTerritory(event.target.value)}><option value="">{t("Tous")}</option>
        {info?.territories.filter(item => item.actions.includes("reports:read")).map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
      </select></label>
      <label>{t("Formulaire")}<select value={form} onChange={event => setForm(event.target.value)}><option value="">{t("Tous")}</option>
        {forms.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
    </div></section>
    {!online && <p role="status">{t("Données serveur indisponibles hors connexion.")}</p>}
    {busy && <p role="status">{t("Chargement…")}</p>}{error && <p role="alert">{t(error)}</p>}
    {data && <><p className="analytics-source">{t("Points visibles")} : {points.length} / {data.total}</p>
      {data.truncated && <p role="status">{t("Affichage limité à 500 points. Réduisez la période ou choisissez un territoire.")}</p>}
      {points.length === 0 ? <section className="panel"><p>{t("Aucun point GPS dans cette période et ce périmètre.")}</p></section> : <>
        <section className="panel"><h2>{t("Carte des rapports")}</h2><MapCanvas points={points} onOpen={openReport} labels={{ report: t("Rapport"), revision: t("Révision"), activity: t("Activité"), view: t("Voir le rapport") }} /></section>
        <section className="panel"><h2>{t("Points accessibles")}</h2><div className="table-scroll"><table><thead><tr><th>{t("Territoire")}</th><th>{t("Période")}</th><th>{t("Formulaire")}</th><th>{t("Coordonnées GPS")}</th><th>{t("Rapport")}</th></tr></thead><tbody>
          {points.map(point => <tr key={`${point.revision_id}:${point.activity_index}`}><td>{point.territory_name}</td><td>{point.period_start}</td><td>{point.form_name}</td><td>{point.latitude.toFixed(5)}, {point.longitude.toFixed(5)}</td><td><AppLink href={`/reports?report=${point.report_id}#revision-${point.revision_id}`}>{point.report_id.slice(0, 8)} · {t("Révision")} {point.revision_number} · {t("Activité")} {point.activity_index + 1}</AppLink></td></tr>)}
        </tbody></table></div></section>
      </>}
      <p className="analytics-source">{t("Seule la révision courante de chaque rapport apparaît sur la carte.")}</p>
    </>}
  </main>;
}
