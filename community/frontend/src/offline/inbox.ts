import type { FormRecord, FormVersion } from "../forms/types";
import { prepareOfflineShell } from "./shell";
import { db, type OfflineDB, type Profile } from "./store";
import type { OfficialRevision } from "./corrections";
import type { ReportContext } from "./reports";

export interface Note { id: string; revision_id: string; author: string; text: string; created_at: string; state?: string }
export interface InboxReport { id: string; current_revision_id: string; viewer_id: string; author_id: string; territory_id: string; territory_name: string; form_id: string; form_name: string; period: string; period_end?: string;
  revisions: OfficialRevision[]; comments: Note[]; corrections: Note[]; workflow_state: string;
  capabilities: { review?: boolean; comment: boolean; request_correction: boolean; correct: boolean } }
export interface CorrectionBundle { report_id: string; request_id: string; revision: OfficialRevision; context: ReportContext;
  form: FormRecord; version: FormVersion; files: { file_name: string; mime_type: string; size: number; sha256: string; blob: Blob }[] }
export interface InboxEntry { key: string; owner: string; tenant_id: string; report: InboxReport; pulled_at: number;
  bundles: CorrectionBundle[]; preparation_error?: string }

export async function pullInbox(profile: Profile, token: string, database: OfflineDB = db, fetcher: typeof fetch = fetch): Promise<void> {
  async function request(path: string, method = "GET") {
    const response = await fetcher(path, { method, headers: { Authorization: `Bearer ${token}` }, cache: "no-store", signal: AbortSignal.timeout(30000) });
    if (!response.ok) throw new Error(`Récupération des demandes interrompue (${response.status}). Les données locales restent conservées.`);
    return response;
  }
  const me: { id: string; tenant_id: string } = await (await request("/api/sync-proxy/me")).json();
  if (me.id !== profile.id || me.tenant_id !== profile.tenant_id) throw new Error("Identité incohérente pour l’inbox.");
  const reports: InboxReport[] = [];
  for (let offset = 0; ; offset += 100) {
    const page: InboxReport[] = await (await request(`/api/reports-proxy/workflow/inbox?own=true&offset=${offset}&limit=100`)).json();
    reports.push(...page); if (page.length < 100) break;
  }
  const entries: InboxEntry[] = [];
  for (const report of reports) {
    if (report.viewer_id !== profile.id || report.author_id !== profile.id) throw new Error("Inbox hors périmètre.");
    const entry: InboxEntry = { key: `${profile.id}:${report.id}`, owner: profile.id, tenant_id: profile.tenant_id,
      report, pulled_at: Date.now(), bundles: [] };
    if (report.capabilities.correct) {
      const revision = report.revisions.find(r => r.id === report.current_revision_id)!;
      for (const note of report.corrections.filter(c => c.state === "OPEN" && c.revision_id === revision.id)) {
        try {
          const context: ReportContext = await (await request(`/api/reports-proxy/contexts/${revision.payload.snapshot.form_version_id}?correction_request_id=${note.id}`, "POST")).json();
          if (context.snapshot.author.id !== profile.id || context.snapshot.tenant_id !== profile.tenant_id ||
              context.correction?.report_id !== report.id || context.correction.base_revision_id !== revision.id ||
              context.correction.correction_request_id !== note.id || !context.sync_grant)
            throw new Error("Contexte de correction incohérent.");
          const form: FormRecord = await (await request(`/api/forms-proxy/${context.snapshot.form_id}`)).json();
          const versions: FormVersion[] = await (await request(`/api/forms-proxy/${form.id}/versions`)).json();
          const version = versions.find(v => v.id === context.snapshot.form_version_id);
          if (!version) throw new Error("Version d’origine indisponible.");
          const cached = (await database.inbox.get(`${profile.id}:${report.id}`))?.bundles.find(b => b.request_id === note.id && b.revision.payload_hash === revision.payload_hash);
          const files: CorrectionBundle["files"] = [];
          for (const [index, file] of revision.payload.attachments.entries()) {
            const blob = cached?.files[index]?.blob ?? await (await request(`/api/reports-proxy/${report.id}/attachments/${file.attachment_id}?revision_id=${revision.id}`)).blob();
            const hash = [...new Uint8Array(await crypto.subtle.digest("SHA-256", await blob.arrayBuffer()))].map(b => b.toString(16).padStart(2, "0")).join("");
            if (hash !== file.sha256 || blob.size !== file.size) throw new Error("Intégrité de pièce jointe incorrecte.");
            files.push({ file_name: file.file_name, mime_type: file.mime_type, size: file.size, sha256: file.sha256, blob });
          }
          entry.bundles.push({ report_id: report.id, request_id: note.id, revision, context, form, version, files });
        } catch (e) { entry.preparation_error = e instanceof Error ? e.message : "Préparation interrompue."; }
      }
    }
    entries.push(entry);
  }
  // Replace only after a complete authorized snapshot, removing resources whose access was revoked.
  await database.transaction("rw", database.inbox, async () => {
    await database.inbox.where("owner").equals(profile.id).delete();
    await database.inbox.bulkPut(entries);
  });
  await prepareOfflineShell();
}
