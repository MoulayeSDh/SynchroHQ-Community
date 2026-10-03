# Phase 3 — Forms Engine

Statut : contrat gelé ; implémentation et gate pilote validés le 28 septembre 2026

## Objectif

Prouver qu'un formulaire arbitraire conforme au contrat SynchroHQ peut être
versionné, publié, récupéré, rendu en français ou en arabe et validé par le
frontend comme par le backend.

Cette phase ne crée ni rapport, ni stockage hors ligne, ni synchronisation.

## Modèle

```text
Form
├── id
├── tenant_id
├── code
├── name
├── description
├── active
└── archived

FormVersion
├── id
├── form_id
├── version            INTEGER
├── status             DRAFT | PUBLISHED | RETIRED
├── data_schema
├── ui_schema
├── translations
├── created_at
├── published_at
└── published_by
```

Contraintes :

```text
UNIQUE(tenant_id, Form.code)
UNIQUE(form_id, FormVersion.version)
```

## Enveloppe SynchroHQ Form v1

```json
{
  "schema_version": "synchrohq.form/v1",
  "data_schema": {},
  "ui_schema": {},
  "translations": {
    "fr": {},
    "ar": {}
  }
}
```

- `data_schema` est un JSON Schema Draft 2020-12 strict ;
- `ui_schema` décrit les widgets, l'ordre, les sections et la visibilité ;
- `translations` contient les libellés, descriptions, options et messages ;
- aucun libellé traduit n'est placé dans les mots-clés JSON Schema standards.

## Conditions

Les conditions de validité appartiennent au schéma de données. Exemple : lorsque
`needs_support` vaut `true`, `support_request` devient obligatoire via `if/then`.

Les conditions de présentation appartiennent au schéma UI. Exemple : masquer le
champ `support_request` lorsque `needs_support` vaut `false`.

Une règle peut donc être représentée sous ces deux angles sans confondre
validation métier et comportement visuel.

## Cycle de vie et immutabilité

```text
DRAFT -> PUBLISHED -> RETIRED
```

- seule une version `DRAFT` peut voir son contenu modifié ;
- la publication est atomique ;
- une version publiée ne redevient jamais brouillon ;
- `PUBLISHED` peut devenir `RETIRED` ;
- le contenu `data_schema`, `ui_schema` et `translations` est immuable à partir
  de la publication, y compris après le retrait ;
- une version publiée ou retirée reste lisible pour les références historiques ;
- une version publiée ou retirée ne peut pas être supprimée ;
- le retrait empêche seulement son utilisation pour une nouvelle saisie future.

La publication conserve `published_by` et `published_at`. Elle produit également
un événement d'audit `FORM_VERSION_PUBLISHED` avec l'acteur, le formulaire, la
version et l'horodatage.

## Permissions

```text
forms:read
forms:manage
forms:publish
```

Le moteur d'autorisation de la Phase 2 reste l'unique source de décision. La
gestion des personnes autorisées à créer un rapport avec un formulaire
(`FormAccess`) est explicitement reportée à la frontière des Phases 4 et 5.

## Validation

Dialecte : JSON Schema Draft 2020-12.

```text
Frontend -> Ajv
Backend  -> jsonschema
```

Le frontend fournit un retour immédiat, mais le backend revalide toujours et
reste l'autorité finale.

Les erreurs natives des deux bibliothèques sont normalisées vers :

```json
{
  "path": "/activities/0/description",
  "code": "minLength",
  "message_key": "validation.min_length"
}
```

Les résultats frontend et backend doivent être sémantiquement équivalents. Leur
représentation interne native n'a pas besoin d'être identique.

## Limites configurables V1

```text
FORM_SCHEMA_MAX_BYTES
FORM_SCHEMA_MAX_DEPTH
FORM_SCHEMA_MAX_FIELDS
FORM_ARRAY_MAX_ITEMS
```

Les références `$ref` externes sont interdites. La V1 utilise une liste contrôlée
de mots-clés JSON Schema. Les valeurs par défaut seront fixées dans la
configuration lors de l'implémentation et testées sans nombres magiques dispersés.

## Widgets Community V1

```text
text
textarea
integer
decimal
date
select
multi-select
boolean
gps
attachments-metadata
repeating-group
```

