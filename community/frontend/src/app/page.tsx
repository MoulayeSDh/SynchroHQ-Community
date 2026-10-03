"use client";
import { useEffect, useState } from "react";
import { useUI } from "../ui/session";
import { AppLink } from "../ui/Shell";
export default function Home() {
  const { t, info, can, token, online, pending, corrections, blocked, lastSync } = useUI();
  const [count, setCount] = useState<number | null>(null); const [requests, setRequests] = useState<number | null>(null); const [error, setError] = useState(false);
  useEffect(() => {
    let live = true;
    if (!token || !online || !can("reports:read")) return;
    void (async () => {
      let total = 0; let correctionCount = 0;
      for (let offset = 0; ; offset += 100) {
        const r = await fetch(`/api/reports-proxy/workflow/inbox?${can("reports:create") ? "own=true&" : ""}offset=${offset}&limit=100`, { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" });
        if (!r.ok) throw new Error();
        const page: { corrections: { state: string }[] }[] = await r.json();
        total += page.length; correctionCount += page.reduce((n, report) => n + report.corrections.filter(c => c.state === "OPEN").length, 0);
        if (page.length < 100) break;
      }
      if (live) { setCount(total); setRequests(correctionCount); }
    })().catch(() => { if (live) setError(true); });
    return () => { live = false; };
    // can is derived from info, which changes when the account changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, online, info]);
  return <main><div className="page-heading"><p className="eyebrow">SynchroHQ Community</p><h1>{t("Votre espace de travail")}</h1><p>{t("Des informations fiables du terrain à la décision.")}</p></div>
    <section className="welcome-banner"><div><span>{t("Connecté")} · {info?.display_name}</span><h2>{info?.assignments[0]?.organization}</h2><p>{t("Collecter. Synchroniser. Agir. Ensemble.")}</p></div>{can("drafts:sync") && <AppLink href="/collect" className="button primary">+ {t("Nouveau rapport")}</AppLink>}</section>
    <div className="stat-grid"><AppLink href="/reports" className="stat-card"><span>{t(can("reports:create") ? "Mes rapports" : "Rapports accessibles")}</span><strong>{online ? count ?? "—" : "—"}</strong></AppLink>
      <AppLink href="/inbox" className="stat-card"><span>{t("Corrections demandées")}</span><strong>{online ? requests ?? "—" : corrections}</strong></AppLink>
      <AppLink href={can("drafts:sync") ? "/collect" : "/inbox"} className="stat-card"><span>{t("À synchroniser")}</span><strong>{pending}</strong></AppLink>
      <div className="stat-card"><span>{t("Bloqués")}</span><strong>{blocked}</strong></div></div>
    {error && <p role="alert">{t("Opération impossible.")}</p>}{!online && <p role="status">{t("Données serveur indisponibles hors connexion.")}</p>}
    <section className="panel"><h2>{t("Synchronisation")}</h2><p>{t(online ? "En ligne" : "Hors connexion")} · {t("Données conservées sur cet appareil")}</p>
      {lastSync && <p>{t("Dernière synchronisation")} : {new Date(lastSync).toLocaleString()}</p>}
      <div className="toolbar">{can("drafts:sync") && <AppLink href="/collect" className="button">{t("Brouillons")}</AppLink>}{can("reports:read") && <AppLink href="/inbox" className="button">{t("Inbox")}</AppLink>}{can("forms:read") && <AppLink href="/forms" className="button">{t("Formulaires")}</AppLink>}{can("reports:read") && <AppLink href="/analytics" className="button">{t("Pilotage")}</AppLink>}</div></section>
  </main>;
}
