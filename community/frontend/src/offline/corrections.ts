import type { Answers } from "../forms/types";
import type { ReportContext } from "./reports";
import { pullInbox, type CorrectionBundle } from "./inbox";
import { canEdit, db, deviceId, type Draft, type LocalAttachment, type OfflineDB, type Profile } from "./store";

export interface OfficialRevision {
  form_definition?: import("../forms/types").Envelope;
  id: string; number: number; state: string; payload_hash: string;
  payload: { snapshot: ReportContext["snapshot"]; answers: Answers; confirmed_at: string; expected_report_id?: string;
    attachments: { attachment_id: string; file_name: string; mime_type: string; size: number; sha256: string }[] };
}

export async function createCorrectionFromBundle(bundle: CorrectionBundle, profile: Profile, database: OfflineDB = db): Promise<Draft> {
  const context = bundle.context;
  if (!canEdit(profile) || Date.now() >= Date.parse(context.expires_at)) throw new Error("Session de correction expirée. Les demandes restent conservées.");
  if (!context.sync_grant || context.snapshot.author.id !== profile.id || context.snapshot.tenant_id !== profile.tenant_id ||
      context.correction?.report_id !== bundle.report_id || context.correction.base_revision_id !== bundle.revision.id ||
      context.correction.correction_request_id !== bundle.request_id || context.correction.revision_number !== bundle.revision.number + 1)
    throw new Error("Contexte de correction incohérent.");
  const id = crypto.randomUUID();
  const files: LocalAttachment[] = [];
  if (bundle.files.length !== bundle.revision.payload.attachments.length) throw new Error("Pièces jointes non préparées.");
  for (const [index, file] of bundle.files.entries()) {
    const original = bundle.revision.payload.attachments[index];
    const hash = [...new Uint8Array(await crypto.subtle.digest("SHA-256", await file.blob.arrayBuffer()))].map(b => b.toString(16).padStart(2, "0")).join("");
    if (hash !== original.sha256 || file.blob.size !== original.size) throw new Error("Pièce jointe locale altérée.");
    files.push({ ...file, id: crypto.randomUUID(), owner: profile.id, draft_id: id, state: "LOCAL" });
  }
  const answers = structuredClone(bundle.revision.payload.answers);
  if (files.length || "attachments" in answers) answers.attachments = files.map(file => ({ attachment_id: file.id,
    file_name: file.file_name, mime_type: file.mime_type, size: file.size, sha256: file.sha256 }));
  const now = new Date().toISOString();
  const draft: Draft = { id, owner: profile.id, tenant_id: profile.tenant_id, device_id: await deviceId(database), form: bundle.form,
    formVersion: bundle.version, answers, sync_grant: context.sync_grant, grant_expires_at: context.expires_at,
    revision: 0, server_version: 0, created_at: now, updated_at: now, business_state: "DRAFT", state: "LOCAL",
    report_id: bundle.report_id, report_revision_id: crypto.randomUUID(), report_revision_number: context.correction.revision_number,
    expected_report_id: context.expected_report_id, report_context: context,
    correction: { base_revision_id: bundle.revision.id, correction_request_id: bundle.request_id } };
  return database.transaction("rw", database.drafts, database.attachments, async () => {
    const existing = (await database.drafts.where("owner").equals(profile.id).toArray()).find(d =>
      d.correction?.correction_request_id === bundle.request_id && d.business_state !== "CONFIRMED");
    if (existing) return existing;
    await database.drafts.add(draft); await database.attachments.bulkAdd(files); return draft;
  });
}

export async function createCorrectionDraft(reportId: string, revision: OfficialRevision, requestId: string, token: string): Promise<Draft> {
  let profile: Profile | undefined;
  if (navigator.onLine) {
    const response = await fetch("/api/sync-proxy/me", { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" });
    if (!response.ok) throw new Error("Préparation de la session refusée.");
    const user = await response.json();
    profile = { id: user.id, tenant_id: user.tenant_id, display_name: user.display_name, verified_at: Date.now(),
      editable_until: Date.now() + user.offline_edit_seconds * 1000 };
    await db.profiles.put(profile); await db.settings.put({ key: "last-profile", value: profile.id });
    const verified = profile;
    if (navigator.locks) await navigator.locks.request("synchrohq-sync", () => pullInbox(verified, token));
    else await pullInbox(verified, token);
  } else {
    const last = await db.settings.get("last-profile");
    profile = last ? await db.profiles.get(last.value) : undefined;
  }
  if (!profile) throw new Error("Préparez votre session en ligne avant de corriger.");
  const entry = await db.inbox.get(`${profile.id}:${reportId}`);
  const bundle = entry?.bundles.find(b => b.request_id === requestId && b.revision.id === revision.id);
  if (!bundle) throw new Error(entry?.preparation_error ?? "Cette correction n’a pas été préparée sur cet appareil.");
  return createCorrectionFromBundle(bundle, profile);
}
