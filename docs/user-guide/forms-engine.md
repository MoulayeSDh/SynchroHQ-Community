# Forms Engine — Phase 3

L’interface courante utilise désormais une session commune FR/AR/EN. Voir [le guide du shell](application-shell.md). Les exemples de jetons ci-dessous restent utiles pour les intégrations techniques.

Le moteur Community définit, versionne, publie, affiche et valide les formulaires.
Il ne sauvegarde aucun rapport ni réponse. Les réponses restent en mémoire dans
le navigateur et sont perdues au rechargement ou au changement de version.

## Démarrer et préparer le pilote

Depuis la racine du dépôt, dans PowerShell :

```powershell
docker compose up -d --build
docker compose exec -T backend alembic upgrade head
docker compose exec -T -e FORMS_DEMO_API_URL=http://localhost:8000 backend python -m app.modules.forms.demo
New-Item -ItemType Directory -Force .local | Out-Null
docker compose cp backend:/app/.local/forms-demo.json .local/forms-demo.json
```

Le script crée un tenant synthétique dédié, un compte avec les seules permissions
Forms et un périmètre territorial propre. Il importe le pilote par HTTP puis le
publie. Relancer le script renouvelle le jeton de deux heures ; une définition
modifiée produit une nouvelle version au lieu de modifier une version publiée.
Il exige `APP_ENV=development`.

Ouvrir http://localhost:3000/forms, copier le champ `token` de
`.local/forms-demo.json` dans le champ de connexion et charger les formulaires.
Le fichier et les captures restent ignorés par Git et Docker. Le jeton n’est
jamais enregistré dans localStorage ou IndexedDB.

Sélectionner le rapport quotidien et sa dernière version publiée. Saisir une
activité, cocher la déclaration et utiliser « Vérifier les réponses ». Les deux
résultats sont affichés séparément. Le serveur revalide même si Ajv refuse les
réponses. Le changement de langue conserve les valeurs. Un échec réseau les
conserve également en mémoire.

L’administration permet de créer un formulaire, importer une enveloppe JSON,
publier, retirer et copier une définition pour créer la version suivante. La
modification d’un brouillon existant passe par l’API `PATCH` avec une enveloppe
complète. Il n’existe pas de constructeur visuel.

## Contrat de présentation V1

Le pilote migré est `community/forms/pilot-form.json`. L’original gelé reste dans
`docs/v1/pilot-form.json`.

```json
{
  "schema_version": "synchrohq.form/v1",
  "data_schema": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {"name": {"type": "string", "minLength": 1}},
    "required": ["name"],
    "additionalProperties": false
  },
  "ui_schema": {
    "title_key": "form.title",
    "order": {"": ["name"]},
    "fields": {"/name": {"widget": "text", "label_key": "name.label"}}
  },
  "translations": {
    "fr": {"form.title": "Exemple", "name.label": "Nom"},
    "ar": {"form.title": "مثال", "name.label": "الاسم"}
  }
}
```

Les chemins sont des JSON Pointers. `/*` désigne l’élément d’un tableau dans les
configurations UI, par exemple `/activities/*/description`. Les chemins des
erreurs utilisent un index concret : `/activities/0/description`.

`order` associe chaque chemin d’objet à la liste complète de ses propriétés dans
l’ordre souhaité. La racine utilise `""`, les activités `/activities/*`.

Une configuration de champ contient `widget`, `label_key`, éventuellement
`options` (valeur vers clé de traduction) et `visible_when` :

```json
{"path": "/needs_support", "equals": true}
```

Cette visibilité ne remplace jamais les conditions de validité dans
`data_schema`. Masquer un champ ne supprime pas automatiquement sa réponse.

Widgets : text, textarea, integer, decimal, date, datetime (UTC), select,
multi-select, boolean, gps, attachments-metadata et repeating-group.
Les objets sont rendus récursivement. Chaque tableau doit définir `items` et un
`maxItems` compatible avec la limite configurée.

Le backend accepte une liste contrôlée de mots-clés JSON Schema, refuse les
références et vérifie les traductions déclarées, widgets et chemins UI.
Formats V1 : date, date-time et uuid.

## Reproduire les vérifications

```powershell
Set-Location community/backend
../../.venv/Scripts/ruff.exe check app migrations tests
../../.venv/Scripts/python.exe -m mypy app
../../.venv/Scripts/python.exe -m pytest -q
Set-Location ../frontend
pnpm lint
pnpm typecheck
pnpm test
pnpm build
pnpm test:e2e
```

Le test E2E utilise la stack démarrée et le jeton du pilote. Il est ignoré si le
fichier de démonstration n’existe pas. Sous Windows, il utilise Edge installé ;
ailleurs, il faut un Chromium Playwright installé. Les captures FR, AR et mobile
sont écrites dans `.local/`.

La CI exécute les tests backend/frontend, le typage, le lint et le build. Le test
navigateur contre la stack locale n’est pas ajouté à cette CI.

Les cas de validation sont partagés dans `community/forms/validation-cases.json`.
Ils couvrent une réponse valide, les champs requis, la condition d’appui, une
quantité négative, une date invalide, un groupe vide, la déclaration et les champs
inconnus. Les tests API couvrent aussi les permissions, tenants, territoires,
clearance, transitions, audit et limites structurelles.
