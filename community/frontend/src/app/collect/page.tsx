"use client";
import { AppLink } from "../../ui/Shell";
import { useUI } from "../../ui/session";
import { useCallback, useEffect, useRef, useState } from "react";
import { useLiveQuery } from "dexie-react-hooks";
import { translate as translateForm } from "../../forms/translations";
import { Badge } from "../../ui/Shell";
import { DynamicFormRenderer } from "../../forms/DynamicFormRenderer";
import type { Answers, FormRecord, FormVersion } from "../../forms/types";
import { addAttachment, canEdit, createDraft, db, duplicateDraft, queueDraft, removeAttachment, saveDraft, type CachedForm, type Draft, type Profile, type SyncState } from "../../offline/store";
import { prepareOfflineShell } from "../../offline/shell";
import { ReportActions } from "../../offline/ReportActions";
import { syncReports, type ReportContext } from "../../offline/reports";
import { pullInbox } from "../../offline/inbox";
import { syncOutbox } from "../../offline/sync";
const states: Record<SyncState, string> = { LOCAL: "Enregistré sur cet appareil", QUEUED: "En attente d’envoi",
    SYNCING: "Envoi en cours", RECEIVED: "Reçu par le serveur", ERROR: "Envoi à réessayer",
    BLOCKED: "Envoi bloqué — données conservées", CONFLICT: "Conflit — données conservées" };
