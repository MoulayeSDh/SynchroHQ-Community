import { expect, test } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { createHash, randomUUID } from "node:crypto";
import cases from "../../forms/validation-cases.json";
import { canonicalJson } from "../src/offline/reports";

test("comment and correction produce a second immutable revision after offline reload", async ({ page, context, request }) => {
  test.setTimeout(90000);
  const credentials = JSON.parse(fs.readFileSync(path.resolve("../../.local/forms-demo.json"), "utf8"));
  const headers = { Authorization: `Bearer ${credentials.token}` };
  const errors: string[] = [];
  page.on("pageerror", e => errors.push(e.message));
  const versions = await (await request.get(`http://localhost:3000/api/forms-proxy/${credentials.form_id}/versions`, { headers })).json();
  const version = versions.filter((v: {status: string}) => v.status === "PUBLISHED").at(-1);
  const confirmationContext = await (await request.post(`http://localhost:3000/api/reports-proxy/contexts/${version.id}`, { headers })).json();
  const grant = await (await request.post(`http://localhost:3000/api/sync-proxy/grants/${version.id}`, { headers })).json();
  const bytes = Buffer.from("%PDF-1.4\nImmutable correction evidence\n%%EOF");
  const file = { attachment_id: randomUUID(), file_name: "preuve-correction.pdf", mime_type: "application/pdf", size: bytes.length,
    sha256: createHash("sha256").update(bytes).digest("hex") };
  const answers = { ...cases[0].answers, attachments: [file] };
  const now = new Date().toISOString();
  const payload = { schema_version: "synchrohq.report/v1", report_id: randomUUID(), revision_id: randomUUID(), revision_number: 1,
    draft_id: randomUUID(), device_id: randomUUID(), snapshot: confirmationContext.snapshot, answers, attachments: [file],
    created_at: now, finalized_at: now, confirmed_at: now };
  const sync = await request.post("http://localhost:3000/api/sync-proxy/drafts", { headers, data: {
    operation_id: randomUUID(), draft_id: payload.draft_id, device_id: payload.device_id, form_version_id: version.id,
    base_version: 0, client_updated_at: now, answers, sync_grant: grant.sync_grant } });
  expect(sync.status()).toBe(200);
  const uploaded = await request.put(`http://localhost:3000/api/sync-proxy/drafts/${payload.draft_id}/attachments/${file.attachment_id}`, { headers,
    multipart: { file_name: file.file_name, mime_type: file.mime_type, size: String(file.size), sha256: file.sha256,
      file: { name: file.file_name, mimeType: file.mime_type, buffer: bytes } } });
  expect(uploaded.status()).toBe(200);
  const canonical = canonicalJson(payload);
  const hash = createHash("sha256").update(canonical).digest("hex");
  const confirmed = await request.post("http://localhost:3000/api/reports-proxy/confirmations", { headers, data: {
    operation_id: randomUUID(), canonical_payload: canonical, payload_hash: hash, context_token: confirmationContext.context_token } });
  expect(confirmed.status()).toBe(200);
  await page.goto("http://localhost:3000/reports");
  await page.getByLabel("Jeton d’accès").fill(credentials.token);
  await page.getByRole("button", { name: "Charger les rapports" }).click();
  await page.getByRole("button", { name: new RegExp(payload.report_id.slice(0,8)) }).click();
  await page.getByLabel("Commentaire", { exact: true }).fill("Préciser le lieu de la visite.");
  await page.getByRole("button", { name: "Ajouter le commentaire" }).click();
  await expect(page.getByText("Préciser le lieu de la visite.", { exact: true })).toBeVisible();
  await page.getByLabel("Motif de correction").fill("Ajouter le lieu au résumé.");
  await page.getByRole("button", { name: "Demander une correction" }).click();
  await page.getByRole("button", { name: "Préparer la nouvelle révision" }).click();
  await expect(page).toHaveURL(/collect\?draft=/);
  await expect(page.getByLabel(/Résumé de la journée/)).toBeVisible();
  // Prepare the application shell before switching off network.
  await expect(page.getByText(/Application préparée pour le hors-ligne/)).toBeVisible();
  await context.setOffline(true);
  await page.getByLabel(/Résumé de la journée/).fill("Visite de terrain au quartier central : résumé corrigé.");
  await expect(page.getByText(/preuve-correction.pdf.*LOCAL/)).toBeVisible();
  await page.getByRole("button", { name: "Finaliser le rapport" }).click();
  await page.getByLabel("J’ai relu ce rapport et je confirme son contenu.").check();
  await page.getByRole("button", { name: "Confirmer définitivement" }).click();
  await expect(page.getByTestId("report-business-state")).toHaveText("Confirmé");
  const secondHash = await page.getByTestId("report-hash").textContent();
  expect(secondHash).not.toBe(hash);
  await page.reload();
  await expect(page.getByTestId("report-hash")).toHaveText(secondHash!);
  await context.setOffline(false);
  await page.getByText("Session et formulaires disponibles", { exact: true }).click();
  await page.getByLabel("Jeton d’accès").fill(credentials.token);
  await page.getByRole("button", { name: "Préparer mes formulaires" }).click();
  await expect(page.getByTestId("report-sync-state")).toHaveText("Rapport reçu par le serveur", { timeout: 20000 });
  const official = await (await request.get(`http://localhost:3000/api/reports-proxy/${payload.report_id}`, { headers })).json();
  expect(official.revisions).toHaveLength(2);
  expect(official.revisions[0].payload_hash).toBe(hash);
  expect(official.revisions[0].canonical_payload).toBe(canonical);
  expect(official.revisions[1].payload_hash).toBe(secondHash);
  expect(official.corrections[0].state).toBe("RESOLVED");
  expect(official.comments[0].revision_id).toBe(payload.revision_id);
  for (const revision of official.revisions) {
    const download = await request.get(`http://localhost:3000/api/reports-proxy/${payload.report_id}/attachments/${revision.payload.attachments[0].attachment_id}?revision_id=${revision.id}`, { headers });
    expect(download.status()).toBe(200); expect(await download.body()).toEqual(bytes);
  }
  await page.goto("http://localhost:3000/reports");
  await page.getByLabel("Jeton d’accès").fill(credentials.token);
  await page.getByRole("button", { name: "Charger les rapports" }).click();
  await page.getByRole("button", { name: new RegExp(payload.report_id.slice(0,8)) }).click();
  await expect(page.getByRole("heading", { name: "Révision 1 · Remplacée" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Révision 2 · Confirmée" })).toBeVisible();
  await page.screenshot({ path: "../../.local/report-correction.png", fullPage: true });
  expect(errors).toEqual([]);
});
