// @vitest-environment node
import "fake-indexeddb/auto";
import Dexie from "dexie";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import pilot from "../../../forms/pilot-form.json";
import cases from "../../../forms/validation-cases.json";
import { addAttachment, createDraft, OfflineDB, removeAttachment, saveDraft,
  type CachedForm, type Profile, type Receipt } from "./store";
import { canonicalJson, confirmReport, finalizeReport, reopenReport, syncReports, type ReportContext } from "./reports";
import { syncOutbox } from "./sync";

let database: OfflineDB;
const profile: Profile = { id: "author", tenant_id: "tenant", display_name: "Author",
  verified_at: Date.now(), editable_until: Date.now() + 3600000 };
const context: ReportContext = { snapshot: { tenant_id: "tenant", author: { id: "author", display_name: "Author" },
  organization: { id: "org", name: "Org", code: "ORG", type_code: "COMMUNE" },
  assignment: { id: "assignment", role_id: "role", role_code: "AUTHOR", clearance_level: 1, scopes: [] },
  form_id: "form", form_version_id: "version", form_version: 1, territory_id: "territory", required_clearance: 1,
  auth_method: "community-jwt" }, context_token: "signed-context", issued_at: new Date().toISOString(),
  expires_at: new Date(Date.now() + 3600000).toISOString() };
const cached: CachedForm = { key: "author:version", owner: "author", form: { id: "form", code: "pilot", name: "Pilot", territory_id: "territory" },
  version: { ...pilot, schema_version: "synchrohq.form/v1", id: "version", form_id: "form", version: 1, status: "PUBLISHED" },
  sync_grant: "grant", grant_expires_at: context.expires_at, report_context: context } as CachedForm;
beforeEach(() => { database = new OfflineDB("reports-test-" + crypto.randomUUID()); });
afterEach(async () => { await database.delete(); });

it("canonicalizes Unicode and numbers deterministically", () => {
  expect(canonicalJson({ z: -0, a: "العربية", nested: { y: 0.1, b: true } })).toBe('{"a":"العربية","nested":{"b":true,"y":0.1},"z":0}');
  expect(() => canonicalJson({ number: Infinity })).toThrow("canonique");
  expect(() => canonicalJson(1e20)).toThrow("canonique");
  expect(() => canonicalJson("\uD800")).toThrow("canonique");
  expect(canonicalJson("😀")).toBe('"😀"');
});

it("requires valid finalization and freezes local data even after reopening IndexedDB", async () => {
  const draft = await createDraft(profile, cached, database);
  await expect(finalizeReport(draft.id, 0, profile, database)).rejects.toThrow("corriger");
  const valid = await saveDraft(draft.id, 0, cases[0].answers as never, profile, database);
  const attached = await addAttachment(valid.id, valid.revision, new File(["proof"], "proof.pdf", { type: "application/pdf" }), profile, database);
  await finalizeReport(draft.id, attached.revision, profile, database);
  await expect(saveDraft(draft.id, attached.revision, {}, profile, database)).rejects.toThrow("figé");
  await reopenReport(draft.id, profile, database);
  await finalizeReport(draft.id, attached.revision, profile, database);
  await confirmReport(draft.id, profile, database);
  const sealed = (await database.reports.where("draft_id").equals(draft.id).first())!;
  const name = database.name;
  database.close(); database = new OfflineDB(name);
  expect((await database.reports.get(sealed.id))?.payload_hash).toBe(sealed.payload_hash);
  await expect(saveDraft(draft.id, attached.revision, {}, profile, database)).rejects.toThrow("figé");
  await expect(removeAttachment(draft.id, JSON.parse(sealed.canonical_payload).attachments[0].attachment_id,
    attached.revision, profile, database)).rejects.toThrow("figé");
  await expect(reopenReport(draft.id, profile, database)).rejects.toThrow("finalisé");
});

