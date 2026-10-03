# Phase 2 — Identity & Authorization

Statut : terminée

## Implémentation Community

- `User` et identité JWT Community ;
- `Territory` avec hiérarchie configurable ;
- `Organization` indépendante de la hiérarchie territoriale ;
- `OrganizationTerritory` pour les juridictions et zones opérationnelles ;
- `UserAssignment` datée ;
- `Role`, `Permission` et `RolePermission` ;
- clearance numérique configurable ;
- `AssignmentScope` avec couverture `SELF` ou `DESCENDANTS` ;
- moteur d'autorisation en refus par défaut ;
- endpoint authentifié `GET /api/me`.

## Règle évaluée

```text
ALLOW =
    user.active
AND assignment.active_at(now)
AND organization.active
AND same_tenant
AND permission(role, action)
AND assignment.clearance >= resource.required_clearance
AND resource.territory IN effective_scope(assignment)
```

## Preuves du gate

- accès descendant dans une wilaya : autorisé ;
- accès à une autre wilaya : refusé ;
- ressource d'un autre tenant : refusée ;
- clearance insuffisante : refusée ;
- permission absente : refusée ;
- JWT valide : sujet extrait ;
- JWT altéré : rejeté ;
- appel `/api/me` sans Bearer token : HTTP 401 ;
- migration appliquée sur PostgreSQL réel ;
- neuf tables Phase 2 présentes ;
- Ruff, Mypy, Pytest, ESLint, TypeScript et build Next.js réussis.

Les endpoints métier appliqueront ce moteur à partir de la Phase 3. Aucune règle
Enterprise, aucun moteur ABAC avancé et aucun modèle de formulaire ou rapport
n'est introduit dans cette phase.
