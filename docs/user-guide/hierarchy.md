# Inbox hiérarchique — pilote local

L’interface courante utilise désormais une session commune FR/AR/EN. Voir [le guide du shell](application-shell.md). Les exemples de jetons ci-dessous restent utiles pour les intégrations techniques.

Pages : `/collect` pour la saisie, `/inbox` pour le suivi et les demandes,
`/reports` pour les preuves, commentaires et historique.

## Préparer les comptes fictifs

```powershell
docker compose exec -T backend python -m app.modules.hierarchy.demo
docker compose cp backend:/app/.local/hierarchy-demo.json .local/hierarchy-demo.json
```

Le fichier local contient des jetons de développement de quatre heures.
Ne pas le partager ni le committer. Pour copier celui d'un acteur :

```powershell
$demo = Get-Content .local/hierarchy-demo.json -Raw | ConvertFrom-Json
$demo.actors.author_1.token | Set-Clipboard
```

Utiliser `reviewer`, `regional`, `central`, `other_wilaya` pour les autres rôles.
Pour une démonstration de comptes distincts, ouvrir des profils de navigateur
distincts afin de séparer IndexedDB. Le dataset comprend dix obligations pour
la journée précédente ; les échéances sont configurées pour le scénario 8/1/1.

## Auteur

1. Dans Collecte, préparer la session et les formulaires en ligne.
2. Dans Inbox, synchroniser puis choisir un rapport attendu à remplir.
3. Saisir, ajouter les fichiers, finaliser et confirmer, y compris hors connexion.
4. Au retour du réseau, préparer sa session puis laisser la synchronisation aboutir.
5. Synchroniser l'inbox : les commentaires et demandes sont conservés localement.
6. Après une coupure réseau, recharger l'inbox et utiliser « Préparer la correction
   hors ligne ». Cela nécessite un contexte et des fichiers téléchargés lors du pull.
7. Modifier, confirmer et synchroniser la nouvelle révision. Les brouillons
   bloqués ou en attente restent accessibles dans l'inbox auteur.

## Responsable et lecteur central

Dans Inbox, choisir « Inbox hiérarchique », saisir son jeton et synchroniser.
Utiliser les filtres métier, consulter le dossier, commenter ou demander une
correction selon les permissions. « Marquer comme examiné » porte uniquement
sur la révision courante et n'est proposé qu'au responsable autorisé.
Le lecteur central consulte l'historique et les obligations sans pouvoir confirmer
à la place de l'auteur.

## Configurer une obligation

V1 propose une API de configuration, sans constructeur de calendrier universel :

```http
POST /api/reports/workflow/requirements
Authorization: Bearer <administrateur autorisé>
Content-Type: application/json

{
  "id": "<UUID stable>",
  "form_id": "<formulaire du territoire cible>",
  "organization_id": "<organisation cible>",
  "territory_id": "<territoire du formulaire>",
  "cadence": "DAILY",
  "active_from": "2026-10-01",
  "active_until": "2026-10-31",
  "timezone": "Africa/Nouakchott",
  "deadline_hour": 18,
  "deadline_days": 0
}
```

L'API nécessite `forms:manage` et `reporting:manage`. Cadences disponibles :
DAILY, WEEKLY, MONTHLY. Les périodes attendues sont matérialisées lors de la
consultation d'une plage autorisée. Les configurations et attendus historiques
ne sont pas modifiés rétroactivement.

## Vérification ciblée du gate

```powershell
Set-Location community/frontend
pnpm exec playwright test e2e/hierarchy.spec.ts --reporter=line
```

Le gate remplit les obligations par les API, sans fabriquer de faux reçus.
Il produit `.local/phase6-gate.json` comme preuve locale, sans jetons.
Le jeu fictif est conservé : une nouvelle exécution doit partir d'obligations
non encore satisfaites pour l'auteur principal, ou d'un nouveau jour de démonstration.
