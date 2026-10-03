import Dexie, { type Table } from "dexie";
import type { Answers, FormRecord, FormVersion, ValidationResult } from "../forms/types";
import type { InboxEntry } from "./inbox";
import type { LocalReport, ReportContext } from "./reports";
import { initialAnswers } from "../forms/validation";

export type SyncState = "LOCAL" | "QUEUED" | "SYNCING" | "RECEIVED" | "ERROR" | "BLOCKED" | "CONFLICT";
export interface Profile { id: string; tenant_id: string; display_name: string; verified_at: number; editable_until: number }
export interface CachedForm {
  key: string; owner: string; form: FormRecord; version: FormVersion;
  sync_grant: string; grant_expires_at: string; report_context?: ReportContext;
}
export interface Draft {
  id: string; owner: string; tenant_id: string; device_id: string;
  form: FormRecord; formVersion: FormVersion; answers: Answers;
  sync_grant: string; grant_expires_at: string;
  revision: number; server_version: number; created_at: string; updated_at: string;
  business_state?: "DRAFT" | "FINALIZED" | "CONFIRMED"; finalized_at?: string;
  report_id?: string; report_revision_id?: string; report_context?: ReportContext;
  report_revision_number?: number; expected_report_id?: string;
  correction?: { base_revision_id: string; correction_request_id: string };
  state: SyncState; error?: string; receipt?: Receipt;
}
export interface Operation {
  operation_id: string; draft_id: string; device_id: string; form_version_id: string;
  base_version: number; client_updated_at: string; answers: Answers;
  sync_grant: string;
}
export interface Pending { id: string; owner: string; draft_id: string; payload: Operation; attempts: number; next_attempt: number }
export interface Receipt {
  operation_id: string; draft_id: string; server_version: number;
  server_received_at: string; payload_hash: string; validation: ValidationResult;
}
export type AttachmentState = "LOCAL" | "SYNCING" | "RECEIVED" | "ERROR" | "BLOCKED";
export interface AttachmentReceipt {
  attachment_id: string; draft_id: string; sha256: string; size: number;
  server_received_at: string;
}
export interface LocalAttachment {
  id: string; owner: string; draft_id: string; file_name: string; mime_type: string;
  size: number; sha256: string; blob: Blob; state: AttachmentState; error?: string;
  receipt?: AttachmentReceipt;
}
export class OfflineDB extends Dexie {
  profiles!: Table<Profile, string>;
  forms!: Table<CachedForm, string>;
  drafts!: Table<Draft, string>;
  outbox!: Table<Pending, string>;
  attachments!: Table<LocalAttachment, string>;
  reports!: Table<LocalReport, string>;
  inbox!: Table<InboxEntry, string>;
  settings!: Table<{ key: string; value: string }, string>;
  constructor(name = "synchrohq-offline-v1") {
    super(name);
    this.version(1).stores({ profiles: "id", forms: "key, owner", drafts: "id, owner, state",
      outbox: "id, owner, &draft_id", settings: "key" });
    this.version(2).stores({ profiles: "id", forms: "key, owner", drafts: "id, owner, state",
      outbox: "id, owner, &draft_id", attachments: "id, owner, draft_id, state", settings: "key" });
    this.version(3).stores({ profiles: "id", forms: "key, owner", drafts: "id, owner, state",
      outbox: "id, owner, &draft_id", attachments: "id, owner, draft_id, state", settings: "key",
      reports: "id, owner, &draft_id, state" });
    this.version(4).stores({ reports: "id, report_id, owner, &draft_id, state" }).upgrade(async transaction => {
      const reports = transaction.table("reports");
      const existing = await reports.toArray();
      await reports.clear();
      await reports.bulkPut(existing.map(report => ({ ...report, id: report.revision_id, report_id: report.report_id ?? report.id })));
    });
    this.version(5).stores({ inbox: "key, owner" });
  }
}
export const db = new OfflineDB();
export async function deviceId(database = db): Promise<string> {
  return database.transaction("rw", database.settings, async () => {
    const value = await database.settings.get("device");
    if (value) return value.value;
    const id = crypto.randomUUID();
    await database.settings.put({ key: "device", value: id });
    return id;
  });
}
export function canEdit(profile: Profile): boolean { return Date.now() <= profile.editable_until; }
export async function createDraft(profile: Profile, cached: CachedForm, database = db): Promise<Draft> {
  if (!canEdit(profile)) throw new Error("Réauthentification requise pour créer un brouillon.");
  if (profile.id !== cached.owner || cached.version.status !== "PUBLISHED") throw new Error("Formulaire indisponible.");
  const now = new Date().toISOString();
  const draft: Draft = { id: crypto.randomUUID(), owner: profile.id, tenant_id: profile.tenant_id,
    device_id: await deviceId(database), form: cached.form, formVersion: cached.version,
    sync_grant: cached.sync_grant, grant_expires_at: cached.grant_expires_at,
    business_state: "DRAFT", report_id: crypto.randomUUID(), report_revision_id: crypto.randomUUID(),
    report_context: cached.report_context, answers: initialAnswers(cached.version.data_schema), revision: 0, server_version: 0,
    created_at: now, updated_at: now, state: "LOCAL" };
  await database.drafts.add(draft);
  return draft;
}
export async function saveDraft(id: string, expectedRevision: number, answers: Answers, profile: Profile, database = db): Promise<Draft> {
  if (!canEdit(profile)) throw new Error("Session locale expirée. Les réponses restent visibles et exportables.");
  return database.transaction("rw", database.drafts, database.outbox, async () => {
    const draft = await database.drafts.get(id);
    if (!draft || draft.owner !== profile.id) throw new Error("Brouillon inaccessible.");
    if (draft.business_state === "CONFIRMED" || draft.business_state === "FINALIZED") throw new Error("Rapport figé. Revenez au brouillon avant de modifier.");
    if (draft.revision !== expectedRevision) throw new Error("Ce brouillon a changé dans un autre onglet. Exportez vos réponses avant de le rouvrir.");
    if (await database.outbox.where("draft_id").equals(id).count()) throw new Error("Une opération attend son accusé. Dupliquez le brouillon pour continuer.");
    const updated: Draft = { ...draft, answers, revision: draft.revision + 1, updated_at: new Date().toISOString(), state: "LOCAL", error: undefined };
    await database.drafts.put(updated);
    return updated;
  });
}
export async function queueDraft(id: string, profile: Profile, database = db): Promise<Pending> {
  if (!canEdit(profile)) throw new Error("Réauthentification requise.");
  return database.transaction("rw", database.drafts, database.outbox, async () => {
    const draft = await database.drafts.get(id);
    if (!draft || draft.owner !== profile.id) throw new Error("Brouillon inaccessible.");
    const previous = await database.outbox.where("draft_id").equals(id).first();
    if (previous) return previous;
    const idOperation = crypto.randomUUID();
    const pending: Pending = { id: idOperation, owner: profile.id, draft_id: id, attempts: 0, next_attempt: 0,
      payload: { operation_id: idOperation, draft_id: id, device_id: draft.device_id,
        form_version_id: draft.formVersion.id, base_version: draft.server_version,
        client_updated_at: draft.updated_at, answers: structuredClone(draft.answers),
        sync_grant: draft.sync_grant } };
    await database.outbox.add(pending);
    await database.drafts.update(id, { state: "QUEUED", error: undefined });
    return pending;
  });
}
export async function duplicateDraft(draft: Draft, profile: Profile, database = db): Promise<Draft> {
  const cached = await database.forms.get(profile.id + ":" + draft.formVersion.id);
  if (!cached) throw new Error("Cette version n’est plus disponible pour un nouveau brouillon.");
  let copy = await createDraft(profile, cached, database);
  const answers = structuredClone(draft.answers);
  delete answers.attachments;
  copy = await saveDraft(copy.id, copy.revision, answers, profile, database);
  const attachments = await database.attachments.where("draft_id").equals(draft.id).toArray();
  for (const attachment of attachments) {
    const file = new File([attachment.blob], attachment.file_name, { type: attachment.mime_type });
    copy = await addAttachment(copy.id, copy.revision, file, profile, database);
  }
  return copy;
}
export async function acceptReceipt(pending: Pending, receipt: Receipt, database = db): Promise<void> {
  if (receipt.operation_id !== pending.id || receipt.draft_id !== pending.draft_id ||
      receipt.server_version !== pending.payload.base_version + 1 || !receipt.server_received_at ||
      !/^[a-f0-9]{64}$/.test(receipt.payload_hash)) throw new Error("Accusé serveur incohérent.");
  await database.transaction("rw", database.drafts, database.outbox, async () => {
    const operation = await database.outbox.get(pending.id);
    if (!operation) return; // Another tab already committed the same receipt.
    await database.drafts.update(pending.draft_id, { state: "RECEIVED", receipt,
      server_version: receipt.server_version, error: undefined });
    await database.outbox.delete(pending.id);
  });
}

