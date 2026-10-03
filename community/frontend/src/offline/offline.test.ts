// @vitest-environment node
import "fake-indexeddb/auto";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import pilot from "../../../forms/pilot-form.json";
import type { FormVersion } from "../forms/types";
import { acceptReceipt, addAttachment, createDraft, duplicateDraft, OfflineDB, queueDraft, removeAttachment, saveDraft,
  type CachedForm, type Profile, type Receipt } from "./store";
import { syncOutbox } from "./sync";

let database: OfflineDB;
const profile: Profile = { id: "author", tenant_id: "tenant", display_name: "Author",
  verified_at: Date.now(), editable_until: Date.now() + 3600000 };
const cached: CachedForm = { key: "author:version", owner: profile.id,
  form: { id: "form", code: "pilot", name: "Pilot", territory_id: "area" },
  version: { ...pilot, id: "version", form_id: "form", version: 1, status: "PUBLISHED" } as FormVersion,
  sync_grant: "grant", grant_expires_at: new Date(Date.now() + 3600000).toISOString() };
beforeEach(() => { database = new OfflineDB("test-" + crypto.randomUUID()); });
afterEach(async () => { await database.delete(); });
const receipt = (id: string, operation: string): Receipt => ({ operation_id: operation, draft_id: id,
  server_version: 1, server_received_at: new Date().toISOString(), payload_hash: "a".repeat(64),
  validation: { valid: false, errors: [] } });

it("persists drafts and their exact form across a reopened database", async () => {
  const draft = await createDraft(profile, cached, database);
  await saveDraft(draft.id, 0, { needs_support: true }, profile, database);
  const name = database.name;
  database.close(); database = new OfflineDB(name);
  const stored = await database.drafts.get(draft.id);
  expect(stored?.answers).toEqual({ needs_support: true });
  expect(stored?.formVersion.id).toBe("version");
});

it("queues atomically, preserves operation ID and freezes in-flight payload", async () => {
  const draft = await createDraft(profile, cached, database);
  const queued = await queueDraft(draft.id, profile, database);
  expect((await queueDraft(draft.id, profile, database)).id).toBe(queued.id);
  await expect(saveDraft(draft.id, 0, {}, profile, database)).rejects.toThrow("accusé");
  await acceptReceipt(queued, receipt(draft.id, queued.id), database);
  expect((await database.drafts.get(draft.id))?.state).toBe("RECEIVED");
  expect(await database.outbox.count()).toBe(0);
});

it("keeps the payload after lost acknowledgments and replays the same operation", async () => {
  const draft = await createDraft(profile, cached, database);
  const queued = await queueDraft(draft.id, profile, database);
  const fetcher = vi.fn<typeof fetch>().mockRejectedValueOnce(new Error("Lost response"))
    .mockResolvedValueOnce(Response.json(receipt(draft.id, queued.id)));
  await syncOutbox(profile, "token", database, fetcher);
  expect((await database.drafts.get(draft.id))?.state).toBe("ERROR");
  expect(await database.outbox.count()).toBe(1);
  await syncOutbox(profile, "token", database, fetcher, true);
  expect(fetcher.mock.calls[0][1]?.body).toBe(fetcher.mock.calls[1][1]?.body);
  expect((await database.drafts.get(draft.id))?.state).toBe("RECEIVED");
});

it("preserves blocked and conflicted drafts, and requires explicit retry", async () => {
  const draft = await createDraft(profile, cached, database);
  await saveDraft(draft.id, 0, { executive_summary: "Local content" }, profile, database);
  await queueDraft(draft.id, profile, database);
  const fetcher = vi.fn<typeof fetch>().mockResolvedValue(Response.json(
    { detail: { code: "SYNC_PERMISSION_REVOKED" } }, { status: 403 }));
  await syncOutbox(profile, "token", database, fetcher);
  await syncOutbox(profile, "token", database, fetcher);
  expect(fetcher).toHaveBeenCalledTimes(1);
  const blocked = (await database.drafts.get(draft.id))!;
  expect(blocked.state).toBe("BLOCKED");
  expect(blocked.answers.executive_summary).toBe("Local content");
  fetcher.mockResolvedValue(Response.json({ detail: { code: "VERSION_CONFLICT" } }, { status: 409 }));
  await syncOutbox(profile, "token", database, fetcher, true);
  expect((await database.drafts.get(draft.id))?.state).toBe("CONFLICT");
  await database.forms.put(cached);
  const copy = await duplicateDraft(blocked, profile, database);
  expect(copy.id).not.toBe(draft.id);
  expect(copy.answers).toEqual(blocked.answers);
  expect(await database.outbox.count()).toBe(1);
});

