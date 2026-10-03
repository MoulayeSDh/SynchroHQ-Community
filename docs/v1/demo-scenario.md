# Scénario de démonstration V1

Statut : prêt à geler — Phase 0

## Objectif

Démontrer dans un échantillon fictif que SynchroHQ représente séparément les
territoires, les organisations et les affectations, puis transporte un rapport
confirmé hors ligne jusqu'aux responsables autorisés sans perte ni duplication.

## Configuration

Territoires :

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

Acteurs :

| Identité | Organisation | Rôle | Clearance | Scope |
|---|---|---|---:|---|
| `author_a11` | Mairie A11 | `REPORT_AUTHOR` | 1 | `SELF(COMMUNE_A11)` |
| `reviewer_a1` | Administration A1 | `AREA_REVIEWER` | 2 | `DESCENDANTS(MOUGHATAA_A1)` |
| `reviewer_wilaya_a` | Administration Wilaya A | `REGIONAL_REVIEWER` | 3 | `DESCENDANTS(WILAYA_A)` |
| `reviewer_wilaya_b` | Administration Wilaya B | `REGIONAL_REVIEWER` | 3 | `DESCENDANTS(WILAYA_B)` |
| `central_reader` | Direction centrale | `CENTRAL_READER` | 4 | `DESCENDANTS(MAURITANIE_TEST)` |
| `regional_council_a` | Conseil régional test | `REGIONAL_REVIEWER` | 2 | scopes explicites configurés |

Le conseil régional est lié à son périmètre par `OrganizationTerritory` et
`AssignmentScope`. Il n'est pas un parent artificiel des moughataas.

Chaque moughataa fictive possède aussi un commissariat central :

| Organisation | Type | Territoire lié | Relation |
|---|---|---|---|
| Commissariat central A1 | `CENTRAL_POLICE_STATION` | `MOUGHATAA_A1` | `JURISDICTION` |
| Commissariat central A2 | `CENTRAL_POLICE_STATION` | `MOUGHATAA_A2` | `JURISDICTION` |
| Commissariat central B1 | `CENTRAL_POLICE_STATION` | `MOUGHATAA_B1` | `JURISDICTION` |

Ces organisations enrichissent le modèle institutionnel sans intervenir dans le
parcours nominal initial. Un scénario métier de police pourra ensuite leur
attribuer des utilisateurs, formulaires et permissions sans changer le Core.

## Parcours nominal

1. `author_a11` se connecte en ligne et prépare sa session locale.
2. L'application télécharge la version `1.0.0-draft` du formulaire pilote et les
   données minimales de son affectation.
3. Le réseau est coupé.
4. L'auteur crée le rapport quotidien de `COMMUNE_A11`.
5. Il ajoute une activité, une position GPS et une image.
6. Il ferme complètement l'application.
7. Il la rouvre sans réseau et retrouve son brouillon.
8. Il finalise puis confirme explicitement la révision.
9. La révision devient `CONFIRMED + QUEUED` et son hash reste stable.
10. Le réseau revient ; la file transmet les pièces jointes et le rapport.
11. Une interruption provoque le renvoi de la même opération.
12. Le serveur enregistre un seul rapport, une seule révision confirmée et un
    seul effet métier, puis renvoie un accusé persistant.
13. `reviewer_a1` et `reviewer_wilaya_a` consultent le rapport.
14. `reviewer_wilaya_b` reçoit `404` sur l'URL directe du même rapport.
15. `central_reader` peut consulter le rapport grâce à sa permission, sa
    clearance et son scope national.

## Correction

1. `reviewer_a1` ajoute un commentaire sur la révision 1 et demande une
   correction motivée.
2. `author_a11` reçoit la demande lors de sa prochaine synchronisation.
3. Il crée la révision 2 sans modifier la révision 1.
4. Il modifie la réponse concernée, puis finalise et confirme la révision 2.
5. Après synchronisation, la révision 2 devient la révision courante.
6. Les deux révisions, leurs confirmations, leurs pièces jointes et leurs
   événements d'audit restent consultables selon les droits.

## Scénarios d'autorisation complémentaires

- `reviewer_a1` consulte `COMMUNE_A11` et `COMMUNE_A12`, mais pas
  `COMMUNE_A21` ;
- `reviewer_wilaya_a` consulte les deux moughataas de `WILAYA_A`, mais rien de
  `WILAYA_B` ;
- la clearance 3 de `reviewer_wilaya_b` ne compense pas son absence de scope sur
  `WILAYA_A` ;
- `regional_council_a` accède uniquement aux territoires explicitement accordés,
  indépendamment de l'arbre de l'administration ;
- l'existence d'un commissariat central sur une moughataa ne donne aucun accès à
  ses utilisateurs tant qu'une affectation, un rôle et un scope ne sont pas
  configurés ;
- après expiration de l'affectation de `author_a11`, une opération locale non
  transmise est bloquée explicitement, jamais effacée ;
- une nouvelle affectation ne modifie pas le snapshot de l'auteur dans les
  révisions 1 et 2.

## Preuves attendues

- contenu IndexedDB avant et après redémarrage ;
- même `operation_id` pendant les retries ;
- un seul enregistrement métier côté serveur ;
- ACK serveur conservé localement ;
- hash identique entre confirmation locale et validation serveur ;
- refus territoriaux automatisés ;
- historique complet des révisions ;
- événements d'audit associés au même `correlation_id`.

## Gate de sortie de la Phase 0

La Phase 0 est validée lorsque les parties prenantes approuvent :

- la séparation Territory / Organization / UserAssignment / Authorization ;
- le jeu de données fictif et les six acteurs ;
- le contenu minimal du formulaire pilote ;
- la politique configurable des opérations hors ligne, distincte de la
  conservation locale et de l'autorisation de synchronisation ;
- les transitions et invariants du cycle de vie ;
- le comportement attendu pour chaque étape et chaque refus d'accès.

Cette approbation autorise le démarrage de la Foundation. Elle ne valide ni le
référentiel mauritanien réel ni une signature électronique à valeur légale.
