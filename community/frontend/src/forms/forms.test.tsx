import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import pilot from "../../../forms/pilot-form.json";
import cases from "../../../forms/validation-cases.json";
import { DynamicFormRenderer } from "./DynamicFormRenderer";
import { validateAnswers } from "./validation";
import type { Answers, Envelope, Locale } from "./types";

const form = pilot as Envelope;
afterEach(cleanup);

describe("shared frontend/backend validation contract", () => {
  for (const test of cases) it(test.name, () => {
    const result = validateAnswers(form.data_schema, test.answers as Answers);
    expect(result.valid).toBe(test.valid);
    if (test.name === "support-required") expect(result.errors).toContainEqual({
      path: "/support_request", code: "required", message_key: "validation.required",
    });
    if (test.name === "negative-quantity") expect(result.errors).toContainEqual({
      path: "/activities/0/quantity", code: "minimum", message_key: "validation.minimum",
    });
  });
});

function Harness({ locale = "fr" }: { locale?: Locale }) {
  const [values, setValues] = useState<Answers>({});
  return <DynamicFormRenderer form={form} locale={locale} values={values} onChange={setValues} />;
}

it("renders bilingual labels, RTL and preserves values on locale change", () => {
  const view = render(<Harness />);
  fireEvent.change(screen.getByLabelText(/Résumé de la journée/), { target: { value: "Texte conservé" } });
  view.rerender(<Harness locale="ar" />);
  expect(screen.getByRole("heading", { name: "التقرير الإقليمي اليومي" })).toBeTruthy();
  expect(screen.getByLabelText(/ملخص اليوم/)).toHaveProperty("value", "Texte conservé");
  expect(view.container.querySelector("form")?.getAttribute("dir")).toBe("rtl");
});

it("reveals conditional fields and creates/removes repeating groups", () => {
  render(<Harness />);
  expect(screen.queryByLabelText("Appui demandé")).toBeNull();
  fireEvent.click(screen.getByLabelText(/Un appui supérieur/));
  expect(screen.getByLabelText("Appui demandé")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Ajouter — Activités et faits rapportés" }));
  expect(screen.getByLabelText(/Description/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Supprimer 1" }));
  expect(screen.queryByLabelText(/Description/)).toBeNull();
});

it("runs independent local/server validation and retains answers on server failure", async () => {
  const serverValidate = vi.fn().mockRejectedValue(new Error("offline"));
  render(<DynamicFormRenderer form={form} locale="fr" values={cases[0].answers as Answers}
    onChange={() => {}} serverValidate={serverValidate} />);
  fireEvent.click(screen.getByRole("button", { name: "Vérifier les réponses" }));
  await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("Vos réponses restent affichées"));
  expect(serverValidate).toHaveBeenCalledWith(cases[0].answers);
  expect(screen.getByLabelText(/Résumé de la journée/)).toHaveProperty("value", cases[0].answers.executive_summary);
});


it("uses explicit UI order even after JSONB reorders schema properties", () => {
  const reversed = { ...form, data_schema: { ...form.data_schema,
    properties: Object.fromEntries(Object.entries(form.data_schema.properties ?? {}).reverse()),
  } };
  const { container } = render(<DynamicFormRenderer form={reversed} locale="fr" values={{}}
    onChange={() => {}} />);
  const firstInput = container.querySelector("form input");
  expect(firstInput?.id).toBe("field/report_date");
});

it("supports numeric enum values in multi-select widgets", () => {
  const sample: Envelope = {
    schema_version: "synchrohq.form/v1",
    data_schema: { type: "object", properties: { choices: { type: "array", maxItems: 3,
      items: { type: "integer", enum: [1, 2, 3] } } } },
    ui_schema: { fields: { "/choices": { widget: "multi-select", label_key: "choices" } } },
    translations: { fr: { choices: "Choix" }, ar: { choices: "خيارات" } },
  };
  const onChange = vi.fn();
  render(<DynamicFormRenderer form={sample} locale="fr" values={{}} onChange={onChange} />);
  const select = screen.getByLabelText("Choix") as HTMLSelectElement;
  select.options[1].selected = true;
  fireEvent.change(select);
  expect(onChange).toHaveBeenCalledWith({ choices: [2] });
});
