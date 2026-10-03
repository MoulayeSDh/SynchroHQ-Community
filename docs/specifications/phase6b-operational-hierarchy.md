# Phase 6B — Operational Hierarchy

Statut : implémentée et gate pilote local validé le 29 septembre 2026.
Les Phases 4 et 5 restent DONE. La Phase 6 est clôturée pour le périmètre V1 local.

## Parcours et inbox

`/inbox` propose deux vues : auteur et hiérarchie. L'auteur consulte ses rapports,
les corrections demandées, les brouillons à resynchroniser et les blocages locaux.
Le responsable consulte la même source centrale, commente depuis `/reports`,
demande une correction et marque la révision courante comme examinée.
L'examen est personnel et lié à une révision ; il ne valide pas une future révision.
Le lecteur central conserve une consultation seule. Aucun rapport n'est recopié
d'un niveau hiérarchique à l'autre.

Les états de l'inbox hiérarchique sont : reçus (ensemble), à examiner,
correction demandée, corrigés et confirmés/examinés. Ils ne remplacent pas
les états réseau ni l'immutabilité d'une révision officielle.

Les filtres portent sur la période métier, le territoire, le formulaire,
le statut, l'auteur et l'organisation. Le serveur restreint d'abord les ressources
par tenant, permission, clearance et scope, puis applique les filtres et la
pagination. Les choix de l'interface sont issus des données autorisées.

## Push et pull

La synchronisation de `/collect` transporte les brouillons, fichiers et preuves,
puis récupère l'inbox auteur. « Synchroniser mon inbox » permet aussi une
récupération explicite. La préparation initiale de la session récupère les demandes.

Le pull vérifie l'identité du jeton et récupère toutes les pages des rapports
propres à l'auteur. Chaque demande ouverte et autorisée reçoit son contexte
signé, la version exacte du formulaire et les octets des fichiers d'origine,
vérifiés par taille et SHA-256. Les fichiers inchangés déjà vérifiés sont réutilisés.
IndexedDB version 5 stocke le résultat par propriétaire. Le remplacement est
atomique après récupération complète ; un échec de pagination conserve le
dernier état. Une récupération complète retire les ressources devenues invisibles.
Une demande visible mais non préparée affiche une erreur explicite et ne permet
pas de créer silencieusement un brouillon incomplet.

Après ce pull, l'auteur peut recharger `/inbox` hors connexion, retrouver la demande,
préparer la nouvelle révision et ouvrir `/collect` sans réseau. Les pages publiques
et leurs assets sont mis en cache, jamais les réponses API ni les jetons.
Les preuves et fichiers restent dans IndexedDB. Les jetons restent en mémoire.
Le contexte signé préparé est une autorisation locale limitée dans le temps,
pas une dérogation aux vérifications actuelles du serveur.

Les droits et l'expiration sont revérifiés lors de la réception. Une correction
obsolète ou une autorisation expirée est bloquée sans supprimer les données.
La préparation répétée d'une même demande réouvre son brouillon non confirmé.
Les verrous du navigateur évitent les push/pull simultanés entre onglets.

## Obligations explicites

`ReportingRequirement` fixe formulaire, organisation cible, territoire,
cadence, dates actives, fuseau IANA, heure limite et nombre de jours après la
fin de période. V1 accepte DAILY, WEEKLY (lundi–dimanche) et MONTHLY.
Les périodes partielles de début ou fin d'activité ne sont pas produites.
Les jours sont civils, sans moteur de jours ouvrés, fêtes ou calendrier universel.
Le choix par défaut d'une heure ambiguë de changement de fuseau est la première
occurrence (`fold=0` de ZoneInfo). Le pilote mauritanien n'a pas ce changement.

En V1, le territoire cible est celui du formulaire. Plusieurs territoires peuvent
utiliser des formulaires distincts avec la même définition versionnée ; un formulaire
lié à un territoire parent ne donne pas implicitement le droit de confirmer pour
un enfant. L'organisation cible doit appartenir au tenant et être active.

