import { expect, test } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { randomUUID, createHash } from "node:crypto";
import cases from "../../forms/validation-cases.json";
import { canonicalJson } from "../src/offline/reports";

test("Phase 6 gate: separate actors, descending sync, offline correction and ten explainable obligations", async ({ browser, request }) => {
  test.setTimeout(120000);
  const demo = JSON.parse(fs.readFileSync(path.resolve("../../.local/hierarchy-demo.json"), "utf8"));
  const author = demo.actors.author_1; const reviewer = demo.actors.reviewer;
  const headers = (token: string) => ({Authorization: `Bearer ${token}`});
  const base="http://localhost:3000/api";
  async function json(url: string, token: string, method="GET", data?: object) {
    const result=await request.fetch(base+url,{method,headers:headers(token),data});
    expect(result.status(), await result.text()).toBe(200);return result.json();
  }
  // Nine receipts will be created through the public API, never by inserting fake statistics.
  for (const obligation of demo.obligations.slice(1,9)) {
    const actor=demo.actors[obligation.author];
    const existing=await json(`/reports-proxy/workflow/expected?start=${demo.period}&end=${demo.period}`,actor.token);
    if(existing.items.find((i:{id:string;report_id?:string})=>i.id===obligation.expected_id)?.report_id) continue;
    const context=await json(`/reports-proxy/contexts/${obligation.version_id}?expected_report_id=${obligation.expected_id}`,actor.token,"POST");
    const grant=await json(`/sync-proxy/grants/${obligation.version_id}`,actor.token,"POST");
    const now=context.issued_at;const answers={...cases[0].answers,report_date:demo.period};
    const payload={schema_version:"synchrohq.report/v1",report_id:randomUUID(),revision_id:randomUUID(),revision_number:1,
      draft_id:randomUUID(),device_id:randomUUID(),snapshot:context.snapshot,answers,attachments:[],created_at:now,finalized_at:now,confirmed_at:now,
      expected_report_id:obligation.expected_id};
    await json("/sync-proxy/drafts",actor.token,"POST",{operation_id:randomUUID(),draft_id:payload.draft_id,device_id:payload.device_id,
      form_version_id:obligation.version_id,base_version:0,client_updated_at:now,answers,sync_grant:grant.sync_grant});
    const canonical=canonicalJson(payload);
    await json("/reports-proxy/confirmations",actor.token,"POST",{operation_id:randomUUID(),canonical_payload:canonical,
      payload_hash:createHash("sha256").update(canonical).digest("hex"),context_token:context.context_token});
  }
  const authorContext=await browser.newContext();const authorPage=await authorContext.newPage();
  const reviewerContext=await browser.newContext();const reviewerPage=await reviewerContext.newPage();
  const errors: string[]=[];authorPage.on("pageerror",e=>errors.push(e.message));reviewerPage.on("pageerror",e=>errors.push(e.message));
  await authorPage.goto("http://localhost:3000/collect");
  await authorPage.getByLabel("Jeton d’accès").fill(author.token);
  await authorPage.getByRole("button",{name:"Préparer mes formulaires"}).click();
  await expect(authorPage.getByText(/Application préparée pour le hors-ligne/)).toBeVisible();
  await authorPage.goto("http://localhost:3000/inbox");
  await authorPage.getByLabel("Jeton d’accès").fill(author.token);
  await authorPage.getByRole("button",{name:"Synchroniser mon inbox"}).click();
  await authorPage.getByRole("button",{name:"Remplir le rapport attendu"}).click();
  await expect(authorPage).toHaveURL(/collect\?draft=/);
  await expect(authorPage.getByLabel(/Résumé de la journée/)).toBeVisible();
  await authorContext.setOffline(true);
  await authorPage.getByLabel(/Date du rapport/).fill(demo.period);
  await authorPage.getByLabel(/Niveau de situation/).selectOption({label:"Normal"});
  await authorPage.getByLabel(/Résumé de la journée/).fill("Rapport communal initial confirmé hors connexion.");
  await authorPage.getByRole("button",{name:"Ajouter — Activités et faits rapportés"}).click();
  await authorPage.getByLabel(/Catégorie/).selectOption({label:"Activité de terrain"});
  await authorPage.getByLabel("Description *",{exact:true}).fill("Visite au quartier central");
  await authorPage.getByLabel(/Date et heure/).fill(`${demo.period}T08:30`);
  await authorPage.getByLabel(/Quantité/).fill("3");
  await authorPage.getByLabel(/Je confirme/).check();
  const evidence=Buffer.from("%PDF-1.4\nHierarchy evidence\n%%EOF");
  await authorPage.getByLabel("Ajouter une pièce jointe").setInputFiles({name:"preuve-hierarchie.pdf",mimeType:"application/pdf",buffer:evidence});
  await expect(authorPage.getByText(/preuve-hierarchie.pdf.*LOCAL/)).toBeVisible();
  await authorPage.getByRole("button",{name:"Finaliser le rapport"}).click();
  await authorPage.getByLabel("J’ai relu ce rapport et je confirme son contenu.").check();
  await authorPage.getByRole("button",{name:"Confirmer définitivement"}).click();
  await expect(authorPage.getByTestId("report-business-state")).toHaveText("Confirmé");
  const firstHash=await authorPage.getByTestId("report-hash").textContent();
  await authorContext.setOffline(false);
  await authorPage.getByText("Session et formulaires disponibles",{exact:true}).click();
  await authorPage.getByLabel("Jeton d’accès").fill(author.token);
  await authorPage.getByRole("button",{name:"Préparer mes formulaires"}).click();
  await expect(authorPage.getByTestId("report-sync-state")).toHaveText("Rapport reçu par le serveur",{timeout:20000});
  const authorInbox=await json("/reports-proxy/workflow/inbox?own=true",author.token);
  const official=authorInbox.find((r:{revisions:{payload_hash:string}[]})=>r.revisions[0].payload_hash===firstHash);
  expect(official).toBeDefined();
  await reviewerPage.goto("http://localhost:3000/inbox");
  await reviewerPage.getByLabel("Vue").selectOption("HIERARCHY");
  await reviewerPage.getByLabel("Jeton d’accès").fill(reviewer.token);
  await reviewerPage.getByRole("button",{name:"Synchroniser mon inbox"}).click();
  await expect(reviewerPage.getByRole("heading",{name:new RegExp(`Rapport ${official.id.slice(0,8)}.*À examiner`)})).toBeVisible();
  await reviewerPage.goto(`http://localhost:3000/reports?report=${official.id}`);
  await reviewerPage.getByLabel("Jeton d’accès").fill(reviewer.token);
  await reviewerPage.getByRole("button",{name:"Charger les rapports"}).click();
  await reviewerPage.getByLabel("Commentaire",{exact:true}).fill("Vérification par le responsable territorial.");
  await reviewerPage.getByRole("button",{name:"Ajouter le commentaire"}).click();
  await expect(reviewerPage.getByText("Vérification par le responsable territorial.",{exact:true})).toBeVisible();
  await reviewerPage.getByLabel("Motif de correction").fill("Préciser le résultat de la visite.");
  await reviewerPage.getByRole("button",{name:"Demander une correction"}).click();
  await expect(reviewerPage.getByRole("heading",{name:"Correction demandée"})).toBeVisible();
  await expect(reviewerPage.getByRole("button",{name:"Préparer la nouvelle révision"})).toHaveCount(0);
  // The author only synchronizes the inbox here; the corrected draft does not exist yet.
  await authorPage.goto("http://localhost:3000/inbox");
  await authorPage.getByLabel("Jeton d’accès").fill(author.token);
  await authorPage.getByRole("button",{name:"Synchroniser mon inbox"}).click();
  await expect(authorPage.getByText(/Préciser le résultat de la visite/)).toBeVisible();
  await authorContext.setOffline(true);await authorPage.reload();
  await expect(authorPage.getByText(/Préciser le résultat de la visite/)).toBeVisible();
  await authorPage.getByRole("button",{name:"Préparer la correction hors ligne"}).click();
  await expect(authorPage).toHaveURL(/collect\?draft=/);
  await expect(authorPage.getByLabel(/Résumé de la journée/)).toBeVisible();
  await authorPage.getByLabel(/Résumé de la journée/).fill("Visite achevée : résultat et quartier précisés dans la correction.");
  await authorPage.getByRole("button",{name:"Finaliser le rapport"}).click();
  await authorPage.getByLabel("J’ai relu ce rapport et je confirme son contenu.").check();
  await authorPage.getByRole("button",{name:"Confirmer définitivement"}).click();
  await expect(authorPage.getByTestId("report-business-state")).toHaveText("Confirmé");
  const secondHash=await authorPage.getByTestId("report-hash").textContent();
  await authorContext.setOffline(false);
  await authorPage.getByText("Session et formulaires disponibles",{exact:true}).click();
  await authorPage.getByLabel("Jeton d’accès").fill(author.token);
  await authorPage.getByRole("button",{name:"Préparer mes formulaires"}).click();
  await expect(authorPage.getByTestId("report-sync-state")).toHaveText("Rapport reçu par le serveur",{timeout:20000});
  const central=await json(`/reports-proxy/${official.id}`,demo.actors.central.token);
  expect(central.revisions).toHaveLength(2);expect(central.revisions[0].payload_hash).toBe(firstHash);
  expect(central.revisions[1].payload_hash).toBe(secondHash);expect(central.corrections[0].state).toBe("RESOLVED");
  const supervisor=await json("/reports-proxy/workflow/inbox?status=CORRECTED",reviewer.token);
  expect(supervisor.find((r:{id:string})=>r.id===official.id)?.revisions).toHaveLength(2);
  for(const revision of central.revisions) {
    const file=revision.payload.attachments[0];
    const download=await request.get(`${base}/reports-proxy/${official.id}/attachments/${file.attachment_id}?revision_id=${revision.id}`,{headers:headers(demo.actors.central.token)});
    expect(download.status()).toBe(200);expect(await download.body()).toEqual(evidence);
  }
  const hidden=demo.actors.other_wilaya.token;
  expect(await json(`/reports-proxy/workflow/inbox?territory_id=${author.territory_id}&author_id=${author.id}`,hidden)).toEqual([]);
  expect((await request.get(`${base}/reports-proxy/${official.id}`,{headers:headers(hidden)})).status()).toBe(404);
  const invisible=await json(`/reports-proxy/workflow/expected?start=${demo.period}&end=${demo.period}`,hidden);
  expect(invisible.total).toBe(0);
  const totals=await json(`/reports-proxy/workflow/expected?start=${demo.period}&end=${demo.period}`,demo.actors.central.token);
  expect(totals.total).toBe(10);expect(totals.counts).toEqual({EXPECTED:0,RECEIVED:8,MISSING:1,LATE:1});
  for(const item of totals.items) {
    expect(item.requirement_id).toBeTruthy();expect(item.expected_by).toBeTruthy();expect(item.explanation).toBeTruthy();
    if(item.status === "RECEIVED") expect(Date.parse(item.received_at)).toBeLessThanOrEqual(Date.parse(item.expected_by));
    if(item.status === "LATE") expect(Date.parse(item.received_at)).toBeGreaterThan(Date.parse(item.expected_by));
    if(item.status === "MISSING") expect(item.report_id).toBeNull();
  }
  fs.writeFileSync(path.resolve("../../.local/phase6-gate.json"),JSON.stringify({passed:true,report_id:official.id,first_hash:firstHash,second_hash:secondHash,counts:totals.counts,total:totals.total,checked_at:new Date().toISOString()},null,2));
  expect(errors).toEqual([]);
  await authorContext.close();await reviewerContext.close();
});
