# Domaine V1

Statut : prêt à geler — Phase 0

## But du pilote

Démontrer qu'un auteur affecté à une commune peut créer et confirmer un rapport
quotidien hors ligne, le synchroniser sans doublon, puis permettre sa
consultation par les responsables autorisés de la moughataa et de la wilaya.

Le cas mauritanien configure le pilote, mais le moteur reste indépendant des
noms et niveaux administratifs employés.

## Concepts du Core Community

### Identité et structure

- `User` : compte d'une personne physique ;
- `Territory` et `TerritoryType` : arbre territorial configurable ;
- `Organization` et `OrganizationType` : structure institutionnelle configurable ;
- `OrganizationTerritory` : zones dans lesquelles une organisation intervient ;
- `UserAssignment` : fonction datée d'un utilisateur dans une organisation ;
- `AssignmentScope` : territoires couverts par une affectation ;
- `Role`, `Permission`, `Clearance` : capacité, action et niveau d'accès.

Le détail normatif est défini dans `institutional-model.md` et
`authorization.md`.

### Collecte et responsabilité

- `Form` : identité stable d'un type de formulaire ;
- `FormVersion` : définition immuable et publiable du formulaire ;
- `Report` : dossier métier stable au fil des corrections ;
- `ReportRevision` : contenu versionné d'un rapport ;
- `Attachment` : fichier lié à une révision avec checksum ;
- `ConfirmationProof` : preuve technique de la confirmation de l'auteur ;
- `Comment` : observation liée à un rapport et, si nécessaire, à une révision ;
- `CorrectionRequest` : demande explicite de nouvelle révision ;
- `SyncOperation` : opération locale idempotente transmise au serveur ;
- `AuditEvent` : trace append-only d'une action importante.

## Invariants métier

1. Une version de formulaire publiée ne change plus.
2. Une révision confirmée ne peut plus être modifiée.
3. Une correction crée une nouvelle révision.
4. Un rapport possède au plus une révision courante officielle.
5. Une pièce jointe confirmée est identifiée par son checksum.
6. La confirmation capture l'auteur, son affectation et son périmètre au moment
   de l'acte.
7. L'état métier est indépendant de l'état de synchronisation.
8. Une opération rejouée avec le même `operation_id` ne produit pas deux effets.
9. Un changement de droits ne supprime jamais silencieusement une donnée locale.
10. Toute lecture et mutation serveur applique permission, clearance et scope.
11. Community fonctionne sans Enterprise et n'importe jamais de code Enterprise.

## Périmètre fonctionnel du pilote

Inclus :

- authentification et session locale limitée ;
- organisations, territoires, affectations et scopes du jeu de test ;
- un formulaire quotidien versionné ;
- brouillon local, finalisation et confirmation ;
- synchronisation du rapport et de ses pièces jointes ;
- consultation descendante autorisée ;
- commentaire, demande de correction et nouvelle révision ;
- historique et audit minimal.

Exclus :

- signature électronique qualifiée ;
- moteur ABAC ou policy engine avancé ;
- workflow arbitraire construit visuellement ;
- référentiel administratif national complet ;
- PostGIS avancé, heatmaps et clustering ;
- statistiques institutionnelles finales ;
- IA, RAG et recherche vectorielle.

## Horodatages distingués

`created_at`, `finalized_at`, `confirmed_at`, `sync_started_at` et
`server_received_at` représentent des événements différents. Les dates émises
par le terminal sont conservées avec leur origine ; le serveur enregistre ses
propres dates de réception.
