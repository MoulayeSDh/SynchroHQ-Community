# Phase 8 — Analytics & Geospatial (terminée sur le pilote local)

Référence Phase 7 : `bfc21ec` / `phase7-application-shell-complete`.

## 8A/8B — Première tranche verticale

`GET /api/reports/analytics/overview?start=YYYY-MM-DD&end=YYYY-MM-DD` renvoie les
KPI attendus, reçus à temps, reçus en retard et manquants, ainsi que les agrégations
par début de période et territoire. Les filtres facultatifs sont `territory_id` et
`form_id`. La plage maximale est de 365 jours. La réponse indique `as_of` et le
fuseau de calcul UTC ; chaque échéance est fixée en amont dans le fuseau de
l'obligation.

L'API réutilise les obligations explicites de Phase 6 et matérialise leurs périodes
pour la plage demandée. Elle vérifie le tenant, la permission `reports:read`, la
portée territoriale et le niveau de clearance **avant** toute agrégation SQL.
L'appartenance d'un rapport à une obligation dépend uniquement de
`expected_report_receipts`. Une révision ultérieure n'ajoute aucune unité. Une
réception enregistrée après `as_of` est exclue de cet instantané.

Les filtres et le détail des obligations restent disponibles dans l'inbox ; le
dashboard est un écran de pilotage, sans édition métier. Il affiche les cartes KPI,
une série par période et une table territoriale. FR/AR/EN et RTL utilisent le shell
de Phase 7. Les données ne sont pas mises en cache hors connexion ; l'écran indique
explicitement que les chiffres serveur sont indisponibles quand le réseau est coupé.

Le test ciblé construit dix obligations réelles et neuf réceptions via l'API de
confirmation : 8 reçues à temps, 1 tardive, 1 manquante. Il vérifie aussi que les
agrégations se réconcilient avec le total et qu'un utilisateur hors périmètre ne
voit aucun chiffre ni filtre disponible.

## 8C — PostGIS et carte

L'image PostgreSQL 16 du pilote a été remplacée par PostgreSQL 16 + PostGIS en
conservant le volume. Avant migration, un dump a été créé et restauré dans une
base temporaire pour vérifier sa lisibilité. La migration `0010` active PostGIS,
crée `report_geo_points` en SRID 4326 et protège les points confirmés contre les
modifications. Les coordonnées valides sont projetées au moment de la confirmation
d'une révision ; seule la révision courante figure sur la carte. Les données
historiques sans GPS ne produisent aucun point artificiel.

`GET /api/reports/geospatial/points` applique tenant, territoire et clearance
dans la requête SQL avant de retourner les positions. La carte permet de filtrer
par période, territoire et formulaire, puis d'ouvrir le rapport correspondant.
Le gate navigateur a couvert le lecteur central sur mobile en EN et AR/RTL, le
responsable territorial sur desktop en FR, et l'utilisateur d'une autre Wilaya :
respectivement 2, 2 et 0 points. Les coordonnées de référence proviennent d'un
rapport synthétique confirmé dans une base pilote isolée.

## 8D — Validation croisée

Une validation API ciblée a passé 24 scénarios compte/filtre sur cette même base :
comptes central, territorial et hors périmètre ; périodes, territoires et formulaires.
Pour le jeu de référence, Analytics retourne 10 obligations = 8 reçues à temps +
1 tardive + 1 manquante, et Geo 2 points. Le compte hors Wilaya obtient 0 dans
les deux APIs. Les totaux et les décompositions se réconcilient pour chaque filtre.
Après migration, le pilote principal conservait ses 10 obligations et 20 révisions ;
son Analytics retournait toujours 10 = 8 + 1 + 1.

Les polygones territoriaux, heatmaps et analyses spatiales avancées sont hors
périmètre V1. Le déploiement, les tuiles de carte en production et le plan de
restauration relèvent de la Phase 9.

Les statistiques officielles restent déterministes et ne dépendent d'aucun LLM.
