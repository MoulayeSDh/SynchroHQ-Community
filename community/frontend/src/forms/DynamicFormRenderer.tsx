"use client";

import { useRef, useState } from "react";
import type { ComponentType } from "react";
import type { Answers, Envelope, FieldUI, Locale, Schema, ValidationIssue, ValidationResult, Value } from "./types";
import { messages, translate } from "./translations";
import { escapePointer, validateAnswers } from "./validation";

type WidgetProps = {
  id: string; schema: Schema; value: Value | undefined; change: (value: Value | undefined) => void;
  config?: FieldUI; form: Envelope; locale: Locale; invalid: boolean;
};
function TextWidget(p: WidgetProps) {
  return <input id={p.id} aria-invalid={p.invalid} value={typeof p.value === "string" ? p.value : ""}
    type={p.config?.widget === "date" ? "date" : "text"}
    onChange={e => p.change(e.target.value || undefined)} />;
}
function TextareaWidget(p: WidgetProps) {
  return <textarea id={p.id} aria-invalid={p.invalid} rows={4} value={typeof p.value === "string" ? p.value : ""}
    onChange={e => p.change(e.target.value || undefined)} />;
}
function NumberWidget(p: WidgetProps) {
  return <input id={p.id} type="number" aria-invalid={p.invalid} step={p.schema.type === "integer" ? 1 : "any"}
    value={typeof p.value === "number" ? p.value : ""}
    onChange={e => p.change(e.target.value === "" ? undefined : Number(e.target.value))} />;
}
function BooleanWidget(p: WidgetProps) {
  return <input id={p.id} type="checkbox" aria-invalid={p.invalid} checked={p.value === true}
    onChange={e => p.change(e.target.checked)} />;
}
function SelectWidget(p: WidgetProps) {
  const options = p.schema.enum ?? [];
  return <select id={p.id} aria-invalid={p.invalid} value={p.value === undefined ? "" : String(options.findIndex(v => v === p.value))}
    onChange={e => p.change(e.target.value === "" ? undefined : options[Number(e.target.value)])}>
    <option value="">{messages[p.locale].choose}</option>
    {options.map((v, i) => <option key={i} value={String(i)}>{translate(p.form, p.locale, p.config?.options?.[String(v)], String(v))}</option>)}
  </select>;
}
function MultiSelectWidget(p: WidgetProps) {
  const options = p.schema.items?.enum ?? [];
  const selected = Array.isArray(p.value) ? p.value : [];
  return <select id={p.id} multiple aria-invalid={p.invalid}
    value={options.flatMap((v, i) => selected.includes(v) ? [String(i)] : [])}
    onChange={e => p.change([...e.target.selectedOptions].map(o => options[Number(o.value)]))}>
    {options.map((v, i) => <option key={i} value={String(i)}>{translate(p.form, p.locale, p.config?.options?.[String(v)], String(v))}</option>)}
  </select>;
}
function DatetimeWidget(p: WidgetProps) {
  // Explicit UTC keeps the JSON Schema date-time contract independent of browser timezone.
  return <input id={p.id} type="datetime-local" aria-invalid={p.invalid}
    title="UTC" value={typeof p.value === "string" ? p.value.replace(/Z$/, "") : ""}
    onChange={e => p.change(e.target.value ? e.target.value + (e.target.value.length === 16 ? ":00Z" : "Z") : undefined)} />;
}
export const WidgetRegistry: Record<string, ComponentType<WidgetProps>> = {
  text: TextWidget, textarea: TextareaWidget, integer: NumberWidget, decimal: NumberWidget,
  date: TextWidget, datetime: DatetimeWidget, boolean: BooleanWidget, select: SelectWidget,
  "multi-select": MultiSelectWidget,
};

function atPath(values: Answers, path: string): Value | undefined {
  let value: Value | undefined = values;
  for (const key of path.slice(1).split("/").map(v => v.replaceAll("~1", "/").replaceAll("~0", "~"))) {
    if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
    value = value[key];
  }
  return value;
}
function errorMessage(error: ValidationIssue, locale: Locale): string {
  const key = error.message_key.replace("validation.", "") as keyof typeof messages.fr;
  return messages[locale][key] ?? messages[locale].generic;
}

