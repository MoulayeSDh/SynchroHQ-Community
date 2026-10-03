"use client";
import { Badge, AppLink } from "../../ui/Shell";
import { useUI } from "../../ui/session";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useLiveQuery } from "dexie-react-hooks";
import { canEdit, createDraft, db, type Profile } from "../../offline/store";
import { createCorrectionFromBundle } from "../../offline/corrections";
import { pullInbox, type InboxReport } from "../../offline/inbox";
import type { ReportContext } from "../../offline/reports";
import { prepareOfflineShell } from "../../offline/shell";
interface Expected {
    id: string;
    form_id: string;
    organization_id: string;
    territory_id: string;
    period_start: string;
    territory_name: string;
    form_name: string;
    organization_name: string;
    period_end: string;
    expected_by: string;
    status: string;
    received_at?: string;
    explanation: string;
    can_create: boolean;
    report_id?: string;
}
const states: Record<string, string> = { RECEIVED: "Rapports reçus", TO_REVIEW: "À examiner", CORRECTION_REQUESTED: "Correction demandée",
    CORRECTED: "Corrigés", CONFIRMED: "Confirmés", EXPECTED: "Attendus", MISSING: "Manquants", LATE: "Reçus en retard" };
export default function InboxPage() {
    const router = useRouter();
    const [profile, setProfile] = useState<Profile | null>(null);
    const { token, t, can } = useUI();
    const [items, setItems] = useState<InboxReport[]>([]);
    const [view, setView] = useState(can("reports:create") ? "AUTHOR" : "HIERARCHY");
    const [status, setStatus] = useState("");
    const [start, setStart] = useState(() => new Date(Date.now() - 30 * 86400000).toISOString().slice(0, 10));
    const [end, setEnd] = useState(() => new Date().toISOString().slice(0, 10));
    const [territory, setTerritory] = useState("");
    const [form, setForm] = useState("");
    const [author, setAuthor] = useState("");
    const [organization, setOrganization] = useState("");
    const [expected, setExpected] = useState<{
        total: number;
        counts: Record<string, number>;
        items: Expected[];
    } | null>(null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState("");
    const [online, setOnline] = useState(true);
    const local = useLiveQuery(() => profile ? db.inbox.where("owner").equals(profile.id).toArray() : [], [profile?.id], []);
    const drafts = useLiveQuery(() => profile ? db.drafts.where("owner").equals(profile.id).toArray() : [], [profile?.id], []);
    useEffect(() => {
        const update = () => setOnline(navigator.onLine);
        update();
        window.addEventListener("online", update);
        window.addEventListener("offline", update);
        void db.settings.get("last-profile").then(async (last) => setProfile(last ? await db.profiles.get(last.value) ?? null : null));
        return () => { window.removeEventListener("online", update); window.removeEventListener("offline", update); };
    }, []);
    useEffect(() => {
        if (token) {
            const timer = setTimeout(() => void run(synchronize), 0);
            return () => clearTimeout(timer);
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [token]);
    useEffect(() => {
      const filter = (event: Event) => setStatus((event as CustomEvent<string>).detail);
      window.addEventListener("synchrohq:inbox-filter", filter);
      return () => window.removeEventListener("synchrohq:inbox-filter", filter);
    }, []);
    async function api(path: string, method = "GET", data?: object) {
        const response = await fetch("/api/reports-proxy/workflow" + path, { method,
            headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: data ? JSON.stringify(data) : undefined, cache: "no-store" });
        const result = await response.json();
        if (!response.ok)
            throw new Error(result.detail?.code ?? `Accès refusé (${response.status}).`);
        return result;
    }
    async function run(action: () => Promise<void>) {
        setBusy(true);
        setError("");
        try {
            await action();
        }
        catch (e) {
            setError(e instanceof Error ? e.message : t("Opération interrompue."));
        }
        finally {
            setBusy(false);
        }
    }
    async function synchronize() {
        const response = await fetch("/api/sync-proxy/me", { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" });
        if (!response.ok)
            throw new Error(t("Session refusée."));
        const me = await response.json();
        const verified: Profile = { id: me.id, tenant_id: me.tenant_id, display_name: me.display_name,
            verified_at: Date.now(), editable_until: Date.now() + me.offline_edit_seconds * 1000 };
        await db.profiles.put(verified);
        await db.settings.put({ key: "last-profile", value: verified.id });
        setProfile(verified);
        if (navigator.locks)
            await navigator.locks.request("synchrohq-sync", () => pullInbox(verified, token));
        else
            await pullInbox(verified, token);
        const all: InboxReport[] = [];
        for (let offset = 0;; offset += 100) {
            const page: InboxReport[] = await api(`/inbox?offset=${offset}&limit=100`);
            all.push(...page);
            if (page.length < 100)
                break;
        }
        setItems(all);
        setExpected(await api(`/expected?start=${start}&end=${end}`));
        await prepareOfflineShell();
    }
    async function fillExpected(item: Expected) {
        if (!profile || !canEdit(profile))
            throw new Error(t("Session expirée."));
        const cached = (await db.forms.where("owner").equals(profile.id).toArray()).find(c => c.form.id === item.form_id);
        if (!cached)
            throw new Error(t("Préparez d’abord les formulaires dans Collecte."));
        const response = await fetch(`/api/reports-proxy/contexts/${cached.version.id}?expected_report_id=${item.id}`, {
            method: "POST", headers: { Authorization: `Bearer ${token}` }, cache: "no-store"
        });
        if (!response.ok)
            throw new Error(t("Obligation indisponible ou déjà satisfaite."));
        const context: ReportContext = await response.json();
        const draft = await createDraft(profile, { ...cached, report_context: context });
        await db.drafts.update(draft.id, { expected_report_id: item.id });
        router.push(`/collect?draft=${draft.id}`);
    }
    const authorItems = local.filter(e => (!status || status === "RECEIVED" || e.report.workflow_state === status) &&
        (!territory || e.report.territory_id === territory) && (!form || e.report.form_id === form) &&
        (!author || e.report.author_id === author) && (!organization || e.report.revisions.at(-1)?.payload.snapshot.organization.id === organization) &&
        (e.report.period_end ?? e.report.period) >= start && e.report.period <= end).map(e => e.report);
    const hierarchyItems = items.filter(r => (!status || status === "RECEIVED" || r.workflow_state === status) &&
      (!territory || r.territory_id === territory) && (!form || r.form_id === form) && (!author || r.author_id === author) &&
      (!organization || r.revisions.at(-1)?.payload.snapshot.organization.id === organization) && (r.period_end ?? r.period) >= start && r.period <= end);
    const visible = view === "AUTHOR" ? authorItems : online ? hierarchyItems : [];
    const blocked = drafts.filter(d => d.state === "BLOCKED" || d.state === "CONFLICT");
    const waiting = drafts.filter(d => ["LOCAL", "QUEUED", "ERROR", "SYNCING"].includes(d.state));
    const filterReports = [...items, ...local.map(e => e.report)];
    const options = (kind: string): [
        string,
        string
    ][] => [...new Map(filterReports.map(r => {
            const snapshot = r.revisions.at(-1)!.payload.snapshot;
            return kind === t("Territoire") ? [r.territory_id, r.territory_name] : kind === t("Formulaire") ? [r.form_id, r.form_name] :
                kind === t("Auteur") ? [r.author_id, snapshot.author.display_name] : [snapshot.organization.id, snapshot.organization.name];
        }) as [
            string,
            string
        ][]).entries()];
    const expectedItems = expected?.items.filter(item => (!territory || item.territory_id === territory) &&
        (!form || item.form_id === form) && (!organization || item.organization_id === organization)) ?? [];
    const expectedCounts = Object.fromEntries(["RECEIVED", "LATE", "MISSING", "EXPECTED"].map(s => [s, expectedItems.filter(i => i.status === s).length]));
    return <main className="forms-workspace">
    <h1>{t("Inbox et obligations de reporting")}</h1>
    <p>{online ? t("En ligne") : t("Hors connexion — demandes conservées sur cet appareil")}</p>
    {profile && <p>{profile.display_name}{!canEdit(profile) && " · " + t("Session expirée, réauthentification nécessaire")}</p>}
    <button disabled={busy || !token || !online} onClick={() => void run(synchronize)}>{t("Synchroniser mon inbox")}</button>
    <details className="panel"><summary>{t("Filtres")}</summary><div className="filters-grid">
    <div className="filter-field"><label htmlFor="inbox-view">{t("Vue")}</label><select id="inbox-view" value={view} onChange={e => setView(e.target.value)}>
      {can("reports:create") && <option value="AUTHOR">{t("Mes rapports et corrections")}</option>}<option value="HIERARCHY">{t("Inbox hiérarchique")}</option></select></div>
    <div className="filter-field"><label htmlFor="inbox-status">{t("Statut")}</label><select id="inbox-status" value={status} onChange={e => setStatus(e.target.value)}><option value="">{t("Tous")}</option>
      {["RECEIVED", "TO_REVIEW", "CORRECTION_REQUESTED", "CORRECTED", "CONFIRMED"].map(s => <option key={s} value={s}>{t(states[s])}</option>)}</select></div>
    <div className="filter-field"><label htmlFor="period-start">{t("Du")}</label><input id="period-start" type="date" value={start} onChange={e => setStart(e.target.value)}/></div>
    <div className="filter-field"><label htmlFor="period-end">{t("Au")}</label><input id="period-end" type="date" value={end} onChange={e => setEnd(e.target.value)}/></div>
    {[[t("Territoire"), territory, setTerritory], [t("Formulaire"), form, setForm], [t("Auteur"), author, setAuthor], [t("Organisation"), organization, setOrganization]].map(([label, value, setter]) => <label key={String(label)}>{String(label)}<select value={String(value)} onChange={e => (setter as (v: string) => void)(e.target.value)}>
        <option value="">{t("Tous")}</option>{options(String(label)).map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></label>)}
    </div></details>
    {error && <p role="alert">{t(error)}</p>}
    {view === "AUTHOR" && <section className="panel"><h2>{t("À resynchroniser")} : {waiting.length} · {t("Bloqués")} : {blocked.length}</h2>
      {[...blocked, ...waiting].map(d => <p key={d.id}><AppLink href={`/collect?draft=${d.id}`}>{d.form.name} · {t(d.state)}</AppLink> {t(d.error ?? "")}</p>)}</section>}
    <div id="received"/> <div id="corrections"/>
    {visible.map(report => <article className="panel" key={report.id}><h2>{t("Rapport")}{" "}{report.id.slice(0, 8)} · <Badge state={report.workflow_state}/></h2>
      <p>{report.revisions.at(-1)?.payload.snapshot.author.display_name} · {report.revisions.at(-1)?.payload.snapshot.organization.name}</p>
      <AppLink href={`/reports?report=${report.id}`}>{t("Consulter et commenter")}</AppLink>
      {view === "HIERARCHY" && report.capabilities.review && <button disabled={busy || !online || !token} onClick={() => void run(async () => {
                    const key = `review:${profile?.id}:${report.current_revision_id}`;
                    const previous = await db.settings.get(key);
                    const id = previous?.value ?? crypto.randomUUID();
                    await db.settings.put({ key, value: id });
                    await api(`/${report.id}/review`, "POST", { operation_id: id, revision_id: report.current_revision_id });
                    await db.settings.delete(key);
                    await synchronize();
                })}>{t("Marquer comme examiné")}</button>}
      {report.corrections.filter(c => c.state === "OPEN").map(note => <div key={note.id}><h3>{t("Correction demandée")}</h3><p>{note.author} : {note.text}</p>
        {view === "AUTHOR" && <p>{t("Dernière récupération")} : {new Date(local.find(e => e.report.id === report.id)?.pulled_at ?? 0).toLocaleString()}</p>}
        {view === "AUTHOR" && report.capabilities.correct && <button disabled={busy || !profile || !canEdit(profile)} onClick={() => void run(async () => {
                        const entry = local.find(e => e.report.id === report.id);
                        const bundle = entry?.bundles.find(b => b.request_id === note.id);
                        if (!bundle || !profile)
                            throw new Error(entry?.preparation_error ?? t("Synchronisez en ligne pour préparer cette correction."));
                        const draft = await createCorrectionFromBundle(bundle, profile);
                        if (navigator.onLine)
                            router.push(`/collect?draft=${draft.id}`);
                        // Full navigation uses the cached public shell when Next router requests cannot reach the server.
                        else
                            // eslint-disable-next-line @next/next/no-location-assign-relative-destination
                            window.location.href = `/collect?draft=${draft.id}`;
                    })}>{t("Préparer la correction hors ligne")}</button>}</div>)}
    </article>)}
    {busy && <p role="status">{t("Chargement…")}</p>}
    {!busy && !visible.length && <p>{t("Aucun rapport dans cette vue.")}</p>}
    {expected && online && <section className="panel"><h2>{t("Obligations")} : {expectedItems.length}</h2>
      <p>{t("Reçus à temps")} : {expectedCounts.RECEIVED} · {t("Reçus en retard")} : {expectedCounts.LATE} · {t("Manquants")} : {expectedCounts.MISSING} · {t("À venir")} : {expectedCounts.EXPECTED}</p>
      <div className="table-scroll"><table><thead><tr><th>{t("Territoire")}</th><th>{t("Période")}</th><th>{t("Échéance")}</th><th>{t("Statut et justification")}</th><th>{t("Action")}</th></tr></thead><tbody>
        {expectedItems.map(item => <tr key={item.id}><td>{item.territory_name}</td><td>{item.period_start} → {item.period_end}</td><td>{item.expected_by}</td>
          <td>{t(states[item.status] ?? t("Reçu à temps"))}<br />{t(item.explanation)}{item.received_at && <><br />{t("Reçu")} : {item.received_at}</>}</td>
          <td>{item.can_create && <button disabled={busy || !token} onClick={() => void run(() => fillExpected(item))}>{t("Remplir le rapport attendu")}</button>}</td></tr>)}</tbody></table></div>
    </section>}
  </main>;
}