function hex(buffer: ArrayBuffer): string {
  return [...new Uint8Array(buffer)].map(value => value.toString(16).padStart(2, "0")).join("");
}

export async function addAttachment(
  draftId: string, expectedRevision: number, file: File, profile: Profile, database = db,
): Promise<Draft> {
  if (!canEdit(profile)) throw new Error("Réauthentification requise.");
  if (!file.size || file.size > 10485760) throw new Error("Le fichier doit faire entre 1 octet et 10 Mio.");
  if (!["image/jpeg", "image/png", "application/pdf"].includes(file.type))
    throw new Error("Format accepté : JPEG, PNG ou PDF.");
  if (file.name.length > 255) throw new Error("Le nom du fichier est trop long.");
  const id = crypto.randomUUID();
  const sha256 = hex(await crypto.subtle.digest("SHA-256", await file.arrayBuffer()));
  return database.transaction("rw", database.drafts, database.outbox, database.attachments, async () => {
    const draft = await database.drafts.get(draftId);
    if (!draft || draft.owner !== profile.id) throw new Error("Brouillon inaccessible.");
    if (draft.business_state === "CONFIRMED" || draft.business_state === "FINALIZED") throw new Error("Rapport figé. Revenez au brouillon avant de modifier.");
    if (draft.revision !== expectedRevision) throw new Error("Ce brouillon a changé dans un autre onglet.");
    if (await database.outbox.where("draft_id").equals(draftId).count())
      throw new Error("Une opération attend son accusé. Dupliquez le brouillon pour continuer.");
    const metadata = { attachment_id: id, file_name: file.name, mime_type: file.type,
      size: file.size, sha256 };
    const existing = Array.isArray(draft.answers.attachments) ? draft.answers.attachments : [];
    const updated: Draft = { ...draft, answers: { ...draft.answers,
      attachments: [...existing, metadata] }, revision: draft.revision + 1,
      updated_at: new Date().toISOString(), state: "LOCAL", error: undefined };
    await database.attachments.add({ id, owner: profile.id, draft_id: draftId,
      file_name: file.name, mime_type: file.type, size: file.size, sha256,
      blob: file, state: "LOCAL" });
    await database.drafts.put(updated);
    return updated;
  });
}

