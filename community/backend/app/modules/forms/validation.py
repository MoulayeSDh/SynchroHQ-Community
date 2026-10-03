import json
import re
from typing import Any

from fastapi import HTTPException
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError

from app.core.config import get_settings
from app.modules.forms.schemas import Envelope, ValidationIssue, ValidationResult

KEYWORDS = set(
    "$schema type properties required additionalProperties items minItems maxItems "
    "uniqueItems enum const minimum maximum exclusiveMinimum exclusiveMaximum "
    "minLength maxLength pattern format allOf anyOf oneOf not if then else "
    "title description default".split()
)
WIDGETS = {
    "text",
    "textarea",
    "integer",
    "decimal",
    "date",
    "datetime",
    "select",
    "multi-select",
    "boolean",
    "gps",
    "attachments-metadata",
    "repeating-group",
}
FORMATS = {"date", "date-time", "uuid"}


def issue(path: str, code: str) -> ValidationIssue:
    key = re.sub(r"(?<!^)(?=[A-Z])", "_", code).lower()
    return ValidationIssue(path=path, code=code, message_key=f"validation.{key}")


def pointer(parts: Any) -> str:
    return "".join("/" + str(part).replace("~", "~0").replace("/", "~1") for part in parts)


def reject(message: str) -> None:
    raise HTTPException(422, detail=message)


def validate_envelope(envelope: Envelope) -> None:
    settings = get_settings()
    if len(envelope.model_dump_json().encode()) > settings.form_schema_max_bytes:
        reject("Form envelope exceeds FORM_SCHEMA_MAX_BYTES")
    if not {"fr", "ar"}.issubset(envelope.translations) or not set(envelope.translations).issubset(
        {"fr", "ar", "en"}
    ):
        reject("French and Arabic translations are required")
    schema = envelope.data_schema
    if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        reject("JSON Schema Draft 2020-12 is required")
    if schema.get("type") != "object":
        reject("Root schema must be an object")
    fields: dict[str, dict[str, Any]] = {}
    objects: dict[str, set[str]] = {}
    count = 0

    def walk(node: Any, depth: int, path: str, field: bool = False) -> None:
        nonlocal count
        if depth > settings.form_schema_max_depth:
            reject("Schema exceeds FORM_SCHEMA_MAX_DEPTH")
        if not isinstance(node, dict) or set(node) - KEYWORDS:
            reject("Unsupported schema keyword or schema shape (references are disabled in V1)")
        if field:
            count += 1
            fields.setdefault(path, node)
        if count > settings.form_schema_max_fields:
            reject("Schema exceeds FORM_SCHEMA_MAX_FIELDS")
        if "format" in node and node["format"] not in FORMATS:
            reject("Unsupported format")
        types = node.get("type", [])
        if types == "array" or isinstance(types, list) and "array" in types:
            maximum = node.get("maxItems")
            if (
                not isinstance(maximum, int)
                or isinstance(maximum, bool)
                or not 0 <= maximum <= settings.form_array_max_items
            ):
                reject("Every array requires maxItems within FORM_ARRAY_MAX_ITEMS")
            if "items" not in node:
                reject("Every array requires items")
        if "properties" in node:
            objects.setdefault(path, set(node["properties"]))
        for name, child in node.get("properties", {}).items():
            walk(child, depth + 1, path + pointer([name]), True)
        if "items" in node:
            walk(node["items"], depth + 1, path + "/*")
        for key in ("if", "then", "else", "not"):
            if key in node:
                walk(node[key], depth + 1, path)
        for key in ("allOf", "anyOf", "oneOf"):
            for child in node.get(key, []):
                walk(child, depth + 1, path)

    try:
        Draft202012Validator.check_schema(schema)
        walk(schema, 0, "")
    except (SchemaError, TypeError, ValueError, AttributeError, RecursionError) as exc:
        raise HTTPException(422, detail="Invalid or excessively complex JSON Schema") from exc
    ui = envelope.ui_schema
    if set(ui) - {"fields", "title_key", "description_key", "order"}:
        reject("Unsupported UI schema key")
    if not isinstance(ui.get("fields"), dict):
        reject("ui_schema.fields must map schema paths to widget settings")
    orders = ui.get("order", {})
    if not isinstance(orders, dict):
        reject("ui_schema.order must map object paths to field-name arrays")
    for object_path, names in orders.items():
        if (
            object_path not in objects
            or not isinstance(names, list)
            or any(not isinstance(name, str) for name in names)
        ):
            reject("Invalid UI field order")
        if len(set(names)) != len(names) or set(names) != objects[object_path]:
            reject("UI order must contain every object property exactly once")
    for path, config in ui["fields"].items():
        if path not in fields or not isinstance(config, dict):
            reject("Unknown UI field path")
        if set(config) - {"widget", "label_key", "options", "visible_when"}:
            reject("Unsupported widget setting")
        if not isinstance(config.get("widget"), str) or config["widget"] not in WIDGETS:
            reject("Unsupported widget")
        field_schema = fields[path]
        types = field_schema.get("type", [])
        types = [types] if isinstance(types, str) else types
        widget = config["widget"]
        expected = {
            "text": "string",
            "textarea": "string",
            "date": "string",
            "datetime": "string",
            "integer": "integer",
            "decimal": "number",
            "boolean": "boolean",
            "gps": "object",
            "multi-select": "array",
            "repeating-group": "array",
            "attachments-metadata": "array",
        }.get(widget)
        if expected and expected not in types:
            reject("Widget is incompatible with field type")
        if widget == "select" and "enum" not in field_schema:
            reject("Select requires enum")
        if widget == "multi-select" and "enum" not in field_schema.get("items", {}):
            reject("Multi-select requires items.enum")
        options = config.get("options", {})
        if not isinstance(options, dict) or any(not isinstance(v, str) for v in options.values()):
            reject("options must map values to translation keys")
        condition = config.get("visible_when")
        if condition is not None:
            if (
                not isinstance(condition, dict)
                or set(condition) != {"path", "equals"}
                or not isinstance(condition["path"], str)
                or condition["path"] not in fields
                or "*" in condition["path"]
            ):
                reject("visible_when requires a root field path and equals")
        for key in [config.get("label_key"), *options.values()]:
            if not isinstance(key, str) or any(
                key not in t for t in envelope.translations.values()
            ):
                reject("Missing FR/AR translation")
    for name in ("title_key", "description_key"):
        if name in ui and (
            not isinstance(ui[name], str)
            or any(ui[name] not in t for t in envelope.translations.values())
        ):
            reject("Missing form translation")


def validate_answers(schema: dict[str, Any], answers: dict[str, Any]) -> ValidationResult:
    settings = get_settings()
    if len(json.dumps(answers, ensure_ascii=False).encode()) > settings.form_answers_max_bytes:
        raise HTTPException(413, detail="Answer payload too large")
    errors: list[ValidationIssue] = []
    for error in Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(answers):
        path = pointer(error.absolute_path)
        code = str(error.validator)
        if code == "required":
            # jsonschema emits one error per missing property; do not depend on English messages.
            for name in error.validator_value:
                if name not in error.instance:
                    errors.append(issue(path + pointer([name]), code))
        elif code == "additionalProperties":
            for name in error.instance.keys() - error.schema.get("properties", {}).keys():
                errors.append(issue(path + pointer([name]), code))
        else:
            errors.append(issue(path, code))
    unique = {(e.path, e.code): e for e in errors}
    return ValidationResult(valid=not unique, errors=[unique[k] for k in sorted(unique)])
