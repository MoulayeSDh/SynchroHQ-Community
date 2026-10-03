# Phase 4 — Collecte hors ligne et synchronisation

## Périmètre

La page `/collect` conserve les formulaires publiés, brouillons, opérations et
fichiers dans IndexedDB. Le jeton d'accès reste uniquement en mémoire. Cette
phase manipule des copies de travail, sans créer de `Report` ou `ReportRevision`.

- Chaque brouillon conserve sa version exacte de formulaire.
- L'envoi fige les réponses et un identifiant d'opération persistant.
- PostgreSQL enregistre la copie, son accusé et l'audit dans une transaction.
- Un renvoi identique retrouve l'accusé ; un contenu différent avec le même
  identifiant est rejeté. Un conflit ne remplace pas les réponses locales.
- Les droits sont réévalués avant toute nouvelle écriture. Un accusé déjà
  enregistré reste récupérable par son propriétaire authentifié.
- Les preuves JWT hors ligne expirent strictement. Après un rejet explicite,
  une nouvelle preuve obtenue après réauthentification peut remplacer l'opération
  sous un nouvel identifiant. Une version retirée ne reçoit aucune nouvelle preuve.
- Une preuve encore valide émise avant le retrait permet de terminer le travail.

## Pièces jointes

JPEG, PNG et PDF, de 1 octet à 10 Mio dans l'interface. L'API applique également
`ATTACHMENT_MAX_BYTES`. Les octets et métadonnées sont conservés localement ;
l'API vérifie la taille et SHA-256 avant de stocker l'objet dans MinIO/S3.
PostgreSQL ne conserve que les métadonnées, la clé objet et l'accusé.

L'envoi des fichiers suit l'accusé du brouillon. Une panne du stockage objet
laisse le fichier à réessayer. Les nouvelles tentatives utilisent la même clé,
et un accusé déjà enregistré ne provoque pas un nouvel upload. Les métadonnées
doivent correspondre exactement à celles du brouillon reçu.

La duplication attribue de nouveaux identifiants au brouillon et à ses fichiers.
Elle nécessite que le formulaire soit encore dans le catalogue publié local.
Le retrait de fichier est interdit après expiration de la session locale,
pendant son envoi ou après sa réception.

## Environnement local

Les anciennes images publiques MinIO ne sont plus accessibles. Le Dockerfile
`deployments/docker/minio/Dockerfile` compile la version initialement retenue
`RELEASE.2025-04-22T22-12-26Z` depuis le commit officiel
`0d7408fc9969caf07de6a8c3a84f9fbb10a6739e`, vérifié pendant la construction.
Cette image sert à la validation locale ; le projet MinIO Community est archivé.
Source : https://github.com/minio/minio

Les ports MinIO 9000/9001 et PostgreSQL 5434 sont limités à localhost.
Le premier build MinIO télécharge le compilateur et les dépendances Go.

## Reproduire le gate

Depuis la racine du dépôt :

```powershell
docker compose up -d --build backend frontend
docker compose exec -T backend alembic upgrade head
docker compose exec -T backend alembic check
docker compose exec -T -e FORMS_DEMO_API_URL=http://localhost:8000 backend python -m app.modules.forms.demo
docker compose cp backend:/app/.local/forms-demo.json .local/forms-demo.json
```

Depuis `community/frontend`, exécuter `pnpm typecheck`, `pnpm lint`, `pnpm test`
et `pnpm test:e2e`. Le build Next.js est inclus dans la construction Docker.
Le test navigateur ajoute un PDF hors connexion, recharge la page hors ligne,
puis se réauthentifie et attend les accusés du brouillon et du fichier.

Après Playwright, depuis la racine :

```powershell
docker compose cp scripts/development/verify-offline-storage.py backend:/tmp/verify-offline-storage.py
docker compose exec -T -e PYTHONPATH=/app/community/backend backend python /tmp/verify-offline-storage.py
```

Ce contrôle relit les octets réellement présents dans MinIO, vérifie leur SHA-256,
et envoie simultanément deux copies d'une opération puis deux copies d'un fichier.
Il attend un seul enregistrement et des accusés identiques. Les essais conservent
leurs brouillons et fichiers de démonstration pour inspection.

Les contrôles Python se lancent depuis `community/backend` avec le Python de
`.venv` : `-m ruff check app tests migrations`, `-m mypy app`, `-m pytest -q`.

## Limites du pilote

- L'atelier utilise encore un jeton manuel ; ce n'est pas un écran de connexion final.
- Le stockage local dépend du navigateur et de l'appareil de confiance.
- L'export JSON contient les réponses et métadonnées, pas les octets des fichiers.
- La validation métier du formulaire reste distincte de l'accusé de réception.
- Un nettoyage d'objets orphelins après panne entre S3 et PostgreSQL reste à prévoir
  pour l'exploitation ; une reprise du même upload réutilise sa clé déterministe.

## Validation finale — 29 septembre 2026

Phase 4 validée pour le pilote local :

- 41 tests backend et 22 tests frontend réussis.
- Ruff, Mypy (28 modules), TypeScript et ESLint réussis.
- Construction Docker backend, frontend et MinIO réussie ; build Next.js réussi.
- Migration `0005_offline_attachments` appliquée ; `alembic check` sans divergence.
- Deux scénarios Playwright réussis : moteur de formulaires et collecte hors ligne
  avec PDF, rechargement sans réseau et accusés après reconnexion.
- Octets du PDF navigateur relus dans MinIO et vérifiés par taille et SHA-256.
- Doubles envois simultanés du brouillon et du fichier : un enregistrement chacun,
  avec des accusés identiques.

La phase suivante concerne les rapports et leur confirmation. Les limites du
pilote décrites plus haut restent applicables.