it("waits for source receipt and replays the exact confirmation after a lost response", async () => {
  const draft = await createDraft(profile, cached, database);
  const valid = await saveDraft(draft.id, 0, cases[0].answers as never, profile, database);
  await finalizeReport(draft.id, valid.revision, profile, database);
  await confirmReport(draft.id, profile, database);
  const report = (await database.reports.where("draft_id").equals(draft.id).first())!;
  const fetcher = vi.fn<typeof fetch>();
  await syncReports(profile, "token", database, fetcher);
  expect(fetcher).not.toHaveBeenCalled();
  const pending = (await database.outbox.where("draft_id").equals(draft.id).first())!;
  const sourceReceipt: Receipt = { operation_id: pending.id, draft_id: draft.id, server_version: 1,
    server_received_at: new Date().toISOString(), payload_hash: "a".repeat(64), validation: { valid: true, errors: [] } };
  await syncOutbox(profile, "token", database, vi.fn<typeof fetch>().mockResolvedValue(Response.json(sourceReceipt)));
  const receipt = { operation_id: report.operation_id, report_id: report.report_id, revision_id: report.revision_id,
    payload_hash: report.payload_hash, server_received_at: new Date().toISOString() };
  fetcher.mockRejectedValueOnce(new Error("Lost response")).mockResolvedValueOnce(Response.json(receipt));
  await syncReports(profile, "token", database, fetcher);
  expect((await database.reports.get(report.id))?.state).toBe("ERROR");
  await syncReports(profile, "token", database, fetcher, true);
  expect(fetcher.mock.calls[0][1]?.body).toBe(fetcher.mock.calls[1][1]?.body);
  expect((await database.reports.get(report.id))?.state).toBe("RECEIVED");
  // Another tab may finish while a stale sender is awaiting a refusal.
  await database.reports.update(report.id, { state: "QUEUED" });
  const race = vi.fn<typeof fetch>(async () => {
    await database.reports.update(report.id, { state: "RECEIVED", receipt });
    return Response.json({ detail: { code: "REPORT_PERMISSION_REVOKED" } }, { status: 403 });
  });
  await syncReports(profile, "token", database, race, true);
  expect((await database.reports.get(report.id))?.state).toBe("RECEIVED");
});


it("retains both immutable confirmations for a corrected report", async () => {
  const first = await createDraft(profile, cached, database);
  const saved = await saveDraft(first.id, 0, cases[0].answers as never, profile, database);
  await finalizeReport(first.id, saved.revision, profile, database);
  await confirmReport(first.id, profile, database);
  const second = await createDraft(profile, cached, database);
  await database.drafts.update(second.id, { answers: saved.answers, report_id: first.report_id,
    report_revision_number: 2, correction: { base_revision_id: first.report_revision_id!, correction_request_id: "request" } });
  await finalizeReport(second.id, second.revision, profile, database);
  await confirmReport(second.id, profile, database);
  const rows = await database.reports.where("report_id").equals(first.report_id!).toArray();
  expect(rows).toHaveLength(2);
  expect(new Set(rows.map(row => row.id)).size).toBe(2);
  const corrected = JSON.parse(rows.find(row => row.draft_id === second.id)!.canonical_payload);
  expect(corrected.revision_number).toBe(2);
  expect(corrected.correction.base_revision_id).toBe(first.report_revision_id);
});

it("migrates an existing confirmation without changing its proof or receipt", async () => {
  const name = database.name;
  database.close();
  const legacy = new Dexie(name);
  legacy.version(3).stores({ profiles: "id", forms: "key, owner", drafts: "id, owner, state",
    outbox: "id, owner, &draft_id", attachments: "id, owner, draft_id, state", settings: "key",
    reports: "id, owner, &draft_id, state" });
  const original = { id: "report", revision_id: "revision", owner: "author", draft_id: "draft",
    state: "RECEIVED", canonical_payload: "original proof", payload_hash: "a".repeat(64), receipt: { report_id: "report" } };
  await legacy.table("reports").add(original);
  legacy.close();
  database = new OfflineDB(name);
  expect(await database.reports.get("revision")).toEqual({ ...original, id: "revision", report_id: "report" });
});