export async function removeAttachment(
  draftId: string, attachmentId: string, expectedRevision: number, profile: Profile, database = db,
): Promise<Draft> {
  if (!canEdit(profile)) throw new Error("Session locale expirée.");
  return database.transaction("rw", database.drafts, database.outbox, database.attachments, async () => {
    const draft = await database.drafts.get(draftId);
    const attachment = await database.attachments.get(attachmentId);
    if (!draft || !attachment || draft.owner !== profile.id || attachment.owner !== profile.id || attachment.draft_id !== draftId)
      throw new Error("Pièce jointe inaccessible.");
    if (draft.business_state === "CONFIRMED" || draft.business_state === "FINALIZED") throw new Error("Rapport figé.");
    if (draft.revision !== expectedRevision || await database.outbox.where("draft_id").equals(draftId).count())
      throw new Error("Le brouillon a changé ou attend un accusé.");
    if (attachment.state === "RECEIVED" || attachment.state === "SYNCING") throw new Error("Une pièce déjà reçue ne peut pas être retirée du brouillon.");
    const existing = Array.isArray(draft.answers.attachments) ? draft.answers.attachments : [];
    const updated: Draft = { ...draft, answers: { ...draft.answers,
      attachments: existing.filter(item => typeof item !== "object" || item === null ||
        !("attachment_id" in item) || item.attachment_id !== attachmentId) },
      revision: draft.revision + 1, updated_at: new Date().toISOString(), state: "LOCAL" };
    await database.attachments.delete(attachmentId);
    await database.drafts.put(updated);
    return updated;
  });
}
