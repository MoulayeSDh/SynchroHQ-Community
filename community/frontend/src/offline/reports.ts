import { validateAnswers } from "../forms/validation";
import { canEdit, db, type OfflineDB, type Profile, type SyncState } from "./store";

export interface ReportContext {
  snapshot: {
    tenant_id: string;
    author: { id: string; display_name: string };
    organization: { id: string; name: string; code: string; type_code: string };
    assignment: { id: string; role_id: string; role_code: string; clearance_level: number;
      scopes: { territory_id: string; coverage: string }[] };
    form_id: string; form_version_id: string; form_version: number;
    territory_id: string; required_clearance: number; auth_method: string;
  };
  context_token: string; issued_at: string; expires_at: string;
  sync_grant?: string; expected_report_id?: string;
  correction?: { report_id: string; base_revision_id: string; correction_request_id: string; revision_number: number };
}
export interface ReportReceipt {
  operation_id: string; report_id: string; revision_id: string;
  payload_hash: string; server_received_at: string;
}
export interface LocalReport {
  id: string; report_id: string; revision_id: string; owner: string; tenant_id: string; draft_id: string;
  operation_id: string; canonical_payload: string; payload_hash: string; context_token: string;
  confirmed_at: string; state: SyncState; attempts: number; next_attempt: number;
  error?: string; receipt?: ReportReceipt;
}

// RFC 8785: ECMAScript number/string serialization and UTF-16 property ordering.
// Reject values that JSON would silently discard or replace.
export function canonicalJson(value: unknown): string {
  if (typeof value === "string") {
    for (let index = 0; index < value.length; index++) {
      const code = value.charCodeAt(index);
      if (code >= 0xD800 && code <= 0xDBFF) {
        const next = value.charCodeAt(++index);
        if (!(next >= 0xDC00 && next <= 0xDFFF)) throw new Error("Texte Unicode non canonique.");
      } else if (code >= 0xDC00 && code <= 0xDFFF) throw new Error("Texte Unicode non canonique.");
    }
    return JSON.stringify(value);
  }
  if (value === null || typeof value === "boolean") return JSON.stringify(value);
  if (typeof value === "number") {
    if (!Number.isFinite(value) || (Number.isInteger(value) && !Number.isSafeInteger(value))) throw new Error("Nombre non canonique.");
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) return "[" + value.map(canonicalJson).join(",") + "]";
  if (typeof value === "object") {
    const record = value as Record<string, unknown>;
    return "{" + Object.keys(record).sort().map(key => canonicalJson(key) + ":" + canonicalJson(record[key])).join(",") + "}";
  }
  throw new Error("Valeur non canonique.");
}

export async function finalizeReport(draftId: string, revision: number, profile: Profile, database = db): Promise<void> {
  if (!canEdit(profile)) throw new Error("Réauthentification requise pour finaliser.");
  await database.transaction("rw", database.drafts, database.forms, database.outbox, async () => {
    const draft = await database.drafts.get(draftId);
    if (!draft || draft.owner !== profile.id || draft.tenant_id !== profile.tenant_id) throw new Error("Brouillon inaccessible.");
    if (draft.business_state === "CONFIRMED") throw new Error("Ce rapport est déjà confirmé.");
    if (draft.revision !== revision || await database.outbox.where("draft_id").equals(draftId).count())
      throw new Error("Attendez la sauvegarde ou l’accusé du brouillon avant de finaliser.");
    const validation = validateAnswers(draft.formVersion.data_schema, draft.answers);
    if (!validation.valid) throw new Error("Réponses à corriger : " + validation.errors.map(e => e.path).join(", "));
    const cached = await database.forms.get(profile.id + ":" + draft.formVersion.id);
    const context = draft.correction || draft.expected_report_id ? draft.report_context : cached?.report_context ?? draft.report_context;
    if (!context || Date.now() > Date.parse(context.expires_at))
      throw new Error("Préparez votre session en ligne pour obtenir les droits de confirmation.");
    await database.drafts.update(draftId, { business_state: "FINALIZED", finalized_at: new Date().toISOString(),
      report_id: draft.report_id ?? crypto.randomUUID(), report_revision_id: draft.report_revision_id ?? crypto.randomUUID(),
      report_context: context });
  });
}

export async function reopenReport(draftId: string, profile: Profile, database = db): Promise<void> {
  if (!canEdit(profile)) throw new Error("Réauthentification requise.");
  await database.transaction("rw", database.drafts, async () => {
    const draft = await database.drafts.get(draftId);
    if (!draft || draft.owner !== profile.id) throw new Error("Brouillon inaccessible.");
    if (draft.business_state !== "FINALIZED") throw new Error("Seul un rapport finalisé peut revenir en brouillon.");
    await database.drafts.update(draftId, { business_state: "DRAFT", finalized_at: undefined });
  });
}