type FieldProps = {
  form: Envelope; locale: Locale; schema: Schema; schemaPath: string; path: string;
  value: Value | undefined; change: (value: Value | undefined) => void; root: Answers;
  errors: ValidationIssue[]; required?: boolean;
  managedAttachments?: boolean;
};
function orderedFields(form: Envelope, schema: Schema, path: string): [string, Schema][] {
  const properties = schema.properties ?? {};
  const order = form.ui_schema.order?.[path] ?? Object.keys(properties);
  return order.filter(key => key in properties).map(key => [key, properties[key]]);
}
function Field(p: FieldProps) {
  const config = p.form.ui_schema.fields[p.schemaPath];
  if (config?.visible_when && atPath(p.root, config.visible_when.path) !== config.visible_when.equals) return null;
  const kind = Array.isArray(p.schema.type) ? p.schema.type.find(v => v !== "null") : p.schema.type;
  const label = translate(p.form, p.locale, config?.label_key, p.schemaPath.endsWith("/*") ? `${p.locale === "ar" ? "عنصر" : p.locale === "en" ? "Item" : "Élément"} ${Number(p.path.split("/").at(-1)) + 1}` : p.schemaPath.split("/").at(-1));
  const errors = p.errors.filter(e => e.path === p.path);
  const id = "field" + p.path;
  const problems = errors.map(e => <p className="field-error" key={e.code} role="alert">{errorMessage(e, p.locale)}</p>);
  if (kind === "object") {
    const value = p.value && typeof p.value === "object" && !Array.isArray(p.value) ? p.value : {};
    return <fieldset><legend>{label}{p.required ? " *" : ""}</legend>{problems}
      {orderedFields(p.form, p.schema, p.schemaPath).map(([key, schema]) => <Field key={key} {...p} schema={schema}
        schemaPath={p.schemaPath + "/" + escapePointer(key)} path={p.path + "/" + escapePointer(key)}
        value={value[key]} required={p.schema.required?.includes(key)} change={next => {
          const result = { ...value }; if (next === undefined) delete result[key]; else result[key] = next;
          p.change(Object.keys(result).length ? result : undefined);
        }} />)}
    </fieldset>;
  }
  if (kind === "array" && config?.widget !== "multi-select") {
    const value = Array.isArray(p.value) ? p.value : [];
    if (config?.widget === "attachments-metadata" && p.managedAttachments) {
      return <fieldset><legend>{label}{p.required ? " *" : ""}</legend>{problems}
        <p>{p.locale === "ar" ? "الملفات المرفقة مدرجة أدناه مع حالة الإرسال." : p.locale === "en" ? "Attached files and upload status are shown below." : "Les fichiers joints et leur état d’envoi sont affichés ci-dessous."} {value.length ? `(${value.length})` : ""}</p>
      </fieldset>;
    }
    return <fieldset><legend>{label}{p.required ? " *" : ""}</legend>{problems}
      {config?.widget === "attachments-metadata" && <p>{messages[p.locale].metadata}</p>}
      {value.map((item, index) => <section className="repeating-item" key={index}>
        <Field {...p} schema={p.schema.items ?? {}} schemaPath={p.schemaPath + "/*"} path={p.path + "/" + index}
          value={item} required={false} change={next => p.change(value.map((v, i) => i === index ? next ?? null : v))} />
        <button type="button" onClick={() => p.change(value.filter((_, i) => i !== index))}>{messages[p.locale].remove} {index + 1}</button>
      </section>)}
      <button type="button" disabled={value.length >= (p.schema.maxItems ?? 100)}
        onClick={() => p.change([...value, p.schema.items?.type === "object" ? {} : ""])}>{messages[p.locale].add} — {label}</button>
    </fieldset>;
  }
  const widget = config?.widget ?? (p.schema.enum ? "select" : kind === "number" ? "decimal" : kind ?? "text");
  const Widget = WidgetRegistry[widget] ?? TextWidget;
  return <div className={widget === "boolean" ? "form-field checkbox-field" : "form-field"}>
    <label htmlFor={id}>{label}{p.required ? " *" : ""}{widget === "datetime" ? " (UTC)" : ""}</label>
    <Widget id={id} schema={p.schema} value={p.value} change={p.change} config={config}
      form={p.form} locale={p.locale} invalid={!!errors.length} />{problems}
  </div>;
}

export function DynamicFormRenderer({ form, locale, values, onChange, serverValidate,
  managedAttachments = false }: {
  form: Envelope; locale: Locale; values: Answers; onChange: (values: Answers) => void;
  serverValidate?: (values: Answers) => Promise<ValidationResult>;
  managedAttachments?: boolean;
}) {
  const [local, setLocal] = useState<ValidationResult | null>(null);
  const [server, setServer] = useState<ValidationResult | null>(null);
  const [pending, setPending] = useState(false);
  const [failed, setFailed] = useState(false);
  const revision = useRef(0);
  function change(next: Answers) {
    revision.current++; onChange(next); setLocal(null); setServer(null); setFailed(false); setPending(false);
  }
  async function validate() {
    const current = ++revision.current;
    setLocal(validateAnswers(form.data_schema, values)); setServer(null); setFailed(false);
    if (serverValidate) {
      setPending(true);
      try { const result = await serverValidate(values); if (current === revision.current) setServer(result); }
      catch { if (current === revision.current) setFailed(true); }
      finally { if (current === revision.current) setPending(false); }
    }
  }
  return <form className="dynamic-form" lang={locale} dir={locale === "ar" ? "rtl" : "ltr"}
    onSubmit={e => { e.preventDefault(); void validate(); }} noValidate>
    <h2>{translate(form, locale, form.ui_schema.title_key)}</h2>
    <p>{translate(form, locale, form.ui_schema.description_key)}</p>
    {orderedFields(form, form.data_schema, "").map(([key, schema]) => <Field key={key}
      form={form} locale={locale} schema={schema} schemaPath={"/" + escapePointer(key)} path={"/" + escapePointer(key)}
      root={values} value={values[key]} required={form.data_schema.required?.includes(key)} errors={[...new Map([...(local?.errors ?? []), ...(server?.errors ?? [])].map(e => [e.path + e.code, e])).values()]}
      managedAttachments={managedAttachments}
      change={value => { const next = { ...values }; if (value === undefined) delete next[key]; else next[key] = value; change(next); }} />)}
    <button type="submit" className="primary" disabled={pending}>{pending ? messages[locale].pending : messages[locale].validate}</button>
    {local && <p role="status">{messages[locale].local} : {local.valid ? messages[locale].valid : messages[locale].invalid}</p>}
    {server && <p role="status">{messages[locale].server} : {server.valid ? messages[locale].valid : messages[locale].invalid}</p>}
    {failed && <p role="alert">{messages[locale].network}</p>}
  </form>;
}
