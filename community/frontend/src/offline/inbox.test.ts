// @vitest-environment node
import "fake-indexeddb/auto";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import pilot from "../../../forms/pilot-form.json";
import cases from "../../../forms/validation-cases.json";
import { OfflineDB, type Profile } from "./store";
import { pullInbox, type CorrectionBundle, type InboxEntry, type InboxReport } from "./inbox";
import { createCorrectionFromBundle } from "./corrections";

vi.mock("./shell", () => ({ prepareOfflineShell: vi.fn(async () => {}) }));
let database: OfflineDB;
const profile: Profile = { id: "author", tenant_id: "tenant", display_name: "Author", verified_at: Date.now(), editable_until: Date.now()+3600000 };
const snapshot = { tenant_id: "tenant", author: { id: "author", display_name: "Author" },
  organization: {id:"org",name:"Org",code:"ORG",type_code:"ADMIN"}, assignment:{id:"assignment",role_id:"role",role_code:"AUTHOR",clearance_level:1,scopes:[]},
  form_id:"form",form_version_id:"version",form_version:1,territory_id:"area",required_clearance:1,auth_method:"community-jwt" };
const report: InboxReport = { id:"report",current_revision_id:"revision",viewer_id:"author",author_id:"author",territory_id:"area",territory_name:"Area",
  form_id:"form",form_name:"Form",period:"2026-09-29",workflow_state:"CORRECTION_REQUESTED",comments:[],capabilities:{comment:false,request_correction:false,correct:true},
  corrections:[{id:"request",revision_id:"revision",author:"Reviewer",text:"Corriger le lieu",created_at:"2026-09-29",state:"OPEN"}],
  revisions:[{id:"revision",number:1,state:"CONFIRMED",payload_hash:"a".repeat(64),payload:{snapshot,answers:cases[0].answers as never,attachments:[],confirmed_at:"2026-09-29"}}] };
const bundle: CorrectionBundle = { report_id:"report",request_id:"request",revision:report.revisions[0],files:[],
  form:{id:"form",code:"pilot",name:"Pilot",territory_id:"area"},version:{...pilot,id:"version",form_id:"form",version:1,status:"PUBLISHED",schema_version:"synchrohq.form/v1"} as never,
  context:{snapshot,context_token:"signed",sync_grant:"grant",issued_at:new Date().toISOString(),expires_at:new Date(Date.now()+3600000).toISOString(),
    correction:{report_id:"report",base_revision_id:"revision",correction_request_id:"request",revision_number:2}} };
beforeEach(()=>{ database = new OfflineDB("inbox-test-"+crypto.randomUUID()); });
afterEach(async()=>{await database.delete();});

it("persists a pulled request, reopens offline and prepares a new revision without touching the source",async()=>{
  const fetcher=vi.fn<typeof fetch>(async input=>{
    const url=String(input);
    if(url.endsWith("/me")) return Response.json(profile);
    if(url.includes("/workflow/inbox")) return Response.json([report]);
    if(url.includes("/contexts/")) return Response.json(bundle.context);
    if(url.endsWith("/versions")) return Response.json([bundle.version]);
    return Response.json(bundle.form);
  });
  await pullInbox(profile,"token",database,fetcher);
  const name=database.name;database.close();database=new OfflineDB(name);
  const entry=(await database.inbox.get("author:report"))!;
  expect(entry.report.corrections[0].text).toBe("Corriger le lieu");
  const draft=await createCorrectionFromBundle(entry.bundles[0],profile,database);
  expect(draft.report_id).toBe("report");expect(draft.report_revision_number).toBe(2);
  expect(draft.report_revision_id).not.toBe("revision");
  expect((await database.inbox.get(entry.key))?.report.revisions[0].payload_hash).toBe("a".repeat(64));
  expect((await createCorrectionFromBundle(entry.bundles[0],profile,database)).id).toBe(draft.id);
});

it("keeps the last inbox on interrupted pull and removes revoked resources only after a complete snapshot",async()=>{
  const original: InboxEntry={key:"author:report",owner:"author",tenant_id:"tenant",report,pulled_at:Date.now(),bundles:[bundle]};
  await database.inbox.put(original);
  const interrupted=vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(profile)).mockRejectedValueOnce(new Error("Network lost"));
  await expect(pullInbox(profile,"token",database,interrupted)).rejects.toThrow("Network lost");
  expect(await database.inbox.get(original.key)).toEqual(original);
  const empty=vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(profile)).mockResolvedValueOnce(Response.json([]));
  await pullInbox(profile,"token",database,empty);expect(await database.inbox.count()).toBe(0);
});

it("rejects another identity and expired offline preparation",async()=>{
  const fetcher=vi.fn<typeof fetch>().mockResolvedValue(Response.json({...profile,id:"other"}));
  await expect(pullInbox(profile,"token",database,fetcher)).rejects.toThrow("Identité incohérente");
  await expect(createCorrectionFromBundle(bundle,{...profile,id:"other"},database)).rejects.toThrow("incohérent");
  await expect(createCorrectionFromBundle({...bundle,context:{...bundle.context,expires_at:new Date(0).toISOString()}},profile,database)).rejects.toThrow("expirée");
});
