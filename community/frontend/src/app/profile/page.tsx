"use client";
import { useState, type FormEvent } from "react";
import { useUI } from "../../ui/session";

export default function ProfilePage() {
  const { t, info, profile, lastSync, token, online, login } = useUI();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(""); setMessage("");
    if (newPassword !== confirmation) { setError("Les nouveaux mots de passe ne correspondent pas."); return; }
    if (newPassword === currentPassword) { setError("Choisissez un nouveau mot de passe différent."); return; }
    if (!token || !online) { setError("Connectez-vous pour modifier le mot de passe."); return; }
    setBusy(true);
    try {
      const response = await fetch("/api/session-proxy/change-password", {
        method: "POST", cache: "no-store",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
      });
      if (!response.ok) {
        const detail = (await response.json().catch(() => ({}))).detail;
        if (detail === "INVALID_CREDENTIALS") throw new Error("Mot de passe actuel incorrect.");
        if (detail === "PASSWORD_POLICY") throw new Error("Le nouveau mot de passe doit contenir au moins 14 caractères et au plus 1 024 octets.");
        if (detail === "PASSWORD_UNCHANGED") throw new Error("Choisissez un nouveau mot de passe différent.");
        if (response.status === 401) throw new Error("Session expirée. Reconnectez-vous.");
        throw new Error("Modification impossible. Réessayez.");
      }
      const result: { token: string } = await response.json();
      await login(result.token);
      setCurrentPassword(""); setNewPassword(""); setConfirmation("");
      setMessage("Mot de passe modifié. Les autres sessions ont été fermées.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Modification impossible. Réessayez.");
    } finally { setBusy(false); }
  }

  return <main><div className="page-heading"><h1>{t("Profil")}</h1><p>{info?.display_name}</p></div>
    <section className="panel"><h2>{t("Affectations actives")}</h2>{info?.assignments.map(a => <article key={a.id} className="assignment"><h3>{a.organization}</h3>
      <p>{t("Rôle")} : {t(a.role)} · {t("Niveau d’habilitation")} : {a.clearance}</p>
      {a.scopes.map(s => <p key={s.territory_id}>{info.territories.find(v => v.id === s.territory_id)?.name} · {t(s.coverage === "DESCENDANTS" ? "Territoire et descendants" : "Territoire uniquement")}</p>)}</article>)}</section>
    <section className="panel"><h2>{t("Synchronisation")}</h2><p>{t("Données conservées sur cet appareil")}</p>{!token && <p>{t("Données en attente : reconnectez-vous pour les envoyer.")}</p>}
      {profile && <p>{t("Fin de session locale")} : {new Date(profile.editable_until).toLocaleString()}</p>}{lastSync && <p>{t("Dernière synchronisation")} : {new Date(lastSync).toLocaleString()}</p>}</section>
    <section className="panel"><h2>{t("Changer le mot de passe")}</h2>
      <p>{t("La modification nécessite une connexion. Les autres sessions seront fermées.")}</p>
      <form onSubmit={submit} style={{ maxWidth: "28rem" }}>
        <label htmlFor="current-password">{t("Mot de passe actuel")}</label>
        <input id="current-password" type="password" autoComplete="current-password" required value={currentPassword} onChange={event => setCurrentPassword(event.target.value)} />
        <label htmlFor="new-password">{t("Nouveau mot de passe")}</label>
        <input id="new-password" type="password" autoComplete="new-password" minLength={14} required value={newPassword} onChange={event => setNewPassword(event.target.value)} />
        <label htmlFor="confirm-password">{t("Confirmer le nouveau mot de passe")}</label>
        <input id="confirm-password" type="password" autoComplete="new-password" minLength={14} required value={confirmation} onChange={event => setConfirmation(event.target.value)} />
        <button className="primary" type="submit" disabled={busy || !online || !token}>{t(busy ? "Modification en cours…" : "Modifier le mot de passe")}</button>
      </form>
      {error && <p role="alert">{t(error)}</p>}{message && <p role="status">{t(message)}</p>}
    </section>
  </main>;
}
