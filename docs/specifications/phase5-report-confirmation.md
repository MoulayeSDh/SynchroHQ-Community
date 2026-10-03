# Phase 5 — Rapports et confirmation

Statut : implémentée et validée pour le pilote local le 29 septembre 2026.

## Parcours

Depuis `/collect`, l'auteur prépare sa session en ligne, saisit un brouillon,
le finalise puis confirme explicitement son contenu. La finalisation valide la
version exacte du formulaire ; elle peut revenir au brouillon. La confirmation
conserve une révision immuable, y compris hors connexion.

Les états métier `DRAFT`, `FINALIZED`, `CONFIRMED` sont distincts des états réseau.
`CONFIRMED + QUEUED` signifie que l'auteur a confirmé, mais que le serveur n'a
pas encore donné son accusé. Un blocage laisse le rapport et ses fichiers locaux
visibles et exportables. L'export JSON conserve la confirmation et sa preuve
canonique ; les octets des fichiers restent dans IndexedDB.

Cette phase fournit la première révision officielle, la consultation autorisée
et le téléchargement protégé de ses fichiers. Les commentaires, demandes de
correction et nouvelles révisions sont le bloc métier suivant ; les tables et
protections de cette phase n'autorisent pas encore ces transitions.

## Confirmation et preuve

La préparation fournit un contexte signé par le serveur : auteur, organisation,
affectation, rôle, clearance, scopes, territoire, formulaire et version exacte.
Le contexte nécessite `reports:create` et `reports:confirm` sur la même affectation,
avec le moteur d'autorisation de Phase 2. Le contexte expire au plus tard à la fin
de l'affectation connue ou de la fenêtre `OFFLINE_EDIT_SECONDS`.

La confirmation capture ce contexte, les réponses, les métadonnées des fichiers,
le terminal et les dates distinctes de création, finalisation et confirmation.
Le payload suit `synchrohq.report/v1`, sérialisé en JSON canonique RFC 8785 puis
haché en SHA-256. Le serveur vérifie la forme canonique, recalcule le hash et
compare les snapshots au contexte signé. Les nombres non finis, entiers hors de
la plage sûre et textes Unicode invalides sont refusés localement.

Le contexte décrit l'identité connue lors de la préparation, comme prévu pour
le travail hors ligne. La preuve technique conserve l'auteur, le terminal, la
méthode `community-jwt`, le hash et les dates locale et serveur. Les horodatages
locaux conservent leur origine et ne sont pas des horodatages de confiance.

## Réception

La synchronisation utilise d'abord la Phase 4 pour transporter la copie exacte
et tous les fichiers. La confirmation officielle est envoyée ensuite avec son
`operation_id` persistant. Le serveur exige :

- l'utilisateur authentifié propriétaire du contexte et du brouillon ;
- des droits actuels de création et confirmation sur l'affectation capturée ;
- un contexte signé non expiré ;
- une version publiée, ou un travail commencé avant son retrait ;
- des réponses métier valides, identiques au brouillon reçu ;
- tous les fichiers reçus avec les mêmes identifiants, tailles et SHA-256.

L'écriture du rapport, de sa révision, de la preuve, des liens de fichiers,
de l'opération et de l'audit est atomique. Deux envois concurrents identiques
créent un seul effet. Une reprise retourne l'accusé persistant, même après un
retrait de permission ; elle nécessite encore un utilisateur authentifié actif.
Un identifiant rejoué avec un autre contenu est rejeté et audité.

La confirmation n'est jamais modifiée automatiquement pour renouveler une
preuve expirée. Le rapport reste bloqué et récupérable ; une nouvelle saisie
peut être créée par duplication avec un contexte valide.

## Protection et consultation

Migration `0006_confirmed_reports` : `reports`, `report_revisions`,
`confirmation_proofs`, `report_attachments`, `report_operations`,
`report_audit_events` et permissions `reports:create`, `reports:confirm`, `reports:read`.

PostgreSQL interdit les modifications et suppressions des contenus confirmés,
preuves, liens de fichiers, opérations et audit. Le brouillon source et ses
métadonnées de fichiers sont également protégés après confirmation officielle.
Le pointeur de révision courante est validé et figé pour cette première phase.

`/reports` présente les rapports accessibles. Listes, lecture et téléchargement
réappliquent permission, tenant, clearance et scope territorial. Une lecture
directe hors périmètre répond `404`. Les snapshots historiques ne changent pas
avec les noms ou affectations actuels. L'audit trace la réception et les lectures.

## API

```text
POST /api/reports/contexts/{form_version_id}
POST /api/reports/confirmations
GET  /api/reports
GET  /api/reports/{report_id}
GET  /api/reports/{report_id}/attachments/{attachment_id}
```

## Validation ciblée

- 10 tests backend : nouveaux invariants de confirmation et autorisation modifiée.
- 12 tests frontend : confirmation locale et stockage hors ligne affecté.
- Ruff, Mypy, TypeScript, ESLint et build Next.js réussis.
- Migration appliquée ; `alembic check` sans divergence.
- Un parcours Playwright : saisie et PDF hors ligne, finalisation, confirmation,
  rechargement hors ligne, reconnexion, même hash serveur, consultation et octets
  du PDF téléchargé via l'accès protégé.
- PostgreSQL refuse 8 mutations sur les données protégées (essais annulés).
- Deux confirmations simultanées donnent un rapport, une révision, une opération
  et des accusés identiques.

## Reproduire

Depuis la racine :

```powershell
docker compose up -d --build backend frontend
docker compose exec -T backend alembic upgrade head
docker compose exec -T backend alembic check
docker compose exec -T -e FORMS_DEMO_API_URL=http://localhost:8000 backend python -m app.modules.forms.demo
docker compose cp backend:/app/.local/forms-demo.json .local/forms-demo.json
```

Depuis `community/frontend` : `pnpm exec playwright test e2e/reports.spec.ts`.
Puis depuis la racine :

```powershell
docker compose cp scripts/development/verify-confirmed-reports.py backend:/tmp/verify-confirmed-reports.py
docker compose exec -T -e PYTHONPATH=/app/community/backend backend python /tmp/verify-confirmed-reports.py
```

Les contrôles de démonstration conservent leurs rapports fictifs pour inspection.
L'atelier utilise encore des jetons manuels ; la connexion finale du pilote reste
un bloc distinct.