export default function CollectPage() {
    const [profile, setProfile] = useState<Profile | null>(null);
    const { token, t, locale, info, can } = useUI();
    const [authenticated, setAuthenticated] = useState<string | null>(null);
    const [online, setOnline] = useState(true);
    const [ready, setReady] = useState(false);
    const [error, setError] = useState("");
    const [busy, setBusy] = useState(false);
    const [saving, setSaving] = useState(false);
    const [saveFailed, setSaveFailed] = useState(false);
    const [selected, setSelected] = useState<Draft | null>(null);
    const [values, setValues] = useState<Answers>({});
    const localRevision = useRef(0);
    const saveChain = useRef<Promise<void>>(Promise.resolve());
    const saveFailedRef = useRef(false);
    const syncing = useRef(false);
    const cached = useLiveQuery(() => profile ? db.forms.where("owner").equals(profile.id).toArray() : [], [profile?.id], []);
    const drafts = useLiveQuery(() => profile ? db.drafts.where("owner").equals(profile.id).toArray() : [], [profile?.id], []);
    const attachments = useLiveQuery(() => selected ? db.attachments.where("draft_id").equals(selected.id).toArray() : [], [selected?.id], []);
    const localReport = useLiveQuery(() => selected ? db.reports.where("draft_id").equals(selected.id).first() : undefined, [selected?.id]);
    const current = drafts.find(d => d.id === selected?.id) ?? selected;
    const pending = useLiveQuery(() => selected ? db.outbox.where("draft_id").equals(selected.id).count() : 0, [selected?.id], 0);
    useEffect(() => {
        const update = () => setOnline(navigator.onLine);
        update();
        window.addEventListener("online", update);
        window.addEventListener("offline", update);
        void db.settings.get("last-profile").then(async (value) => {
            if (value) {
                const savedProfile = await db.profiles.get(value.value);
                setProfile(savedProfile ?? null);
                const draftId = new URLSearchParams(window.location.search).get("draft");
                const draft = draftId ? await db.drafts.get(draftId) : undefined;
                if (draft && savedProfile && draft.owner === savedProfile.id && draft.tenant_id === savedProfile.tenant_id) {
                    setSelected(draft);
                    setValues(draft.answers);
                    localRevision.current = draft.revision;
                }
            }
        }).catch(() => setError(t("Le stockage local est indisponible. Aucune sauvegarde n’est garantie.")));
        void prepareOfflineShell().then(() => setReady(true)).catch(e => setError(String(e.message)));
        return () => { window.removeEventListener("online", update); window.removeEventListener("offline", update); };
    // A language change must not reopen a draft or reset an unsaved edit.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);
    const synchronize = useCallback(async (retry = false) => {
        if (!profile || authenticated !== profile.id || !token || !navigator.onLine || syncing.current)
            return;
        syncing.current = true;
        try {
            const work = async () => { await syncOutbox(profile, token, db, fetch, retry); await syncReports(profile, token, db, fetch, retry); await pullInbox(profile, token); };
            if (navigator.locks)
                await navigator.locks.request("synchrohq-sync", work);
            else
                await work();
        }
        catch (e) {
            setError(e instanceof Error ? e.message : t("Synchronisation interrompue."));
        }
        finally {
            syncing.current = false;
        }
    }, [profile, token, authenticated, t]);
    useEffect(() => {
        const initial = setTimeout(() => void synchronize(), 0);
        const timer = setInterval(() => void synchronize(), 10000);
        return () => { clearTimeout(initial); clearInterval(timer); };
    }, [online, synchronize]);
    useEffect(() => {
        if (token && info?.id) {
            const timer = setTimeout(() => void run(connect), 0);
            return () => clearTimeout(timer);
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [token, info?.id]);
    async function run(action: () => Promise<void>) {
        setError("");
        setBusy(true);
        try {
            await action();
        }
        catch (e) {
            const message = e instanceof Error ? e.message : t("Opération impossible.");
            if (message.startsWith("Réponses à corriger : ") && current) {
              const labels = message.slice("Réponses à corriger : ".length).split(", ").map(path => {
                const field = current.formVersion.ui_schema.fields[path.replace(/\/\d+(?=\/|$)/g,"/*")];
                return translateForm(current.formVersion, locale, field?.label_key, t("Contenu du rapport"));
              });
              setError(t("Réponses à corriger") + " : " + labels.join(", "));
            } else setError(message);
        }
        finally {
            setBusy(false);
        }
    }
    async function api<T>(url: string, method = "GET"): Promise<T> {
        const response = await fetch(url, { method, headers: { Authorization: `Bearer ${token}` }, cache: "no-store" });
        if (!response.ok)
            throw new Error(`Accès refusé ou session expirée (${response.status}). Les données locales sont conservées.`);
        return response.json() as Promise<T>;
    }
    async function connect() {
        const user = await api<{
            id: string;
            tenant_id: string;
            display_name: string;
            offline_edit_seconds: number;
        }>("/api/sync-proxy/me");
        const verified: Profile = { ...user, verified_at: Date.now(), editable_until: Date.now() + user.offline_edit_seconds * 1000 };
        await db.profiles.put(verified);
        await db.settings.put({ key: "last-profile", value: verified.id });
        if (profile?.id && profile.id !== verified.id) {
            setSelected(null);
            setValues({});
        }
        setProfile(verified);
        setAuthenticated(verified.id);
        const forms: FormRecord[] = [];
        for (let offset = 0;; offset += 100) {
            const page = await api<FormRecord[]>(`/api/forms-proxy?offset=${offset}&limit=100`);
            forms.push(...page);
            if (page.length < 100)
                break;
        }
        const entries: CachedForm[] = [];
        for (const form of forms.filter(f => f.actions?.collect)) {
            const versions = await api<FormVersion[]>(`/api/forms-proxy/${form.id}/versions`);
            for (const version of versions.filter(v => v.status === "PUBLISHED")) {
                const grant = await api<{
                    sync_grant: string;
                    expires_at: string;
                }>(`/api/sync-proxy/grants/${version.id}`, "POST");
                const contextResponse = await fetch(`/api/reports-proxy/contexts/${version.id}`, {
                    method: "POST", headers: { Authorization: `Bearer ${token}` }, cache: "no-store"
                });
                let reportContext: ReportContext | undefined;
                if (contextResponse.ok)
                    reportContext = await contextResponse.json();
                else if (contextResponse.status !== 403)
                    throw new Error(t("Préparation des droits de confirmation interrompue."));
                entries.push({ key: verified.id + ":" + version.id, owner: verified.id, form, version,
                    sync_grant: grant.sync_grant, grant_expires_at: grant.expires_at, report_context: reportContext });
            }
        }
        await db.transaction("rw", db.forms, async () => {
            await db.forms.where("owner").equals(verified.id).delete();
            await db.forms.bulkPut(entries);
        });
        // Existing drafts carry their exact immutable form snapshot independently of this catalogue.
        await prepareOfflineShell();
        setReady(true);
        await navigator.storage?.persist?.();
        await pullInbox(verified, token);
    }
    async function open(draft: Draft) {
        await saveChain.current;
        if (saveFailedRef.current)
            throw new Error(t("Exportez les réponses non enregistrées avant de changer de brouillon."));
        const latest = await db.drafts.get(draft.id);
        if (!latest)
            return;
        setSelected(latest);
        setValues(latest.answers);
        localRevision.current = latest.revision;
    }
    function change(answers: Answers) {
        if (!selected || !profile)
            return;
        setValues(answers);
        setSaving(true);
        const id = selected.id;
        const snapshot = structuredClone(answers);
        saveChain.current = saveChain.current.then(async () => {
            if (saveFailedRef.current)
                return;
            try {
                const saved = await saveDraft(id, localRevision.current, snapshot, profile);
                localRevision.current = saved.revision;
            }
            catch (e) {
                saveFailedRef.current = true;
                setSaveFailed(true);
                setError(e instanceof Error ? e.message : t("Échec de sauvegarde locale."));
            }
        });
        const latest = saveChain.current;
        void latest.then(() => { if (latest === saveChain.current)
            setSaving(false); });
    }
    function exportDraft() {
        if (!current)
            return;
        const content = JSON.stringify({ ...current, answers: values, confirmation: localReport, exported_at: new Date().toISOString() }, null, 2);
        const url = URL.createObjectURL(new Blob([content], { type: "application/json" }));
        const a = document.createElement("a");
        a.href = url;
        a.download = `synchrohq-draft-${current.id}.json`;
        a.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
    }
    return <main className="forms-workspace"><AppLink href="/inbox">{t("Mes rapports et corrections")}</AppLink>
    <header><AppLink href="/forms">SynchroHQ · Formulaires</AppLink><h1>{t("Collecte hors ligne")}</h1>
      <p>{online ? t("Connexion disponible") : t("Hors connexion")} · {ready ? t("Application préparée pour le hors-ligne") : t("Préparation du mode hors ligne…")}</p>
      <p>{t("Enregistrez un brouillon, finalisez les réponses puis confirmez explicitement le rapport.")}</p><AppLink href="/reports">Consulter les rapports confirmés</AppLink></header>
    <div className="toolbar"><button disabled={busy || saving || !online || !token} onClick={() => void run(connect)}>{t("Préparer mes formulaires")}</button></div>
    {error && <p className="field-error" role="alert">{t(error)}</p>}
    {profile && <>
      {!canEdit(profile) && <p role="status">{t("La session locale a expiré. Vous pouvez lire et exporter vos brouillons ; reconnectez-vous pour les modifier.")}</p>}
      <div className="workspace-grid"><aside className="panel"><h2 id="drafts">{t("Mes brouillons")}</h2>
        {drafts.map(d => <button key={d.id} className="catalog-item" disabled={busy || saving} onClick={() => void run(() => open(d))}>{d.form.name} · {d.id.slice(0, 8)}<br /><Badge state={d.state}/></button>)}
        {drafts.length === 0 && <p>{t("Aucun brouillon sur cet appareil.")}</p>}
        <h2 id="new-draft">{t("Nouveau brouillon")}</h2>
        {cached.map(c => <button key={c.key} className="catalog-item" disabled={busy || saving || !canEdit(profile)} onClick={() => void run(async () => { const draft = await createDraft(profile, c); await open(draft); })}>
          {c.form.name} · v{c.version.version}</button>)}
      </aside><section className="panel">
        {!current ? <p>{t("Créez ou ouvrez un brouillon. Chaque modification est enregistrée sur cet appareil.")}</p> : <>
          <div className="toolbar"><strong data-testid="draft-state">{saving ? t("Enregistrement local…") : <Badge state={current.state}/>}</strong>
            <button onClick={exportDraft}>{t("Exporter une copie JSON")}</button>
            </div>
          <p>{t("Formulaire")} v{current.formVersion.version} · {t("copie serveur")} v{current.server_version}</p>
          {current.error && <p role="alert">{t(current.error)} — {t("le brouillon et son opération restent sur cet appareil.")}</p>}
          <fieldset disabled={!!pending || !canEdit(profile) || saveFailed || current.business_state === "FINALIZED" || current.business_state === "CONFIRMED"} style={{ border: 0, padding: 0 }}>
            <DynamicFormRenderer key={current.id} form={current.formVersion} locale={locale} values={values} onChange={change} managedAttachments/>
          </fieldset>
          <fieldset disabled={!!pending || !canEdit(profile) || current.state === "RECEIVED" || current.business_state === "FINALIZED" || current.business_state === "CONFIRMED"}>
            <legend>{t("Fichiers conservés sur cet appareil")}</legend>
            <label className="button upload-button" htmlFor="draft-attachment">{t("Ajouter une pièce jointe")}<input id="draft-attachment" className="sr-only" aria-label={t("Ajouter une pièce jointe")} type="file" accept="image/jpeg,image/png,application/pdf" onChange={event => {
                    const file = event.target.files?.[0];
                    event.target.value = "";
                    if (!file)
                        return;
                    void run(async () => {
                        await saveChain.current;
                        if (saveFailedRef.current)
                            throw new Error(t("Sauvegarde locale non terminée."));
                        const updated = await addAttachment(current.id, localRevision.current, file, profile);
                        localRevision.current = updated.revision;
                        setValues(updated.answers);
                    });
                }}/>
            </label>
            {attachments.map(attachment => <p key={attachment.id}>
              {attachment.file_name} · {(attachment.size / 1024).toFixed(1)} Kio · {t(states[attachment.state] ?? attachment.state)}
              {attachment.error ? ` · ${attachment.error}` : ""} {attachment.state !== "RECEIVED" &&
                        <button type="button" onClick={() => void run(async () => {
                                const updated = await removeAttachment(current.id, attachment.id, localRevision.current, profile);
                                localRevision.current = updated.revision;
                                setValues(updated.answers);
                            })}>{t("Retirer")}</button>}
            </p>)}
          </fieldset>
          <div className="toolbar">
            <button disabled={busy || saving || !!pending || !canEdit(profile) || saveFailed || current.state === "RECEIVED" || current.business_state === "CONFIRMED"} onClick={() => void run(async () => {
                    await saveChain.current;
                    if (saveFailedRef.current)
                        throw new Error(t("Sauvegarde locale non terminée."));
                    await queueDraft(current.id, profile);
                    await synchronize();
                })}>{t("Mettre en attente d’envoi")}</button>
            <button disabled={busy || saving || !online || authenticated !== profile.id} onClick={() => void run(() => synchronize(true))}>{t("Synchroniser maintenant")}</button>
            <button disabled={busy || saving || !canEdit(profile)} onClick={() => void run(async () => {
                    const copy = await duplicateDraft({ ...current, answers: values }, profile);
                    saveFailedRef.current = false;
                    setSaveFailed(false);
                    await open(copy);
                })}>{t("Dupliquer pour continuer")}</button>
          </div>
          {can("reports:confirm") && current.report_context && <ReportActions key={current.id} draft={current} profile={profile} report={localReport} revision={current.revision} disabled={busy || saving || saveFailed || !!pending} run={run} sync={() => synchronize()}/> }
          {current.state === "CONFLICT" && <p>{t("Aucun écrasement automatique. Exportez votre copie ou dupliquez-la sous un nouvel identifiant.")}</p>}
          {current.receipt && <p>{t("Dernier accusé serveur")} : {current.receipt.server_received_at} ·
            {current.receipt.validation.valid ? " réponses valides" : " brouillon reçu, réponses à compléter"}</p>}
        </>}
      </section></div>
    </>}
  </main>;
}