it("persists attachment bytes, uploads them after the draft receipt, and copies them safely", async () => {
  await database.forms.put(cached);
  const draft = await createDraft(profile, cached, database);
  const content = new TextEncoder().encode("%PDF-1.4\nSynchroHQ\n%%EOF");
  const attached = await addAttachment(draft.id, 0,
    new File([content], "preuve.pdf", { type: "application/pdf" }), profile, database);
  const local = await database.attachments.where("draft_id").equals(draft.id).first();
  expect(local?.blob.size).toBe(content.byteLength);
  const queued = await queueDraft(draft.id, profile, database);
  const fetcher = vi.fn<typeof fetch>(async input => {
    if (String(input).includes("/attachments/")) {
      return Response.json({ attachment_id: local!.id, draft_id: draft.id,
        sha256: local!.sha256, size: local!.size, server_received_at: new Date().toISOString() });
    }
    return Response.json(receipt(draft.id, queued.id));
  });
  await syncOutbox(profile, "token", database, fetcher);
  expect(fetcher).toHaveBeenCalledTimes(2);
  expect((await database.attachments.get(local!.id))?.state).toBe("RECEIVED");

  const copy = await duplicateDraft(attached, profile, database);
  const copiedFiles = await database.attachments.where("draft_id").equals(copy.id).toArray();
  expect(copiedFiles).toHaveLength(1);
  expect(copiedFiles[0].id).not.toBe(local!.id);
  expect(copiedFiles[0].blob.size).toBe(content.byteLength);
});

it("does not overwrite concurrent local edits or delete data after session expiry", async () => {
  const draft = await createDraft(profile, cached, database);
  await saveDraft(draft.id, 0, { needs_support: true }, profile, database);
  await expect(saveDraft(draft.id, 0, {}, profile, database)).rejects.toThrow("autre onglet");
  await expect(saveDraft(draft.id, 1, {}, { ...profile, editable_until: 0 }, database)).rejects.toThrow("expirée");
  expect((await database.drafts.get(draft.id))?.answers).toEqual({ needs_support: true });
});

it("does not synchronize another local owner's queue and rejects mismatched receipts", async () => {
  const draft = await createDraft(profile, cached, database);
  const queued = await queueDraft(draft.id, profile, database);
  const fetcher = vi.fn<typeof fetch>();
  await syncOutbox({ ...profile, id: "other" }, "other-token", database, fetcher);
  expect(fetcher).not.toHaveBeenCalled();
  await expect(acceptReceipt(queued, receipt(draft.id, "wrong-id"), database)).rejects.toThrow("incohérent");
  expect(await database.outbox.count()).toBe(1);
});

it("requeues with a fresh grant only after an explicit grant rejection", async () => {
  const draft = await createDraft(profile, cached, database);
  const original = await queueDraft(draft.id, profile, database);
  await database.forms.put({ ...cached, sync_grant: "fresh-grant" });
  const fetcher = vi.fn<typeof fetch>().mockResolvedValue(Response.json(
    { detail: { code: "OFFLINE_GRANT_INVALID" } }, { status: 403 }));
  await syncOutbox(profile, "token", database, fetcher);
  const replacement = await database.outbox.where("draft_id").equals(draft.id).first();
  expect(replacement?.id).not.toBe(original.id);
  expect(replacement?.payload.sync_grant).toBe("fresh-grant");
  expect((await database.drafts.get(draft.id))?.state).toBe("QUEUED");
});

it("refuses attachment removal after expiry or from a different draft", async () => {
  const draft = await createDraft(profile, cached, database);
  const updated = await addAttachment(draft.id, 0,
    new File(["pdf"], "preuve.pdf", { type: "application/pdf" }), profile, database);
  const attachment = (await database.attachments.where("draft_id").equals(draft.id).first())!;
  const other = await createDraft(profile, cached, database);
  await expect(removeAttachment(draft.id, attachment.id, updated.revision,
    { ...profile, editable_until: 0 }, database)).rejects.toThrow("expirée");
  await expect(removeAttachment(other.id, attachment.id, 0, profile, database)).rejects.toThrow("inaccessible");
  expect(await database.attachments.count()).toBe(1);
});
