# Commentaires et corrections de rapports

Statut : implémenté et validé sur le pilote local le 29 septembre 2026.

La suite Phase 6B est décrite dans `phase6b-operational-hierarchy.md` : elle ajoute
le pull des demandes et permet la préparation d’une correction hors ligne après
synchronisation en ligne.

Ce bloc prolonge la Phase 5 conformément au cycle V1, sans modifier son payload
canonique existant ni les preuves déjà reçues.

## Utilisation

Depuis `/reports`, un lecteur autorisé ouvre un rapport. La permission
`reports:comment` permet de déposer un commentaire lié à une révision précise.
La permission `reports:request-correction` permet de demander une correction
motivée de la révision courante. Une demande ouverte par révision est autorisée.

L'auteur utilise « Préparer la nouvelle révision ». Cette préparation nécessite
une connexion : elle vérifie ses droits actuels, récupère la version exacte du
formulaire et télécharge les pièces jointes d'origine. Chaque fichier est
vérifié par taille et SHA-256 puis recopié dans IndexedDB avec un nouvel UUID.
L'ensemble du brouillon et des fichiers est enregistré atomiquement. Une erreur
de téléchargement ou d'intégrité empêche la création du brouillon.

La collecte s'ouvre sur le brouillon de correction. La saisie, la finalisation,
la confirmation et le rechargement peuvent ensuite se faire hors connexion,
pendant la fenêtre autorisée. Au retour en ligne, l'auteur prépare sa session
dans `/collect`, comme pour la première révision. Le transport du brouillon et
de tous les fichiers précède la confirmation officielle.

À réception, le serveur ajoute la nouvelle révision, sa preuve et la résolution
de la demande, puis déplace le pointeur courant dans la même transaction.
L'ancienne révision est affichée « Remplacée » et garde ses réponses, son hash,
ses fichiers et ses commentaires. Les fichiers de chaque révision sont
téléchargeables avec les droits de lecture actuels.

## Autorisation et intégrité

La lecture, les commentaires et les demandes appliquent tenant, permission,
clearance et scope territorial. Une ressource invisible répond `404` ; une
action interdite sur un rapport visible répond `403`.

Seul l'auteur d'origine peut préparer et confirmer sa correction, avec
`reports:correct` et `reports:confirm`, ainsi que les droits de lecture et de
synchronisation existants. La préparation de confirmation utilise les deux
permissions sur une même affectation ; la réception revérifie cette affectation.
Le contexte signé lie rapport, demande, révision de base et numéro suivant.
Changer ce lien ou tenter de corriger une demande résolue est refusé.

Une version retirée reste utilisable pour cette correction précise, avec une
preuve dédiée signée par le serveur. Elle ne redevient pas disponible pour une
nouvelle saisie ordinaire. Les expirations JWT demeurent strictes ; aucun jeton
expiré n'est accepté. Une confirmation déjà figée dont la preuve a expiré reste
conservée et bloquée. Une nouvelle préparation de correction, puis un nouveau
brouillon avec reprise des changements, est nécessaire tant que la demande est
encore ouverte. Aucun renouvellement ne réécrit une preuve confirmée.

Les commentaires et demandes portent un `operation_id` persistant, conservé
dans IndexedDB en cas de réponse perdue ou de problème d'authentification.
Rejouer la même opération renvoie son accusé. Un contenu différent est refusé
et audité. Les envois concurrents de confirmation sont sérialisés et idempotents.

## Stockage

Migration `0007_report_corrections` : `report_comments`, `correction_requests`,
`correction_resolutions`, `report_workflow_operations`, trois permissions.
Les nouvelles tables sont append-only sous PostgreSQL. Les protections de
Phase 5 restent actives sur révisions, preuves, sources et fichiers officiels.
Le pointeur courant ne peut avancer que vers la révision suivante du même
rapport, accompagnée de la résolution de la demande visant son ancien courant.
L'identité, l'auteur, le territoire et la clearance du rapport restent immuables.
Le downgrade automatique est refusé pour préserver l'historique officiel.

IndexedDB version 4 utilise l'UUID de révision comme clé locale des confirmations
et conserve séparément `report_id`. La migration conserve les payloads, preuves,
opérations et accusés existants. Plusieurs révisions d'un même rapport peuvent
coexister. L'export JSON d'un brouillon inclut sa confirmation et son accusé ;
les octets des pièces jointes restent dans IndexedDB.

L'utilisateur de démonstration reçoit explicitement les trois permissions dans
l'environnement de développement. Aucun rôle existant de production n'est
automatiquement augmenté par la migration.

## Validation ciblée

- Backend : corrections sur version publiée ou retirée, conservation de la
  première révision, rejouabilité, autorisation et refus d'un autre auteur.
- Frontend : conservation de deux confirmations, migration d'une base existante,
  invariants de preuve et reprise d'une confirmation après réponse perdue.
- Navigateur : commentaire, demande, recopie PDF, confirmation hors connexion,
  rechargement, reconnexion, deux révisions consultables et fichiers identiques.
- PostgreSQL : migration sans écart, succession atomique, concurrence et refus
  des mutations de l'historique dans `verify-report-corrections.py`.

Contrôles statiques et build de production passent. Les suites globales ne sont
pas relancées pour ce bloc : seules les vérifications liées aux changements sont
exécutées.
