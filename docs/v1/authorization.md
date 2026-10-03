# Autorisation V1

Statut : prêt à geler — Phase 0

## Principe

Le frontend adapte l'interface, mais le backend prend chaque décision d'accès.
Tout est refusé par défaut.

```text
ALLOW =
    account.active
AND assignment.active_at(request_time)
AND permission(role, action)
AND assignment.clearance >= resource.required_clearance
AND resource.territory IN effective_scope(assignment)
```

L'appartenance à une organisation ou son périmètre territorial ne suffit jamais
à accorder un accès.

## Modèle configurable du pilote

Les codes sont génériques ; les libellés métier sont configurables.

| Rôle | Libellé pilote | Permissions principales |
|---|---|---|
| `REPORT_AUTHOR` | Agent communal / auteur | créer, modifier un brouillon, confirmer, consulter ses rapports, répondre à une correction |
| `AREA_REVIEWER` | Responsable de moughataa | consulter dans son scope, commenter, demander une correction |
| `REGIONAL_REVIEWER` | Responsable de wilaya | consulter dans son scope, commenter, demander une correction |
| `CENTRAL_READER` | Direction centrale | consulter dans son scope |
| `TENANT_ADMIN` | Administrateur | administrer la configuration autorisée, sans accès implicite au contenu |

Le rôle n'implique pas automatiquement un niveau de clearance ou un territoire.

## Clearance pilote

```text
1 = LOCAL
2 = AREA
3 = REGIONAL
4 = CENTRAL
```

Ces nombres et libellés sont une configuration du tenant. Une ressource possède
un `required_clearance`. Avoir une clearance élevée n'élargit pas le scope.

## Scope

Un scope référence un ou plusieurs territoires avec l'un des modes suivants :

- `SELF` : le territoire exact ;
- `DESCENDANTS` : le territoire et ses descendants dans l'arbre principal.

Exemples :

- l'auteur de `COMMUNE_A11` reçoit `SELF(COMMUNE_A11)` ;
- le responsable de `MOUGHATAA_A1` reçoit `DESCENDANTS(MOUGHATAA_A1)` ;
- le responsable de `WILAYA_A` reçoit `DESCENDANTS(WILAYA_A)` ;
- un acteur transversal peut recevoir plusieurs scopes explicites.

## Ressource et territoire de référence

Chaque rapport possède un `territory_id` métier déterminé à sa création et
capturé dans chaque révision. La consultation s'autorise sur ce territoire, pas
sur la position GPS facultative contenue dans les réponses.

Les commentaires et pièces jointes héritent du contrôle d'accès du rapport et de
la révision auxquels ils appartiennent.

## Comportement des endpoints

- une collection ne retourne que les ressources autorisées ;
- une lecture directe hors scope répond `404` afin de ne pas révéler l'existence
  de la ressource ;
- une action interdite sur une ressource visible répond `403` ;
- connaître un UUID ne donne aucun accès ;
- les exports et téléchargements de pièces jointes réappliquent les mêmes règles.

## Travail hors ligne

SynchroHQ distingue trois éléments :

```text
AUTH SESSION != LOCAL DATA != SYNC AUTHORIZATION
```

La durée maximale autorisée pour certaines opérations hors ligne est une
politique configurable par déploiement. Une valeur éventuelle, telle que 24
heures pour un pilote, n'est jamais un invariant du Core.

L'expiration d'une session ou d'une autorisation locale n'efface, n'altère et ne
masque jamais les brouillons, rapports, pièces jointes ou opérations conservés
sur le terminal. L'utilisateur peut être invité à se réauthentifier avant de
continuer une opération sensible ou de synchroniser.

La confirmation locale capture l'identité et l'affectation connues du terminal.
Lors de la synchronisation, le serveur réauthentifie l'utilisateur et réévalue
ses droits actuels. Si le compte, l'affectation ou le scope a changé :

1. aucune donnée locale n'est supprimée ;
2. l'opération reçoit un rejet explicite avec un code stable ;
3. le rapport passe en état de synchronisation bloqué ;
4. une résolution administrative peut être engagée et auditée.

La V1 n'accepte jamais silencieusement une opération uniquement parce qu'elle a
été créée hors ligne avant le changement de droits.

## Cas de test obligatoires

- le responsable de `WILAYA_A` ne lit rien de `WILAYA_B` ;
- une clearance 4 sans scope sur `WILAYA_B` n'accède pas à ses rapports ;
- un scope communal ne remonte pas vers les territoires parents ;
- un scope `DESCENDANTS(MOUGHATAA_A1)` couvre ses communes, pas `MOUGHATAA_A2` ;
- un utilisateur avec deux scopes accède exactement à leur union ;
- une affectation expirée ne donne aucun accès ;
- changer une affectation ne modifie pas les snapshots historiques ;
- un administrateur sans permission de lecture métier ne lit pas les rapports ;
- l'URL directe d'une pièce jointe hors scope est refusée ;
- les mêmes filtres précèdent toute future recherche ou utilisation par l'IA.
