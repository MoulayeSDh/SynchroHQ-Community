"use client";
import { useUI } from "../../ui/session";
import { useEffect, useState } from "react";
import { Badge } from "../../ui/Shell";
import { initialAnswers } from "../../forms/validation";
import { DynamicFormRenderer } from "../../forms/DynamicFormRenderer";
import type { Answers, Envelope, FormRecord, FormVersion, ValidationResult } from "../../forms/types";
export default function FormsPage() {
    const { token, t, locale, can, info, online } = useUI();
    const [forms, setForms] = useState<FormRecord[]>([]);
    const [selected, setSelected] = useState<FormRecord | null>(null);
    const [versions, setVersions] = useState<FormVersion[]>([]);
    const [version, setVersion] = useState<FormVersion | null>(null);
    const [values, setValues] = useState<Answers>({});
    const [error, setError] = useState("");
    const [busy, setBusy] = useState(false);
    const [territory, setTerritory] = useState("");
    const [code, setCode] = useState("");
    const [name, setName] = useState("");
    const [json, setJson] = useState("");
    const [connected, setConnected] = useState(false);
    useEffect(() => {
        let live = true;
        if (token)
            void api<FormRecord[]>("").then(list => { if (live) {
                setForms(list);
                setConnected(true);
            } }).catch(e => { if (live)
                setError(e.message); });
        return () => { live = false; };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [token]);
    async function api<T>(path: string, method = "GET", body?: unknown): Promise<T> {
        const response = await fetch("/api/forms-proxy" + path, {
            method, headers: { Authorization: `Bearer ${token}`, ...(body ? { "Content-Type": "application/json" } : {}) },
            ...(body ? { body: JSON.stringify(body) } : {}), cache: "no-store",
        });
        const result = await response.json();
        if (!response.ok)
            throw new Error(typeof result.detail === "string" ? result.detail : `Erreur ${response.status}`);
        return result as T;
    }
    async function run(work: () => Promise<void>) {
        setError("");
        setBusy(true);
        try {
            await work();
        }
        catch (e) {
            setError(e instanceof Error ? e.message : t("Erreur inattendue"));
        }
        finally {
            setBusy(false);
        }
    }
    async function selectForm(form: FormRecord) {
        const list = await api<FormVersion[]>(`/${form.id}/versions`);
        setSelected(form);
        setVersions(list);
        setVersion(null);
        setValues({});
    }
    async function lifecycle(action: "publish" | "retire") {
        if (!version)
            return;
        const next = await api<FormVersion>(`/${version.form_id}/versions/${version.version}/${action}`, "POST");
        setVersion(next);
        setVersions(versions.map(v => v.id === next.id ? next : v));
    }
    return <main className="forms-workspace">
    <header><h1>{t("Formulaires")}</h1><p>{t("Définir, publier et vérifier les formulaires de votre organisation.")}</p></header>
    <button disabled={busy || !token} onClick={() => void run(async () => { setForms(await api<FormRecord[]>("")); setConnected(true); })}>{t("Actualiser")}</button>
    {!online && <p role="status">{t("Données serveur indisponibles hors connexion.")}</p>}
    {error && <p role="alert" className="field-error">{t(error)}</p>}
    {connected && <div className="workspace-grid"><aside className="panel">
      <h2>{t("Catalogue")}</h2>{forms.length === 0 && <p>{t("Aucun formulaire accessible.")}</p>}
      {forms.map(form => <button className="catalog-item" key={form.id} disabled={busy} onClick={() => void run(() => selectForm(form))}>{form.name}</button>)}
      {can("forms:manage") && <details><summary>{t("Nouveau formulaire")}</summary>
        <label htmlFor="name">{t("Nom")}</label><input id="name" value={name} onChange={e => setName(e.target.value)}/>
        <label htmlFor="code">{t("Code")}</label><input id="code" value={code} onChange={e => setCode(e.target.value)}/>
        <label htmlFor="territory">{t("Identifiant du territoire")}</label><select id="territory" value={territory} onChange={e => setTerritory(e.target.value)}><option value="">{t("Territoire")}</option>{info?.territories.filter(v => v.actions.includes("forms:manage")).map(v => <option key={v.id} value={v.id}>{v.name}</option>)}</select>
        <button disabled={busy || !name || !code || !territory} onClick={() => void run(async () => {
                    const form = await api<FormRecord>("", "POST", { name, code, territory_id: territory });
                    setForms(await api<FormRecord[]>(""));
                    await selectForm(form);
                })}>{t("Créer")}</button>
      </details>}
    </aside><section className="panel">
      {!selected ? <p>{t("Sélectionnez un formulaire.")}</p> : <>
        <h2>{selected.name}</h2><div className="toolbar">{versions.map(v => <button key={v.id} disabled={busy} onClick={() => { setVersion(v); setValues(initialAnswers(v.data_schema)); }}>v{v.version} · <Badge state={v.status}/></button>)}</div>
        {selected.actions?.manage && <details><summary>{t("Importer une nouvelle version JSON")}</summary>
          <label htmlFor="envelope">{t("Définition du formulaire")}</label><textarea id="envelope" rows={8} value={json} onChange={e => setJson(e.target.value)}/>
          <input aria-label={t("Charger un fichier JSON")} type="file" accept=".json,application/json" onChange={e => {
                        const file = e.target.files?.[0];
                        if (file)
                            void run(async () => setJson(await file.text()));
                    }}/>
          <button disabled={busy || !json} onClick={() => void run(async () => {
                        const next = await api<FormVersion>(`/${selected.id}/versions`, "POST", JSON.parse(json) as Envelope);
                        setVersions([...versions, next]);
                        setVersion(next);
                        setValues(initialAnswers(next.data_schema));
                    })}>{t("Créer le brouillon")}</button>
        </details>}
        {version && <><div className="toolbar">
          <strong>{t("Version")}{" "}{version.version} · <Badge state={version.status}/></strong>
          {selected.actions?.publish && version.status === "DRAFT" && <button disabled={busy} onClick={() => void run(() => lifecycle("publish"))}>{t("Publier")}</button>}
          {selected.actions?.publish && version.status === "PUBLISHED" && <button disabled={busy} onClick={() => void run(() => lifecycle("retire"))}>{t("Retirer")}</button>}
          {selected.actions?.manage && <button disabled={busy} onClick={() => {
                            setJson(JSON.stringify({ schema_version: version.schema_version, data_schema: version.data_schema,
                                ui_schema: version.ui_schema, translations: version.translations }, null, 2));
                        }}>{t("Copier la définition pour une nouvelle version")}</button>}

        </div>
        <DynamicFormRenderer key={version.id + version.status} form={version} locale={locale} values={values} onChange={setValues} serverValidate={answers => api<ValidationResult>(`/${version.form_id}/versions/${version.version}/validate`, "POST", { answers })}/>
        </>}
      </>}
    </section></div>}
  </main>;
}