export async function confirmReport(draftId: string, profile: Profile, database = db): Promise<void> {
  if (!canEdit(profile)) throw new Error("Réauthentification requise pour confirmer.");
  const draft = await database.drafts.get(draftId);
  if (!draft || draft.owner !== profile.id || draft.tenant_id !== profile.tenant_id) throw new Error("Brouillon inaccessible.");
  const context = draft.report_context;
  if (draft.business_state !== "FINALIZED" || !context || !draft.finalized_at || !draft.report_id || !draft.report_revision_id)
    throw new Error("Finalisez les réponses avant la confirmation.");
  if (Date.now() > Date.parse(context.expires_at) || context.snapshot.author.id !== profile.id ||
      context.snapshot.tenant_id !== profile.tenant_id || context.snapshot.form_version_id !== draft.formVersion.id)
    throw new Error("Contexte de confirmation expiré ou incohérent. Préparez votre session puis finalisez à nouveau.");
  const files = await database.attachments.where("draft_id").equals(draftId).toArray();
  const metadata = draft.answers.attachments ?? [];
  if (!Array.isArray(metadata) || metadata.length !== files.length || files.some(file =>
    !metadata.some(item => typeof item === "object" && item !== null && "attachment_id" in item &&
      canonicalJson(item) === canonicalJson({ attachment_id: file.id, file_name: file.file_name,
        mime_type: file.mime_type, size: file.size, sha256: file.sha256 }))))
    throw new Error("Les pièces jointes ne correspondent pas aux fichiers locaux.");
  const confirmedAt = new Date().toISOString();
  const canonical = canonicalJson({ schema_version: "synchrohq.report/v1", report_id: draft.report_id,
    revision_id: draft.report_revision_id, revision_number: draft.report_revision_number ?? 1,
    ...(draft.correction ? { correction: draft.correction } : {}),
    ...(draft.expected_report_id ? { expected_report_id: draft.expected_report_id } : {}), draft_id: draft.id, device_id: draft.device_id,
    snapshot: context.snapshot, answers: draft.answers, attachments: metadata,
    created_at: draft.created_at, finalized_at: draft.finalized_at, confirmed_at: confirmedAt });
  const hash = [...new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(canonical)))].map(b => b.toString(16).padStart(2, "0")).join("");
  await database.transaction("rw", database.drafts, database.reports, database.outbox, database.attachments, async () => {
    const current = await database.drafts.get(draftId);
    if (!current || current.business_state !== "FINALIZED" || current.revision !== draft.revision ||
        current.finalized_at !== draft.finalized_at || canonicalJson(current.answers) !== canonicalJson(draft.answers))
      throw new Error("Le brouillon a changé pendant la confirmation.");
    await database.reports.add({ id: draft.report_revision_id!, report_id: draft.report_id!, revision_id: draft.report_revision_id!,
      owner: profile.id, tenant_id: profile.tenant_id, draft_id: draftId,
      operation_id: crypto.randomUUID(), canonical_payload: canonical, payload_hash: hash,
      context_token: context.context_token, confirmed_at: confirmedAt, state: "QUEUED", attempts: 0, next_attempt: 0 });
    await database.drafts.update(draftId, { business_state: "CONFIRMED" });
    // Phase 4 transports the exact source and files before the official confirmation.
    if (current.state !== "RECEIVED" && !await database.outbox.where("draft_id").equals(draftId).count()) {
      const operationId = crypto.randomUUID();
      await database.outbox.add({ id: operationId, owner: profile.id, draft_id: draftId, attempts: 0, next_attempt: 0,
        payload: { operation_id: operationId, draft_id: draftId, device_id: draft.device_id,
          form_version_id: draft.formVersion.id, base_version: draft.server_version,
          client_updated_at: draft.updated_at, answers: draft.answers, sync_grant: draft.sync_grant } });
      await database.drafts.update(draftId, { state: "QUEUED" });
    }
  });
}

export async function syncReports(profile: Profile, token: string, database: OfflineDB = db,
  fetcher: typeof fetch = fetch, retry = false): Promise<void> {
  if (!token) return;
  const reports = await database.reports.where("owner").equals(profile.id).toArray();
  for (const report of reports) {
    if (report.tenant_id !== profile.tenant_id || report.state === "RECEIVED" ||
        (!retry && (report.state === "BLOCKED" || report.next_attempt > Date.now()))) continue;
    const draft = await database.drafts.get(report.draft_id);
    if (!draft || draft.state !== "RECEIVED") continue;
    const files = await database.attachments.where("draft_id").equals(report.draft_id).toArray();
    if (files.some(f => f.state !== "RECEIVED")) continue;
    const shouldSend = await database.transaction("rw", database.reports, async () => {
      if ((await database.reports.get(report.id))?.state === "RECEIVED") return false;
      await database.reports.update(report.id, { state: "SYNCING", error: undefined });
      return true;
    });
    if (!shouldSend) continue;
    try {
      const response = await fetcher("/api/reports-proxy/confirmations", { method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ operation_id: report.operation_id, canonical_payload: report.canonical_payload,
          payload_hash: report.payload_hash, context_token: report.context_token }), signal: AbortSignal.timeout(30000) });
      const result = await response.json();
      if (!response.ok) {
        const code = result.detail?.code ?? `HTTP_${response.status}`;
        if (response.status >= 500 || response.status === 429) throw new Error(code);
        await database.transaction("rw", database.reports, async () => {
          if ((await database.reports.get(report.id))?.state === "RECEIVED") return;
          await database.reports.update(report.id, { state: "BLOCKED", error: code });
        });
        continue;
      }
      const receipt = result as ReportReceipt;
      if (receipt.operation_id !== report.operation_id || receipt.report_id !== report.report_id ||
          receipt.revision_id !== report.revision_id || receipt.payload_hash !== report.payload_hash || !receipt.server_received_at)
        throw new Error("Accusé de rapport incohérent.");
      await database.reports.update(report.id, { state: "RECEIVED", receipt, error: undefined });
    } catch (error) {
      await database.transaction("rw", database.reports, async () => {
        // A lost response in another tab must not erase a persistent acknowledgement.
        if ((await database.reports.get(report.id))?.state === "RECEIVED") return;
        await database.reports.update(report.id, { state: "ERROR", error: error instanceof Error ? error.message : "NETWORK_ERROR",
          attempts: report.attempts + 1, next_attempt: Date.now() + Math.min(60000, 1000 * 2 ** Math.min(report.attempts, 6)) });
      });
    }
  }
}
