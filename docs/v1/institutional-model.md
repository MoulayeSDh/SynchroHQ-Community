# Modèle institutionnel V1

Statut : prêt à geler — Phase 0

## Décision

SynchroHQ sépare strictement :

1. la structure territoriale ;
2. la structure organisationnelle ;
3. les affectations des utilisateurs ;
4. les autorisations accordées à ces affectations.

Les termes `Wilaya`, `Moughataa`, `Commune`, `Mairie`, `Conseil régional`,
`Préfet` et `Wali` sont des données de configuration du pilote mauritanien. Ils
ne sont jamais codés comme des niveaux obligatoires du moteur Community.

## Territory

Un territoire est une unité géographique ou administrative sur laquelle des
droits, des formulaires ou des rapports peuvent s'appliquer.

```text
Territory
├── id
├── tenant_id
├── type_id
├── code
├── name
├── parent_id          nullable
├── geometry_ref      nullable
├── active
├── valid_from
└── valid_to          nullable
```

`TerritoryType` est configurable. Le pilote utilise `COUNTRY`, `WILAYA`,
`MOUGHATAA` et `COMMUNE`, sans rendre ces valeurs universelles.

`parent_id` décrit l'arbre territorial administratif principal. La V1 exige un
arbre sans cycle et un seul parent actif par territoire. Les relations
géographiques qui se chevauchent ou qui ne sont pas hiérarchiques ne sont pas
forcées dans cet arbre.

## Organization

Une organisation est une entité qui emploie, mandate ou regroupe des personnes.
Sa hiérarchie ne doit pas reproduire automatiquement celle des territoires.

```text
Organization
├── id
├── tenant_id
├── type_id
├── code
├── name
├── parent_id          nullable
├── active
├── valid_from
└── valid_to          nullable
```

`OrganizationType` est configurable. Le pilote peut contenir une mairie, une
administration de moughataa, une administration de wilaya, un ministère et un
conseil régional. Il contient également un commissariat central pour chaque
moughataa du jeu de données pilote.

## Périmètre territorial d'une organisation

Une organisation peut intervenir sur zéro, un ou plusieurs territoires.

```text
OrganizationTerritory
├── organization_id
├── territory_id
├── relation_type
├── valid_from
└── valid_to          nullable
```

`relation_type` précise la relation, par exemple `SEAT`, `JURISDICTION` ou
`OPERATIONAL_AREA`. Cette table permet de représenter un conseil régional sans
le placer artificiellement entre une wilaya et une moughataa.

## UserAssignment

Les droits sont portés par une affectation datée, pas directement par le compte.
Un utilisateur peut avoir plusieurs affectations, simultanées ou successives.

```text
UserAssignment
├── id
├── user_id
├── organization_id
├── role_id
├── clearance_level
├── valid_from
├── valid_to          nullable
├── active
└── is_primary
```

Les territoires autorisés sont liés séparément :

```text
AssignmentScope
├── assignment_id
├── territory_id
├── coverage          SELF | DESCENDANTS
├── valid_from
└── valid_to          nullable
```

Cette séparation permet à une personne d'appartenir à une organisation tout en
ayant un périmètre opérationnel couvrant plusieurs territoires.

## Jeu de données pilote

Le pilote utilise des données fictives réduites :

```text
MAURITANIE_TEST
├── WILAYA_A
│   ├── MOUGHATAA_A1
│   │   ├── COMMUNE_A11
│   │   └── COMMUNE_A12
│   └── MOUGHATAA_A2
│       └── COMMUNE_A21
└── WILAYA_B
    └── MOUGHATAA_B1
        └── COMMUNE_B11
```

Organisations représentées :

- une mairie dans `COMMUNE_A11` ;
- une administration pour chaque moughataa du jeu de test ;
- un commissariat central pour chaque moughataa du jeu de test ;
- une administration de `WILAYA_A` ;
- une administration de `WILAYA_B` ;
- une direction centrale nationale ;
- un conseil régional test couvrant un périmètre configuré explicitement.

Les commissariats centraux sont des organisations de type
`CENTRAL_POLICE_STATION`. Chacun est lié à sa moughataa par une relation
`JURISDICTION`. Ils ne sont ni des territoires ni des parents des communes. Leur
présence n'accorde aucun accès automatique : les droits de leurs agents passent
toujours par `UserAssignment` et `AssignmentScope`.

Le référentiel réel des 15 wilayas, 63 moughataas, 238 communes/mairies et 13
conseils régionaux sera importé ultérieurement. Il n'est pas une condition de la
V1 technique.

## Invariants

- aucun type territorial ou organisationnel métier n'est codé en dur ;
- aucun cycle n'est permis dans les hiérarchies ;
- supprimer une structure déjà référencée est interdit ; elle est désactivée ;
- toute affectation possède une période de validité ;
- un rapport conserve un snapshot de l'affectation utilisée lors de sa création
  et de sa confirmation ;
- modifier une affectation ne réécrit jamais l'historique des rapports ;
- le périmètre d'une organisation n'accorde pas automatiquement des droits à ses
  membres ; les droits proviennent de leurs affectations et scopes ;
- Community porte ce modèle générique sans dépendance vers Enterprise.

## Limite V1

La V1 utilise un arbre territorial administratif principal. Les géométries
complexes, zones superposées, relations spatiales calculées et analyses PostGIS
avancées appartiennent à une phase ultérieure. Le modèle conserve néanmoins des
identifiants stables permettant cette extension.