Les widgets décrivent la présentation. GPS reste un objet de données
latitude/longitude. Les pièces jointes ne sont que des métadonnées validables ;
leur upload réel appartient à une phase ultérieure.

## API prévue

```text
GET   /api/forms
POST  /api/forms
GET   /api/forms/{form_id}
GET   /api/forms/{form_id}/versions
POST  /api/forms/{form_id}/versions
GET   /api/forms/{form_id}/versions/{version}
PATCH /api/forms/{form_id}/versions/{version}
POST  /api/forms/{form_id}/versions/{version}/publish
POST  /api/forms/{form_id}/versions/{version}/retire
POST  /api/forms/{form_id}/versions/{version}/validate
```

`PATCH` refuse toute version qui n'est pas `DRAFT`. L'endpoint `validate` reste
stateless et ne crée aucun rapport.

## Frontend prévu

```text
DynamicFormRenderer
├── SchemaValidator
├── WidgetRegistry
├── ConditionalRenderer
├── RepeatingGroup
└── TranslationResolver
```

Aucun composant propre au rapport quotidien n'est codé en dur.

## Gate de sortie

```text
pilot-form.json
-> migration vers synchrohq.form/v1
-> Form + FormVersion 1 DRAFT
-> validation structurelle
-> publication atomique
-> immutabilité vérifiée
-> récupération API autorisée
-> rendu générique Next.js
-> bascule FR / AR et RTL
-> groupe répétable
-> champ conditionnel
-> validation Ajv
-> validation serveur
-> résultats sémantiquement équivalents
```

Tests minimaux :

1. isolation entre tenants ;
2. permissions de lecture, gestion et publication ;
3. modification d'un brouillon ;
4. refus de modification d'une version publiée ou retirée ;
5. rejet d'une enveloppe ou d'un schéma invalide ;
6. acceptation d'une réponse valide ;
7. rejet d'une réponse invalide avec chemins normalisés ;
8. condition `needs_support` / `support_request` ;
9. groupes répétables et contraintes numériques ;
10. rendu français puis arabe avec direction RTL.

## Hors scope

- `Report` et `ReportRevision` ;
- IndexedDB et Sync Engine ;
- upload réel des pièces jointes ;
- Form Builder visuel ;
- `FormAccess` avancé ;
- widgets Enterprise.

## Clôture d’implémentation — 28 septembre 2026

- 27 tests backend et 13 tests frontend réussis.
- Parcours Playwright réel réussi : accès protégé, formulaire publié, saisie,
  groupe répétable, condition, FR/AR/RTL et validations locale/serveur.
- Ruff, Mypy, ESLint, TypeScript et build Docker/Next.js réussis.
- Migration `0003_forms_engine` appliquée ; `alembic check` sans divergence.
- PostgreSQL refuse les modifications de contenu, suppressions et retours en
  brouillon des versions publiées (vérifications SQL annulées après chaque essai).
- Rendu desktop et mobile inspecté ; absence de débordement horizontal à 390 px.

Précisions d’implémentation :

- `Form.territory_id` et `required_clearance` raccordent les formulaires au moteur
  d’autorisation Phase 2. Le tenant provient de l’utilisateur authentifié.
- Les écritures de version verrouillent le parent `Form` pour sérialiser
  l’allocation des numéros et les transitions.
- `FormAuditEvent` conserve l’acteur, son nom au moment de l’action, le formulaire,
  la version, l’action et la date dans la même transaction que la publication.
- `ui_schema.order` fixe l’ordre des champs par chemin d’objet ; on ne dépend pas
  de l’ordre des clés JSONB. Les champs absents de cette configuration utilisent
  l’ordre retourné par le schéma.
- La V1 rejette toutes les références `$ref`, y compris locales. Cette restriction
  volontaire est plus forte que l’interdiction minimale des références externes.
- Les dates avec heure sont saisies en UTC. GPS est une saisie de coordonnées ;
  les pièces jointes restent des métadonnées sans upload.
- L’atelier est une interface de développement avec jeton Community en mémoire,
  pas un écran de connexion destiné au pilote de production.

Guide d’utilisation et reproduction : `../user-guide/forms-engine.md`.
