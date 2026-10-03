"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useUI } from "./session";
import { statusNames } from "./catalog";
import { db } from "../offline/store";
import { useLiveQuery } from "dexie-react-hooks";
import type { Locale } from "../forms/types";

const names: Record<string, string> = { author_1: "Auteur communal", reviewer: "Responsable territorial", regional: "Responsable régional",
  central: "Lecteur central", other_wilaya: "Autre Wilaya", admin: "Administrateur" };
export function Brand() {
  return <span className="brand"><svg viewBox="0 0 100 100" aria-hidden="true"><g fill="none" strokeWidth="7" strokeLinecap="round">
    <path d="M50 20V50M20 50H80M50 50V80" stroke="#14bd9d" />
    <path d="M21 30A36 36 0 0 1 30 21M70 21A36 36 0 0 1 79 30M79 70A36 36 0 0 1 70 79M30 79A36 36 0 0 1 21 70" stroke="#00bce8" /></g>
    <circle cx="50" cy="50" r="14" fill="#008aff" /><circle cx="50" cy="16" r="11" fill="#24c653" />
    <circle cx="16" cy="50" r="11" fill="#24c653" /><circle cx="84" cy="50" r="11" fill="#24c653" /><circle cx="50" cy="84" r="11" fill="#008aff" />
  </svg><span>Synchro<span className="hq">HQ</span></span></span>;
}
export function Badge({ state }: { state: string }) { const { t } = useUI(); return <span className={`badge status-${state.toLowerCase()}`}>{t(statusNames[state] ?? state)}</span>; }
export function AppLink({ href, children, ...props }: { href: string; children: ReactNode; className?: string; onClick?: () => void; "aria-current"?: "page" }) {
  const { online } = useUI();
  return <Link href={href} {...props} onClick={event => {
    props.onClick?.();
    if (!online) {
      event.preventDefault();
      // The public shell can navigate from its service-worker cache without an RSC request.
      window.location.href = href;
    }
  }}>{children}</Link>;
}
function Login() {
  const { t, login, loginWithPassword, online } = useUI();
  const [accounts, setAccounts] = useState<string[]>([]);
  const [token, setToken] = useState(""); const [error, setError] = useState(""); const [busy, setBusy] = useState(false);
  const [identifier, setIdentifier] = useState(""); const [password, setPassword] = useState("");
  useEffect(() => { void fetch("/api/session-proxy/demo", { cache: "no-store" }).then(async r => { if (r.ok) setAccounts(await r.json()); }).catch(() => {}); }, []);
  async function connect(code?: string) {
    setBusy(true); setError("");
    try {
      let value = token;
      if (code) {
        const response = await fetch("/api/session-proxy/demo", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ account: code }) });
        if (!response.ok) throw new Error("La connexion de démonstration n’est pas disponible.");
        value = (await response.json()).token;
      }
      await login(value);
    } catch(e) { setError(e instanceof Error ? e.message : "Session refusée."); } finally { setBusy(false); }
  }
  async function connectPassword() {
    setBusy(true); setError("");
    try { await loginWithPassword(identifier, password); setPassword(""); }
    catch(e) { setError(e instanceof Error ? e.message : "Session refusée."); }
    finally { setBusy(false); }
  }
  return <main className="login-page" id="main-content"><section className="login-card"><Brand />
    <p className="brand-promise">{t("Collecter. Synchroniser. Agir. Ensemble.")}</p><h1>{t("Connexion")}</h1>
    <form onSubmit={e => { e.preventDefault(); void connectPassword(); }}>
      <label htmlFor="login-identifier">{t("Identifiant")}</label>
      <input id="login-identifier" type="text" autoComplete="username" required value={identifier} onChange={e => setIdentifier(e.target.value)} />
      <label htmlFor="login-password">{t("Mot de passe")}</label>
      <input id="login-password" type="password" autoComplete="current-password" required value={password} onChange={e => setPassword(e.target.value)} />
      <button className="primary" type="submit" disabled={busy || !identifier || !password || !online}>{t("Se connecter")}</button>
    </form>
    {accounts.length > 0 && <><span className="badge">{t("Pilote local")}</span><h2>{t("Comptes de démonstration")}</h2>
      <p>{t("Ces comptes utilisent uniquement les données synthétiques du pilote local.")}</p>
      <div className="account-grid">{accounts.map(code => <button key={code} data-account={code} disabled={busy || !online}
        onClick={() => void connect(code)}>{t(names[code] ?? code)}<span aria-hidden="true">→</span></button>)}</div></>}
    {!online && <p role="status">{t("Hors connexion")}. {t("Connectez-vous pour accéder à votre espace.")}</p>}
    <details><summary>{t("Connexion avancée")}</summary><p>{t("Le jeton reste uniquement en mémoire pendant cette session.")}</p>
      <label htmlFor="session-token">{t("Jeton d’accès")}</label><input id="session-token" type="password" value={token} autoComplete="off" onChange={e => setToken(e.target.value)} />
      <button className="primary" disabled={busy || !token || !online} onClick={() => void connect()}>{t("Se connecter")}</button></details>
    {error && <p role="alert">{t(error)}</p>}{busy && <p role="status">{t("Chargement…")}</p>}
  </section></main>;
}
export function ApplicationShell({ children }: { children: ReactNode }) {
  const { t, locale, setLocale, info, hydrated, can, online, token, pending, blocked, syncing, sync, logout, lastSync, corrections, error, clearError } = useUI();
  const pathname = usePathname(); const [menu, setMenu] = useState(false); const [notifications, setNotifications] = useState(false);
  const close = useRef<HTMLButtonElement>(null); const toggle = useRef<HTMLButtonElement>(null);
  const drafts = useLiveQuery(() => info ? db.drafts.where("owner").equals(info.id).toArray() : [], [info?.id], []);
  useEffect(() => { if (menu) close.current?.focus(); }, [menu]);
  function closeMenu() { setMenu(false); toggle.current?.focus(); }
  const nav = [{ href: "/", label: "Accueil", icon: "home", permission: "" },
    { href: "/collect", label: "Collecte", icon: "collect", permission: "drafts:sync" },
    { href: "/reports", label: can("reports:create") ? "Mes rapports" : "Rapports", icon: "reports", permission: "reports:read" },
    { href: "/inbox", label: "Inbox", icon: "inbox", permission: "reports:read" },
    { href: "/analytics", label: "Pilotage", icon: "analytics", permission: "reports:read" },
    { href: "/map", label: "Carte des rapports", icon: "map", permission: "reports:read" },
    { href: "/forms", label: "Formulaires", icon: "forms", permission: "forms:read" },
    { href: "/administration", label: "Administration", icon: "admin", permission: "administration:read" },
    { href: "/profile", label: "Profil", icon: "profile", permission: "" }].filter(n => !n.permission || can(n.permission));
  const denied = info && ((pathname.startsWith("/collect") && !can("drafts:sync")) || (pathname.startsWith("/forms") && !can("forms:read")) ||
    (pathname.startsWith("/administration") && !can("administration:read")) || (["/reports", "/inbox", "/analytics", "/map"].includes(pathname) && !can("reports:read")));
  return <div className="app-shell"><a className="skip-link" href="#main-content">{t("Aller au contenu")}</a>
    {info && <><button className={`nav-scrim ${menu ? "visible" : ""}`} aria-label={t("Fermer le menu")} onClick={closeMenu} tabIndex={menu ? 0 : -1} />
      <aside className={`sidebar ${menu ? "open" : ""}`} role={menu ? "dialog" : undefined} aria-modal={menu || undefined} aria-label={t("Navigation")} onKeyDown={e => {
          if (e.key === "Escape") closeMenu();
          if (menu && e.key === "Tab") {
            const nodes = [...e.currentTarget.querySelectorAll<HTMLElement>("a[href], button:not([disabled])")].filter(n => n.offsetParent !== null);
            const first = nodes[0], last = nodes.at(-1);
            if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last?.focus(); }
            else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus(); }
          }
        }}>
        <AppLink href="/" className="brand-link" onClick={closeMenu}><Brand /></AppLink>
        <button className="mobile-only close-menu" ref={close} aria-label={t("Fermer le menu")} onClick={closeMenu}>×</button>
        <p className="nav-caption">{t("Votre espace de travail")}</p><nav aria-label={t("Navigation")}>{nav.map(n => <div key={n.href}>
          <AppLink href={n.href} aria-current={pathname === n.href ? "page" : undefined} onClick={closeMenu}>
            <NavIcon kind={n.icon} /><span>{t(n.label)}</span>{n.href === "/inbox" && pending > 0 && <span className="nav-count">{pending}</span>}</AppLink>
          {n.href === "/collect" && pathname === "/collect" && <div className="subnav"><a href="#new-draft">{t("Nouveau rapport")}</a><a href="#drafts">{t("Brouillons")}</a></div>}
          {n.href === "/inbox" && pathname === "/inbox" && <div className="subnav"><button onClick={() => window.dispatchEvent(new CustomEvent("synchrohq:inbox-filter", { detail: "" }))}>{t("Rapports reçus")}</button><button onClick={() => window.dispatchEvent(new CustomEvent("synchrohq:inbox-filter", { detail: "CORRECTION_REQUESTED" }))}>{t("Corrections")}</button></div>}
        </div>)}</nav><div className="sidebar-footer"><span className="badge">Community</span><p>{t("Des informations fiables du terrain à la décision.")}</p></div>
      </aside></>}
    <div className={info ? "app-body" : "guest-body"}><header className="topbar">
      {info ? <><button ref={toggle} className="mobile-only" aria-expanded={menu} aria-label={t("Ouvrir le menu")} onClick={() => setMenu(true)}>☰</button>
        <div className="identity"><strong>{info.display_name}</strong><span>{info.assignments[0]?.organization} · {info.territories.find(r => info.assignments[0]?.scopes.some(s => s.territory_id === r.id))?.name}</span></div></> : <Brand />}
      <div className="topbar-actions"><label className="sr-only" htmlFor="app-language">{t("Langue")}</label><select id="app-language" value={locale} onChange={e => setLocale(e.target.value as Locale)}><option value="fr">FR</option><option value="ar">العربية</option><option value="en">EN</option></select>
        {info && <><button aria-expanded={notifications} aria-label={t("Notifications")} onClick={() => setNotifications(!notifications)}><NavIcon kind="bell" /></button>
          <button className="logout" onClick={() => void logout()}>{t("Se déconnecter")}</button></>}</div>
    </header>
    {info && <section className="connection-strip" aria-label={t("Synchronisation")}><span className={`network-dot ${online ? "online" : "offline"}`} />
      <span>{t(online ? "En ligne" : "Hors connexion")}</span><span className="strip-divider" />
      <span role="status">{t(syncing ? "Synchronisation en cours…" : blocked ? "Bloqués" : pending ? "À synchroniser" : lastSync ? "À jour" : token ? "Synchronisation" : "Données conservées sur cet appareil")}{(pending + blocked) > 0 && ` · ${blocked || pending}`}{blocked > 0 && pending > 0 && ` · ${t("À synchroniser")} : ${pending}`}</span>
      <button disabled={!online || syncing} onClick={() => token ? void sync() : void logout()}>{t(token ? "Synchroniser maintenant" : "Se connecter")}</button>
    </section>}
    {notifications && info && <section className="notification-panel panel" aria-label={t("Notifications")}><h2>{t("Notifications")}</h2>
      {corrections > 0 && <p><AppLink href="/inbox">{t("Corrections demandées")} : {corrections}</AppLink></p>}{pending > 0 && <p>{t("À synchroniser")} : {pending}</p>}{blocked > 0 && <p>{t("Bloqués")} : {blocked}</p>}
      {drafts.filter(d => d.error).map(d => <p key={d.id}><AppLink href={`/collect?draft=${d.id}`}>{d.form.name}</AppLink> · {t(d.error ?? "")}</p>)}
      {!pending && !blocked && !corrections && <p>{t("Aucune notification.")}</p>}<button onClick={() => setNotifications(false)}>{t("Fermer")}</button></section>}
    {error && info && <div className="global-error" role="alert">{t(error)} <button onClick={clearError}>{t("Fermer")}</button></div>}
    {!hydrated ? <main id="main-content"><p role="status">{t("Chargement…")}</p></main> : !info ? <Login /> : denied ? <main id="main-content"><h1>{t("Accès non autorisé")}</h1><p>{t("Vos droits ne permettent pas cette action.")}</p><AppLink href="/">{t("Accueil")}</AppLink></main> : <div id="main-content" tabIndex={-1}>{children}</div>}
    </div></div>;
}
function NavIcon({ kind }: { kind: string }) {
  const paths: Record<string, string> = { home: "M3 10l9-7 9 7v10h-6v-7H9v7H3z", collect: "M12 3v18M3 12h18", reports: "M6 3h8l4 4v14H6zM10 11h5M10 15h5", inbox: "M3 5h18v15H3zM3 13h5l2 3h4l2-3h5", analytics: "M3 20V11h4v9M10 20V4h4v16M17 20v-7h4v7", map: "M3 5l6-2 6 2 6-2v16l-6 2-6-2-6 2zM9 3v16M15 5v16", forms: "M5 3h14v18H5zM8 8h8M8 12h8M8 16h5", admin: "M12 3l8 4v5c0 5-8 9-8 9s-8-4-8-9V7z", profile: "M16 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0M4 21v-3a8 5 0 0 1 16 0v3", bell: "M6 17V9a6 6 0 0 1 12 0v8l2 2H4zM10 22h4" };
  return <svg className="nav-icon" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round" strokeLinecap="round"><path d={paths[kind]} /></svg>;
}
