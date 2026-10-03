import { translateUI } from "../ui/catalog";
import type { Envelope, Locale } from "./types";

export function translate(form: Envelope, locale: Locale, key: string | undefined, fallback = "") {
  return key ? form.translations[locale]?.[key] ?? (locale === "en" ? translateUI(form.translations.fr[key] ?? fallback, "en") : form.translations.fr[key]) ?? fallback : fallback;
}
export const messages = {
  fr: { add: "Ajouter", remove: "Supprimer", choose: "Choisir…", validate: "Vérifier les réponses",
    valid: "Les réponses sont valides.", invalid: "Des réponses sont à corriger.",
    server: "Vérification serveur", local: "Vérification du formulaire", pending: "Vérification…",
    metadata: "Métadonnées uniquement : aucun fichier n’est envoyé.",
    required: "Ce champ est obligatoire.", type: "Le type de valeur est incorrect.",
    min_length: "Le texte est trop court.", max_length: "Le texte est trop long.",
    minimum: "La valeur est trop petite.", maximum: "La valeur est trop grande.",
    min_items: "Ajoutez les éléments requis.", max_items: "Il y a trop d’éléments.",
    format: "Le format est incorrect.", const: "La confirmation est requise.",
    enum: "Choisissez une valeur proposée.", pattern: "La valeur ne respecte pas le format attendu.",
    additional_properties: "Ce champ n’est pas autorisé.", generic: "Vérifiez cette valeur.",
    network: "La vérification serveur a échoué. Vos réponses restent affichées.",
  },
  en: { add: "Add", remove: "Remove", choose: "Choose…", validate: "Check answers",
    valid: "The answers are valid.", invalid: "Some answers need correction.", server: "Server check", local: "Form check",
    pending: "Checking…", metadata: "Metadata only: no file is uploaded.", required: "This field is required.",
    type: "Incorrect value type.", min_length: "The text is too short.", max_length: "The text is too long.",
    minimum: "The value is too small.", maximum: "The value is too large.", min_items: "Add the required items.",
    max_items: "Too many items.", format: "Incorrect format.", const: "Confirmation is required.", enum: "Choose a listed value.",
    pattern: "The value does not match the required format.", additional_properties: "This field is not allowed.",
    generic: "Check this value.", network: "Server check failed. Your answers remain displayed.",
  },
  ar: { add: "إضافة", remove: "حذف", choose: "اختر…", validate: "التحقق من الإجابات",
    valid: "الإجابات صحيحة.", invalid: "توجد إجابات تحتاج إلى تصحيح.",
    server: "التحقق على الخادم", local: "التحقق من النموذج", pending: "جارٍ التحقق…",
    metadata: "بيانات وصفية فقط: لا يتم إرسال أي ملف.",
    required: "هذا الحقل مطلوب.", type: "نوع القيمة غير صحيح.",
    min_length: "النص قصير جداً.", max_length: "النص طويل جداً.",
    minimum: "القيمة صغيرة جداً.", maximum: "القيمة كبيرة جداً.",
    min_items: "أضف العناصر المطلوبة.", max_items: "عدد العناصر كبير جداً.",
    format: "التنسيق غير صحيح.", const: "التأكيد مطلوب.", enum: "اختر إحدى القيم المقترحة.",
    pattern: "القيمة لا تطابق التنسيق المطلوب.", additional_properties: "هذا الحقل غير مسموح.",
    generic: "تحقق من هذه القيمة.", network: "تعذر التحقق على الخادم. لا تزال إجاباتك معروضة.",
  },
};
