export type Locale = "fr" | "ar" | "en";
export type Value = string | number | boolean | null | Value[] | { [key: string]: Value };
export type Answers = Record<string, Value>;
export interface Schema {
  type?: string | string[];
  properties?: Record<string, Schema>;
  items?: Schema;
  required?: string[];
  enum?: Value[];
  const?: Value;
  format?: string;
  minItems?: number;
  maxItems?: number;
  minimum?: number;
  maximum?: number;
  minLength?: number;
  maxLength?: number;
  [key: string]: unknown;
}
export type WidgetName = "text" | "textarea" | "integer" | "decimal" | "date" | "datetime" |
  "select" | "multi-select" | "boolean" | "gps" | "attachments-metadata" | "repeating-group";
export interface FieldUI {
  widget: WidgetName;
  label_key: string;
  options?: Record<string, string>;
  visible_when?: { path: string; equals: Value };
}
export interface Envelope {
  schema_version: "synchrohq.form/v1";
  data_schema: Schema;
  ui_schema: { title_key?: string; description_key?: string; order?: Record<string, string[]>; fields: Record<string, FieldUI> };
  translations: Record<"fr" | "ar", Record<string, string>> & { en?: Record<string, string> };
}
export interface FormVersion extends Envelope {
  id: string;
  form_id: string;
  version: number;
  status: "DRAFT" | "PUBLISHED" | "RETIRED";
}
export interface FormRecord {
  id: string;
  code: string;
  name: string;
  territory_id: string;
  actions?: { manage: boolean; publish: boolean; collect?: boolean };
}
export interface ValidationIssue { path: string; code: string; message_key: string }
export interface ValidationResult { valid: boolean; errors: ValidationIssue[] }