L'API de configuration `POST /api/reports/workflow/requirements` nécessite
`forms:manage` et `reporting:manage`. Les UUID de configuration sont stables et
les périodes d'une même cadence/cible ne peuvent pas se chevaucher.
Les configurations sont immuables : V1 prévoit une fin d'activité explicite,
sans modifier rétroactivement les obligations historiques.

`ExpectedReport` est une projection persistante, avec UUID déterministe par
obligation/période et échéance UTC. Les requêtes de suivi matérialisent les
périodes autorisées couvrant la plage demandée (366 jours maximum).
Un endpoint de matérialisation explicite est aussi disponible pour l'administration.
Les verrous PostgreSQL et la contrainte unique empêchent les doublons.

L'auteur choisit « Remplir le rapport attendu ». Le contexte signé lie explicitement
l'attendu au formulaire, au territoire et à l'organisation de son affectation.
`expected_report_id` fait partie du payload canonique confirmé. La première réception
officielle crée un `ExpectedReceipt` dans la même transaction que la confirmation.
Un seul dossier peut satisfaire un attendu. Une nouvelle révision garde ce lien
et ne réécrit pas la date de réception initiale.

Un rapport ordinaire, même ressemblant, ne satisfait pas implicitement une obligation.
Il reste accessible mais hors des compteurs de suivi. La date locale de confirmation
ne peut pas transformer une réception tardive en réception à temps.

## Catégories explicables

| Catégorie | Définition |
|---|---|
| EXPECTED | Aucun reçu lié, échéance à venir ou égale à maintenant |
| RECEIVED | Reçu serveur lié avant ou à l'échéance |
| LATE | Reçu serveur lié après l'échéance |
| MISSING | Aucun reçu lié et échéance dépassée |

Ces catégories sont exclusives. Le gate donne 10 obligations = 8 reçus **à temps**
+ 1 reçu **en retard** + 1 manquant. Il y a donc 9 réceptions effectives au total.
Chaque ligne expose obligation, période, cible, échéance, fuseau, dossier lié,
date de réception et justification. Un attendu dont l'échéance est dépassée
sans réception reste MISSING ; LATE désigne une réception effective tardive.

## Données et sécurité

Migration `0008_operational_hierarchy` : `reporting_requirements`,
`expected_reports`, `expected_report_receipts`, `report_reviews` ; permissions
`reporting:manage`, `reports:review`. Les nouvelles tables sont append-only sous
PostgreSQL. Les protections de révision, preuve, source et fichier de Phase 5 restent
actives. Aucun rôle existant n'est augmenté implicitement.

Le module `app.modules.hierarchy.demo` crée un tenant fictif isolé, restreint
à APP_ENV=development : dix auteurs communaux, un responsable de moughataa,
un responsable de wilaya, un lecteur central, un utilisateur d'une autre wilaya
et un administrateur. Leurs jetons sont conservés uniquement dans `.local/`,
ignoré par Git. Le pilote ne constitue pas un déploiement OIDC de production.

## Gate de sortie

`community/frontend/e2e/hierarchy.spec.ts` vérifie sur PostgreSQL/MinIO :

1. Auteur A : confirmation offline d'un rapport explicitement attendu avec PDF.
2. Synchronisation et réception de la première preuve.
3. Responsable B : consultation dans l'inbox, commentaire et demande motivée.
4. Auteur A : pull, rechargement offline, demande encore visible.
5. Création de la révision 2 offline, confirmation puis synchronisation.
6. Responsable B et lecteur central C : deux révisions accessibles, première
   empreinte inchangée et téléchargement des deux versions du PDF.
7. Utilisateur autre wilaya : inbox vide, accès direct 404, aucun attendu découvert.
8. Dix obligations réelles, neuf confirmations par API et compteurs 8/1/1 explicables.

Validations ciblées : 17 tests backend sur les contrats touchés, 8 tests frontend,
un gate navigateur complet, migrations sans écart, typage, lint et build production.
Les suites globales n'ont pas été relancées. La Phase 7 peut désormais exploiter
ces catégories ; le déploiement réel et le pilote prolongé restent en Phase 8.
