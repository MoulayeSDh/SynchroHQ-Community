"use client";
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useLiveQuery } from "dexie-react-hooks";
import type { Locale } from "../forms/types";
import { db, type Profile } from "../offline/store";
import { syncOutbox } from "../offline/sync";
import { syncReports } from "../offline/reports";
import { pullInbox } from "../offline/inbox";
import { prepareOfflineShell } from "../offline/shell";
import { translateUI } from "./catalog";

export interface SessionInfo {
  id: string; tenant_id: string; display_name: string; offline_edit_seconds: number;
  permissions: string[]; territories: { id: string; name: string; type: string; actions: string[] }[];
  assignments: { id: string; organization: string; role: string; clearance: number;
    scopes: { territory_id: string; coverage: string }[] }[];
}
interface UI {
  locale: Locale; setLocale: (locale: Locale) => void; t: (text: string) => string;
  token: string; info: SessionInfo | null; profile: Profile | null; hydrated: boolean;
  login: (token: string) => Promise<void>; loginWithPassword: (identifier: string, password: string) => Promise<void>;
  logout: () => Promise<void>; can: (action: string) => boolean;
  online: boolean; syncing: boolean; pending: number; blocked: number; corrections: number;
  sync: () => Promise<void>; lastSync: number | null; error: string; clearError: () => void;
}
const Context = createContext<UI | null>(null);
export function SessionProvider({ children }: { children: ReactNode }) {
  const [locale, setLanguage] = useState<Locale>("fr");
  const [token, setToken] = useState("");
  const [info, setInfo] = useState<SessionInfo | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [hydrated, setHydrated] = useState(false);
  const [online, setOnline] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [lastSync, setLastSync] = useState<number | null>(null);
  const [error, setError] = useState("");
  const lock = useRef(false);
  const epoch = useRef(0);
  const drafts = useLiveQuery(() => info ? db.drafts.where("owner").equals(info.id).toArray() : [], [info?.id], []);
  const reports = useLiveQuery(() => info ? db.reports.where("owner").equals(info.id).toArray() : [], [info?.id], []);
  const attachments = useLiveQuery(() => info ? db.attachments.where("owner").equals(info.id).toArray() : [], [info?.id], []);
  const inbox = useLiveQuery(() => info ? db.inbox.where("owner").equals(info.id).toArray() : [], [info?.id], []);
  useEffect(() => {
    const languageTimer = setTimeout(() => { const saved = localStorage.getItem("synchrohq-locale"); if (saved === "fr" || saved === "ar" || saved === "en") setLanguage(saved); }, 0);
    const update = () => setOnline(navigator.onLine);
    update(); window.addEventListener("online", update); window.addEventListener("offline", update);
    // Cached presentation rights are bounded by the verified local profile; never an API credential.
    void (async () => {
      const last = await db.settings.get("last-profile");
      const cached = last ? await db.profiles.get(last.value) : undefined;
      const metadata = cached ? await db.settings.get(`ui-session:${cached.id}`) : undefined;
      if (!navigator.onLine && cached && metadata && cached.editable_until > Date.now()) {
        const value: SessionInfo = JSON.parse(metadata.value);
        if (value.id === cached.id && value.tenant_id === cached.tenant_id) { setInfo(value); setProfile(cached); }
      }
    })().catch(() => setError("Le stockage local est indisponible. Aucune sauvegarde n’est garantie."))
      .finally(() => setHydrated(true));
    return () => { clearTimeout(languageTimer); window.removeEventListener("online", update); window.removeEventListener("offline", update); };
  }, []);
  useEffect(() => { document.documentElement.lang = locale; document.documentElement.dir = locale === "ar" ? "rtl" : "ltr"; }, [locale]);
  useEffect(() => {
    if (hydrated && online) void prepareOfflineShell().catch(e => setError(e instanceof Error ? e.message : "Préparation hors ligne incomplète. Réessayez en ligne."));
  }, [hydrated, online]);
  function setLocale(value: Locale) { localStorage.setItem("synchrohq-locale", value); setLanguage(value); }
  async function login(value: string) {
    const response = await fetch("/api/session-proxy", { headers: { Authorization: `Bearer ${value}` }, cache: "no-store" });
    if (!response.ok) throw new Error("Session refusée.");
    const next: SessionInfo = await response.json();
    const verified = { id: next.id, tenant_id: next.tenant_id, display_name: next.display_name,
      verified_at: Date.now(), editable_until: Date.now() + next.offline_edit_seconds * 1000 };
    epoch.current++;
    await db.transaction("rw", db.profiles, db.settings, async () => {
      await db.profiles.put(verified); await db.settings.put({ key: "last-profile", value: next.id });
      await db.settings.put({ key: `ui-session:${next.id}`, value: JSON.stringify(next) });
    });
    setInfo(next); setProfile(verified); setToken(value); setLastSync(null); setError("");
  }
  async function loginWithPassword(identifier: string, password: string) {
    const response = await fetch("/api/session-proxy/login", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ identifier, password }), cache: "no-store" });
    if (!response.ok) throw new Error(response.status === 401 ? "Identifiant ou mot de passe incorrect." : "Connexion impossible. Vérifiez le réseau puis réessayez.");
    const result: { token: string } = await response.json();
    await login(result.token);
  }
  async function logout() {
    const currentToken = token;
    epoch.current++; setToken(""); setInfo(null); setProfile(null); setLastSync(null); setError("");
    await db.settings.delete("last-profile"); // Drafts are retained, owned by their original author.
    if (currentToken && navigator.onLine) {
      await fetch("/api/session-proxy/logout", { method: "POST", headers: { Authorization: `Bearer ${currentToken}` },
        cache: "no-store", signal: AbortSignal.timeout(5000) }).catch(() => {});
    }
  }
  const sync = useCallback(async () => {
    if (!profile || !token || !navigator.onLine || lock.current) return;
    lock.current = true; setSyncing(true);
    const started = epoch.current;
    try {
      const work = async () => {
        await syncOutbox(profile, token); await syncReports(profile, token);
        if (info?.permissions.includes("reports:create")) await pullInbox(profile, token);
      };
      if (navigator.locks) await navigator.locks.request("synchrohq-sync", work); else await work();
      if (started === epoch.current) { setLastSync(Date.now()); setError(""); }
    } catch { if (started === epoch.current) setError("Synchronisation interrompue."); }
    finally { lock.current = false; setSyncing(false); }
  }, [profile, token, info]);
  useEffect(() => {
    const initial = setTimeout(() => void sync(), 0); const timer = setInterval(() => void sync(), 15000);
    return () => { clearTimeout(initial); clearInterval(timer); };
  }, [sync, online]);
  useEffect(() => {
    if (!token || !online) return;
    let live = true;
    const timer = setInterval(() => {
      void fetch("/api/session-proxy", { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" })
        .then(async response => {
          if (!live) return;
          if (response.status === 401) { setToken(""); setError("Session expirée, reconnectez-vous."); return; }
          if (response.ok) {
            const metadata: SessionInfo = await response.json();
            if (live && metadata.id === info?.id && metadata.tenant_id === info.tenant_id) {
              setInfo(metadata); await db.settings.put({ key: `ui-session:${metadata.id}`, value: JSON.stringify(metadata) });
            }
          }
        }).catch(() => {});
    }, 60000);
    return () => { live = false; clearInterval(timer); };
  }, [token, online, info?.id, info?.tenant_id]);
  const blocked = new Set([...drafts.filter(d => ["BLOCKED", "CONFLICT"].includes(d.state)).map(d=>d.id), ...reports.filter(r=>r.state==="BLOCKED").map(r=>r.draft_id), ...attachments.filter(f=>["BLOCKED","CONFLICT"].includes(f.state)).map(f=>f.draft_id)]).size;
  const pendingIds = new Set([...drafts.filter(d => ["QUEUED", "SYNCING", "ERROR"].includes(d.state)).map(d => d.id),
    ...reports.filter(r => !["RECEIVED","BLOCKED"].includes(r.state)).map(r => r.draft_id),
    ...attachments.filter(f => !["RECEIVED","BLOCKED","CONFLICT"].includes(f.state) && drafts.some(d=>d.id===f.draft_id && d.state!=="LOCAL")).map(f=>f.draft_id)]);
  const t = useCallback((text: string) => translateUI(text, locale), [locale]);
  return <Context.Provider value={{ locale, setLocale, t, token, info, profile,
    hydrated, login, loginWithPassword, logout, can: action => !!info?.permissions.includes(action), online, syncing,
    pending: pendingIds.size, blocked, corrections: inbox.reduce((n, e) => n + e.report.corrections.filter(c => c.state === "OPEN").length, 0),
    sync, lastSync, error, clearError: () => setError("") }}>{children}</Context.Provider>;
}
export function useUI() { const value = useContext(Context); if (!value) throw new Error("Missing SessionProvider"); return value; }
