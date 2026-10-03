import Ajv2020 from "ajv/dist/2020";
import addFormats from "ajv-formats";
import type { Answers, Schema, ValidationIssue, ValidationResult } from "./types";

const ajv = new Ajv2020({ allErrors: true, strict: false, validateFormats: true });
addFormats(ajv);
export const escapePointer = (value: string) => value.replaceAll("~", "~0").replaceAll("/", "~1");

export function initialAnswers(schema: Schema): Answers {
  return Object.fromEntries(Object.entries(schema.properties ?? {}).flatMap(([key, field]) =>
    field.type === "boolean" ? [[key, false]] : []));
}

export function validateAnswers(schema: Schema, answers: Answers): ValidationResult {
  const validate = ajv.compile(schema);
  const valid = !!validate(answers);
  const unique = new Map<string, ValidationIssue>();
  for (const error of validate.errors ?? []) {
    let path = error.instancePath;
    if (error.keyword === "required") path += "/" + escapePointer(error.params.missingProperty);
    if (error.keyword === "additionalProperties") path += "/" + escapePointer(error.params.additionalProperty);
    // Ajv emits a synthetic `if` error in addition to the failing then/else branch.
    if (error.keyword === "if") continue;
    const code = error.keyword;
    const message_key = "validation." + code.replace(/[A-Z]/g, c => "_" + c.toLowerCase());
    unique.set(path + ":" + code, { path, code, message_key });
  }
  return { valid, errors: [...unique.values()].sort((a, b) => a.path.localeCompare(b.path) || a.code.localeCompare(b.code)) };
}
