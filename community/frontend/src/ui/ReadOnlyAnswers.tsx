"use client";
import type { Answers, Envelope, Value } from "../forms/types";
import { translate } from "../forms/translations";
import { useUI } from "./session";
export function ReadOnlyAnswers({ form, answers }: { form?: Envelope; answers: Answers }) {
  const { t, locale } = useUI();
  function render(value: Value, path: string): React.ReactNode {
    const config = form?.ui_schema.fields[path];
    if (Array.isArray(value)) return value.length ? <ol>{value.map((v,i) => <li key={i}>{render(v, path+"/*")}</li>)}</ol> : "—";
    if (value && typeof value === "object") return <dl>{Object.entries(value).map(([key,v]) => <div key={key}><dt>{label(path+"/"+key,key)}</dt><dd>{render(v,path+"/"+key)}</dd></div>)}</dl>;
    if (form && config?.options?.[String(value)]) return translate(form,locale,config.options[String(value)]);
    if (typeof value === "boolean") return t(value ? "Oui" : "Non");
    return value == null || value === "" ? "—" : String(value);
  }
  function label(path: string, key: string) { return form ? translate(form,locale,form.ui_schema.fields[path]?.label_key,key.replaceAll("_"," ")) : key.replaceAll("_"," "); }
  return <section><h4>{t("Contenu du rapport")}</h4><dl className="report-answers">{Object.entries(answers).filter(([key])=>key!=="attachments").map(([key,value]) => <div key={key}><dt>{label("/"+key,key)}</dt><dd>{render(value,"/"+key)}</dd></div>)}</dl></section>;
}
