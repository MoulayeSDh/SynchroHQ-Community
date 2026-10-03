"use client";

import { useCallback, useEffect, useState } from "react";
import { AppLink } from "../../ui/Shell";
import { useUI } from "../../ui/session";

type Counts = Record<"EXPECTED" | "RECEIVED" | "LATE" | "MISSING", number>;
interface Overview {
  start: string; end: string; as_of: string; timezone: string; total: number; counts: Counts;
  by_period: { period_start: string; counts: Counts }[];
  by_territory: { territory_id: string; territory_name: string; counts: Counts }[];
  available_forms: { id: string; name: string }[];
  available_territories: { id: string; name: string }[];
}
const statuses: (keyof Counts)[] = ["RECEIVED", "LATE", "MISSING", "EXPECTED"];
const labels: Record<keyof Counts, string> = {
  RECEIVED: "Reçus à temps", LATE: "Reçus en retard", MISSING: "Manquants", EXPECTED: "À venir",
};
const day = () => new Date().toISOString().slice(0, 10);
const monthAgo = () => new Date(Date.now() - 30 * 86400000).toISOString().slice(0, 10);
export default function AnalyticsPage() {
  const { t, token, online, info, locale } = useUI();
  const [start, setStart] = useState(monthAgo);
  const [end, setEnd] = useState(day);
  const [territory, setTerritory] = useState("");
  const [form, setForm] = useState("");
  const [overview, setOverview] = useState<Overview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const refresh = useCallback(async () => {
    if (!token || !online) return;
    setBusy(true); setError("");
    try {
      const params = new URLSearchParams({ start, end });
      if (territory) params.set("territory_id", territory);
      if (form) params.set("form_id", form);
      const response = await fetch(`/api/reports-proxy/analytics/overview?${params}`, {
        headers: { Authorization: `Bearer ${token}` }, cache: "no-store",
      });
      if (!response.ok) throw new Error(response.status === 422 ? "Période invalide (maximum 365 jours)." : "Opération impossible.");
      setOverview(await response.json());
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Opération impossible."); }
    finally { setBusy(false); }
  }, [token, online, start, end, territory, form]);
  useEffect(() => { const timer = setTimeout(() => void refresh(), 0); return () => clearTimeout(timer); }, [refresh, info?.id]);
  const total = (counts: Counts) => statuses.reduce((sum, key) => sum + counts[key], 0);
  return <main><div className="page-heading"><p className="eyebrow">SynchroHQ Community</p>
    <h1>{t("Pilotage")}</h1><p>{t("Obligations de reporting et réceptions officielles")}</p></div>
    <section className="panel"><h2>{t("Filtres")}</h2><div className="analytics-filters">
      <label>{t("Du")}<input type="date" value={start} onChange={event => setStart(event.target.value)} /></label>
      <label>{t("Au")}<input type="date" value={end} onChange={event => setEnd(event.target.value)} /></label>
      <label>{t("Territoire")}<select value={territory} onChange={event => setTerritory(event.target.value)}><option value="">{t("Tous")}</option>
        {overview?.available_territories.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
      <label>{t("Formulaire")}<select value={form} onChange={event => setForm(event.target.value)}><option value="">{t("Tous")}</option>
        {overview?.available_forms.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
    </div></section>
    {!online && <p role="status">{t("Données serveur indisponibles hors connexion.")}</p>}
    {busy && <p role="status">{t("Chargement…")}</p>}{error && <p role="alert">{t(error)}</p>}
    {overview && <><p className="analytics-source">{t("Période")} : {overview.start} → {overview.end} · {t("Calculé le")} : {new Date(overview.as_of).toLocaleString(locale)} · {overview.timezone}</p>
      <section className="analytics-kpis" aria-label={t("Indicateurs")}>
        <div className="stat-card"><span>{t("Attendus")}</span><strong>{overview.total}</strong></div>
        {statuses.map(status => <div className={`stat-card analytics-${status.toLowerCase()}`} key={status}><span>{t(labels[status])}</span><strong>{overview.counts[status]}</strong></div>)}
      </section>
      {overview.total === 0 ? <section className="panel"><p>{t("Aucune obligation dans cette période et ce périmètre.")}</p></section> : <>
        <section className="panel"><h2>{t("Évolution par période")}</h2><div className="analytics-chart" role="img" aria-label={t("Répartition des obligations par période")}>{overview.by_period.map(item => <div className="analytics-bar-row" key={item.period_start}>
          <span>{item.period_start}</span><div className="analytics-bar" title={`${item.period_start} : ${total(item.counts)}`}>
            {statuses.map(status => item.counts[status] > 0 && <span key={status} className={`analytics-segment analytics-${status.toLowerCase()}`} style={{ width: `${100 * item.counts[status] / Math.max(1, overview.total)}%` }} />)}
          </div><strong>{total(item.counts)}</strong></div>)}</div>
          <div className="analytics-legend">{statuses.map(status => <span key={status}><i className={`analytics-segment analytics-${status.toLowerCase()}`} />{t(labels[status])}</span>)}</div>
        </section>
        <section className="panel"><h2>{t("Comparaison territoriale")}</h2><div className="table-scroll"><table><thead><tr><th>{t("Territoire")}</th><th>{t("Attendus")}</th>{statuses.map(status => <th key={status}>{t(labels[status])}</th>)}</tr></thead><tbody>
          {overview.by_territory.map(item => <tr key={item.territory_id}><th scope="row">{item.territory_name}</th><td>{total(item.counts)}</td>{statuses.map(status => <td key={status}>{item.counts[status]}</td>)}</tr>)}
        </tbody></table></div></section>
      </>}
      <p className="analytics-source">{t("Chaque obligation est comptée une seule fois. Une révision ne crée pas de nouvelle réception.")} <AppLink href="/inbox">{t("Voir les obligations détaillées")}</AppLink></p>
    </>}
  </main>;
}
