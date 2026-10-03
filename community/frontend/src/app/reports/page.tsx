"use client";
import { ReadOnlyAnswers } from "../../ui/ReadOnlyAnswers";
import { Badge, AppLink } from "../../ui/Shell";
import { useUI } from "../../ui/session";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { createCorrectionDraft, type OfficialRevision } from "../../offline/corrections";
import { db } from "../../offline/store";
interface Note {
    id: string;
    revision_id: string;
    author: string;
    text: string;
    created_at: string;
    state?: string;
}
interface Report {
    id: string;
    current_revision_id: string;
    viewer_id: string;
    revisions: OfficialRevision[];
    comments: Note[];
    corrections: Note[];
    capabilities: {
        comment: boolean;
        request_correction: boolean;
        correct: boolean;
    };
}
interface Mutation {
    operation_id: string;
    revision_id: string;
    text: string;
}
function WorkflowForm({ report, revision, token, kind, refresh }: {
    report: Report;
    revision: OfficialRevision;
    token: string;
    kind: "comments" | "correction-requests";
    refresh: () => Promise<void>;
}) {
    const { t } = useUI();
    const [text, setText] = useState("");
    const [pending, setPending] = useState<Mutation | null>(null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState("");
    const key = `workflow:${report.viewer_id}:${revision.id}:${kind}`;
    useEffect(() => { void db.settings.get(key).then(saved => { if (saved)
        setPending(JSON.parse(saved.value)); }); }, [key]);
    async function submit() {
        setBusy(true);
        setError("");
        try {
            const saved = await db.settings.get(key);
            const body: Mutation = saved ? JSON.parse(saved.value) : { operation_id: crypto.randomUUID(), revision_id: revision.id, text: text.trim() };
            await db.settings.put({ key, value: JSON.stringify(body) });
            setPending(body);
            const response = await fetch(`/api/reports-proxy/${report.id}/${kind}`, { method: "POST",
                headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify(body) });
            const result = await response.json();
            if (!response.ok) {
                if ([409, 422].includes(response.status)) {
                    await db.settings.delete(key);
                    setPending(null);
                }
                throw new Error(result.detail?.code ?? `HTTP_${response.status}`);
            }
            if (result.operation_id !== body.operation_id || result.revision_id !== revision.id || !result.id)
                throw new Error(t("Accusé incohérent. L’opération reste conservée."));
            await db.settings.delete(key);
            setPending(null);
            setText("");
            await refresh();
        }
        catch (e) {
            setError(e instanceof Error ? e.message : t("Envoi interrompu."));
        }
        finally {
            setBusy(false);
        }
    }
    return <div><label htmlFor={key}>{kind === "comments" ? t("Commentaire") : t("Motif de correction")}</label>
    <textarea id={key} maxLength={4000} value={pending?.text ?? text} disabled={busy || !!pending} onChange={e => setText(e.target.value)}/>
    <button disabled={busy || (!pending && !text.trim())} onClick={() => void submit()}>
      {pending ? t("Réessayer le même envoi") : kind === "comments" ? t("Ajouter le commentaire") : t("Demander une correction")}</button>
    {error && <p role="alert">{t(error)}</p>}</div>;
}
export default function ReportsPage() {
    const router = useRouter();
    const { token, t, can, online } = useUI();
    const [items, setItems] = useState<{
        id: string;
        created_at: string;
    }[]>([]);
    const [report, setReport] = useState<Report | null>(null);
    const [error, setError] = useState("");
    const [busy, setBusy] = useState(false);
    async function load() {
        const all: {
            id: string;
            created_at: string;
        }[] = [];
        for (let offset = 0;; offset += 100) {
            const page = await (await request(`?${can("reports:create") ? "own=true&" : ""}offset=${offset}&limit=100`)).json();
            all.push(...page);
            if (page.length < 100)
                break;
        }
        setItems(all);
        const requested = new URLSearchParams(window.location.search).get("report");
        setReport(requested ? await (await request("/" + requested)).json() : null);
    }
    useEffect(() => {
        if (token && online) {
            const timer = setTimeout(() => void run(load), 0);
            return () => clearTimeout(timer);
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [token, online]);
    async function request(path: string) {
        const response = await fetch("/api/reports-proxy" + path, { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" });
        if (!response.ok)
            throw new Error(`Rapport inaccessible (${response.status}).`);
        return response;
    }
    async function run(action: () => Promise<void>) {
        setError("");
        setBusy(true);
        try {
            await action();
        }
        catch (e) {
            setError(e instanceof Error ? e.message : t("Opération impossible."));
        }
        finally {
            setBusy(false);
        }
    }
    async function refresh() { if (report)
        setReport(await (await request("/" + report.id)).json()); }
    return <main className="forms-workspace"><h1>{t("Rapports confirmés")}</h1>
    {!online && <p role="status">{t("Données serveur indisponibles hors connexion.")}</p>}
    <button disabled={busy || !token || !online} onClick={() => void run(load)}>{t("Actualiser")}</button>
    {error && <p role="alert">{t(error)}</p>}
    <div className="workspace-grid"><aside className="panel"><h2>{t("Rapports accessibles")}</h2>
      {items.map(item => <button key={item.id} disabled={busy} onClick={() => void run(async () => {
                setReport(await (await request("/" + item.id)).json());
            })}>{item.id.slice(0, 8)} · {item.created_at}</button>)}
      {!items.length && <p>{t("Aucun rapport chargé.")}</p>}</aside>
      <section className="panel">{busy && <p role="status">{t("Chargement…")}</p>}{!report && !busy && <p>{t("Aucun rapport sélectionné.")}</p>}{report && <><h2>{t("Rapport")}{" "}{report.id.slice(0, 8)}</h2>
        {report.revisions.map(revision => <article key={revision.id} id={`revision-${revision.id}`}><h3>{t("Révision")}{" "}{revision.number} · <Badge state={revision.state}/></h3>
          <p>{revision.payload.snapshot.author.display_name} · {revision.payload.snapshot.organization.name}</p>
          <p>{t("Confirmé le")}{" "}{revision.payload.confirmed_at}</p>
          <code style={{ overflowWrap: "anywhere" }}>{revision.payload_hash}</code>
          <ReadOnlyAnswers form={revision.form_definition} answers={revision.payload.answers} />
          {revision.payload.attachments.map(file => <button key={file.attachment_id} disabled={busy} onClick={() => void run(async () => {
                        const response = await request(`/${report.id}/attachments/${file.attachment_id}?revision_id=${revision.id}`);
                        const url = URL.createObjectURL(await response.blob());
                        const link = document.createElement("a");
                        link.href = url;
                        link.download = file.file_name;
                        link.click();
                        setTimeout(() => URL.revokeObjectURL(url), 1000);
                    })}>{t("Télécharger")}{" "}{file.file_name}</button>)}
          <h4>{t("Commentaires")}</h4>
          {report.comments.filter(c => c.revision_id === revision.id).map(c => <p key={c.id}>{c.author} · {c.created_at}<br />{c.text}</p>)}
          {report.capabilities.comment && <WorkflowForm report={report} revision={revision} token={token} kind="comments" refresh={refresh}/>}
          {report.corrections.filter(c => c.revision_id === revision.id).map(c => <div key={c.id}><h4>{t("Correction")}{" "}{c.state === "RESOLVED" ? t("résolue") : t("demandée")}</h4>
            <p>{c.author} · {c.text}</p>
            {c.state === "OPEN" && report.capabilities.correct && <button disabled={busy} onClick={() => void run(async () => {
                            const draft = await createCorrectionDraft(report.id, revision, c.id, token);
                            router.push(`/collect?draft=${draft.id}`);
                        })}>{t("Préparer la nouvelle révision")}</button>}</div>)}
          {report.capabilities.request_correction && revision.id === report.current_revision_id &&
                    !report.corrections.some(c => c.revision_id === revision.id) &&
                    <WorkflowForm report={report} revision={revision} token={token} kind="correction-requests" refresh={refresh}/>}
        </article>)}
      </>}</section></div>
  </main>;
}
