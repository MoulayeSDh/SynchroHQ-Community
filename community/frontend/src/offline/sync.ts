import { acceptReceipt, db, type AttachmentReceipt, type OfflineDB, type Profile,
  type Receipt } from "./store";

type Fetcher = typeof fetch;
export async function syncOutbox(profile: Profile, token: string, database: OfflineDB = db,
  fetcher: Fetcher = fetch, retryBlocked = false): Promise<void> {
  if (!token) return;
  const pending = await database.outbox.where("owner").equals(profile.id).toArray();
  for (const item of pending) {
    const draft = await database.drafts.get(item.draft_id);
    if (!draft || draft.owner !== profile.id || draft.tenant_id !== profile.tenant_id) continue;
    if (draft.state === "CONFLICT" || (!retryBlocked && draft.state === "BLOCKED")) continue;
    if (!retryBlocked && item.next_attempt > Date.now()) continue;
    await database.drafts.update(draft.id, { state: "SYNCING", error: undefined });
    try {
      const response = await fetcher("/api/sync-proxy/drafts", { method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify(item.payload), signal: AbortSignal.timeout(20000) });
      const result = await response.json();
      if (!response.ok) {
        const code = typeof result.detail?.code === "string" ? result.detail.code : `HTTP_${response.status}`;
        if (code === "OFFLINE_GRANT_INVALID") {
          const cached = await database.forms.get(profile.id + ":" + draft.formVersion.id);
          if (!draft.correction && cached && cached.sync_grant !== item.payload.sync_grant) {
            const replacementId = crypto.randomUUID();
            await database.transaction("rw", database.drafts, database.outbox, async () => {
              if (!await database.outbox.get(item.id)) return;
              await database.outbox.delete(item.id);
              await database.outbox.add({ ...item, id: replacementId,
                payload: { ...item.payload, operation_id: replacementId,
                  sync_grant: cached.sync_grant }, attempts: 0, next_attempt: 0 });
              await database.drafts.update(draft.id, { state: "QUEUED", error: undefined,
                sync_grant: cached.sync_grant, grant_expires_at: cached.grant_expires_at });
            });
            continue;
          }
        }
        if (response.status >= 500 || response.status === 429) throw new Error(code);
        const conflict = ["VERSION_CONFLICT", "OPERATION_ID_REUSED", "IDENTIFIER_CONFLICT", "FORM_VERSION_MISMATCH"].includes(code);
        await database.drafts.update(draft.id, { state: conflict ? "CONFLICT" : "BLOCKED", error: code });
        continue;
      }
      await acceptReceipt(item, result as Receipt, database);
    } catch (error) {
      await database.transaction("rw", database.drafts, database.outbox, async () => {
        // A successful sender in another tab must not be overwritten by this failed attempt.
        if (!await database.outbox.get(item.id)) return;
        await database.drafts.update(draft.id, { state: "ERROR", error: error instanceof Error ? error.message : "NETWORK_ERROR" });
        await database.outbox.update(item.id, { attempts: item.attempts + 1,
          next_attempt: Date.now() + Math.min(60000, 1000 * 2 ** Math.min(item.attempts, 6)) });
      });
    }
  }
  const attachments = await database.attachments.where("owner").equals(profile.id).toArray();
  for (const attachment of attachments) {
    if (attachment.state === "RECEIVED" || (!retryBlocked && attachment.state === "BLOCKED")) continue;
    const draft = await database.drafts.get(attachment.draft_id);
    if (!draft || draft.owner !== profile.id || draft.state !== "RECEIVED") continue;
    await database.attachments.update(attachment.id, { state: "SYNCING", error: undefined });
    try {
      const body = new FormData();
      body.set("file_name", attachment.file_name);
      body.set("mime_type", attachment.mime_type);
      body.set("size", String(attachment.size));
      body.set("sha256", attachment.sha256);
      body.set("file", attachment.blob, attachment.file_name);
      const response = await fetcher(
        `/api/sync-proxy/drafts/${draft.id}/attachments/${attachment.id}`,
        { method: "PUT", headers: { Authorization: `Bearer ${token}` }, body,
          signal: AbortSignal.timeout(30000) },
      );
      const result = await response.json();
      if (!response.ok) {
        const code = typeof result.detail?.code === "string" ? result.detail.code : `HTTP_${response.status}`;
        if (response.status >= 500 || response.status === 429) throw new Error(code);
        await database.attachments.update(attachment.id, { state: "BLOCKED", error: code });
        continue;
      }
      const receipt = result as AttachmentReceipt;
      if (receipt.attachment_id !== attachment.id || receipt.draft_id !== draft.id ||
          receipt.sha256 !== attachment.sha256 || receipt.size !== attachment.size)
        throw new Error("Accusé de pièce jointe incohérent.");
      await database.attachments.update(attachment.id, { state: "RECEIVED", receipt,
        error: undefined });
    } catch (error) {
      await database.attachments.update(attachment.id, { state: "ERROR",
        error: error instanceof Error ? error.message : "NETWORK_ERROR" });
    }
  }
}
