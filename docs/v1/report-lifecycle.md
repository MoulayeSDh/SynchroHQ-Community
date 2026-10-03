# Cycle de vie d'un rapport V1

Statut : prêt à geler — Phase 0

## Deux machines d'état

L'état métier d'une révision et son état réseau ne sont jamais confondus.

```text
BUSINESS STATE
DRAFT -> FINALIZED -> CONFIRMED -> SUPERSEDED
                    \-> CORRECTION_REQUESTED
```

`CORRECTION_REQUESTED` décrit le workflow du rapport ; la révision confirmée
reste immuable. Lorsqu'une nouvelle révision est confirmée, l'ancienne devient
`SUPERSEDED` et reste consultable.

```text
SYNC STATE
LOCAL -> QUEUED -> SYNCING -> RECEIVED
                    \-> ERROR
                    \-> BLOCKED
```

Une révision `CONFIRMED + QUEUED` est valide : elle a été confirmée localement,
mais le serveur ne l'a pas encore reçue.

## Transitions

### Création et brouillon

Le terminal crée un `Report` et sa première `ReportRevision` avec des UUID
générés localement. Le brouillon est enregistré dans IndexedDB, en ligne comme
hors ligne.

### Finalisation

La finalisation exécute les validations de la version exacte du formulaire. Une
révision finalisée peut revenir à `DRAFT` tant qu'elle n'est pas confirmée.

### Confirmation

La confirmation est un acte explicite de l'auteur. Elle fige :

- les réponses ;
- l'identifiant et la version du formulaire ;
- le territoire métier ;
- le niveau requis de clearance ;
- les snapshots de l'auteur, de l'organisation et de l'affectation ;
- les identifiants, tailles, types MIME et checksums des pièces jointes ;
- les métadonnées importantes de création et de confirmation.

Le payload est sérialisé sous une forme canonique définie puis haché avec
SHA-256. `ConfirmationProof` conserve au minimum le hash, l'utilisateur, le
terminal, la date locale, la méthode d'authentification et la date de réception
serveur.

Cette preuve est une preuve technique d'intégrité et d'attribution dans
SynchroHQ. Elle n'est pas présentée comme une signature électronique qualifiée.

### Synchronisation

Chaque mutation possède un `operation_id` stable. Le serveur enregistre
l'opération et ses effets de façon atomique. Rejouer le même identifiant avec le
même payload retourne le même résultat sans créer de doublon. Réutiliser le même
identifiant avec un payload différent est rejeté et audité.

Une donnée locale n'est marquée `RECEIVED` qu'après un accusé serveur persistant.
Les pièces jointes utilisent aussi des identifiants et checksums stables.

### Correction

Un responsable autorisé crée une `CorrectionRequest` liée à la révision visée.
L'auteur du rapport crée une nouvelle révision à partir de la dernière révision
confirmée. La nouvelle révision a son propre cycle de finalisation, confirmation
et synchronisation.

Lorsque le serveur accepte la nouvelle révision :

- `Report.current_revision_id` pointe vers elle ;
- l'ancienne révision demeure accessible dans l'historique ;
- les commentaires restent liés à leur révision d'origine ;
- un événement d'audit décrit le changement de révision officielle.

## Audit minimal append-only

```text
REPORT_CREATED
REPORT_FINALIZED
REPORT_CONFIRMED
REPORT_SYNC_ACCEPTED
REPORT_SYNC_REJECTED
REPORT_VIEWED
COMMENT_ADDED
CORRECTION_REQUESTED
REVISION_CREATED
CURRENT_REVISION_CHANGED
```

Les événements d'audit ne remplacent pas les logs techniques et ne sont pas
modifiables par les opérations métier normales.

## Invariants testables

- aucune API normale ne modifie une révision confirmée ;
- une correction ne détruit jamais la révision précédente ;
- un seul `operation_id` ne produit qu'un seul effet métier ;
- le hash serveur est recalculé et comparé à la confirmation reçue ;
- une pièce jointe dont le checksum diffère est rejetée ;
- l'accusé serveur est reproductible après un retry ;
- une erreur ou un changement de droits laisse la donnée locale visible et
  récupérable.
