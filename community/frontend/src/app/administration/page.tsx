"use client";
import { useEffect, useState } from "react";
import { useUI } from "../../ui/session";
interface Directory { users: { id: string; name: string }[]; organizations: { id: string; name: string; code: string }[]; territories: { id: string; name: string; type: string }[] }
export default function Administration() {
  const { t, token, online } = useUI(); const [data, setData] = useState<Directory | null>(null); const [error, setError] = useState(false);
  useEffect(() => {
    let live = true;
    if (token && online) void fetch("/api/session-proxy/administration", { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" })
      .then(async r => { if (!r.ok) throw new Error(); const value = await r.json(); if (live) setData(value); }).catch(() => { if (live) setError(true); });
    return () => { live = false; };
  }, [token, online]);
  return <main><div className="page-heading"><h1>{t("Administration")}</h1><p>{t("Annuaire en lecture seule")}. {t("Les données affichées sont limitées à votre périmètre autorisé.")}</p></div>
    {!online && <p role="status">{t("Données serveur indisponibles hors connexion.")}</p>}{error && <p role="alert">{t("Accès non autorisé")}</p>}{online && !data && !error && <p role="status">{t("Chargement…")}</p>}
    {data && <div className="directory-grid">{(["users", "organizations", "territories"] as const).map((key, i) => <section className="panel" key={key}><h2>{t(["Utilisateurs", "Organisations", "Territoires"][i])} · {data[key].length}</h2>
      {data[key].map(item => <article className="directory-item" key={item.id}><strong>{item.name}</strong>{"type" in item && <span>{t(item.type)}</span>}{"code" in item && <span>{item.code}</span>}</article>)}{!data[key].length && <p>{t("Aucune donnée disponible.")}</p>}</section>)}</div>}
  </main>;
}
