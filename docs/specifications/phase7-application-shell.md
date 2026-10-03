# Phase 7 — UX/UI & Application Shell

Référence Core : `8c24a89`, tag `phase6-core-complete`.
Roadmap : Analytics & Geospatial est désormais la Phase 8 ; Production Hardening & Pilot la Phase 9 ; AI la Phase 10.

## Interface

- Session commune aux pages : accueil, collecte, rapports, inbox, formulaires, administration et profil.
- Sidebar desktop, menu mobile, parcours tablette et styles logiques compatibles RTL.
- Identité générique institutionnelle et technologique : réseau de nœuds bleu/vert, accents cyan, nom SynchroHQ.
- Navigation et actions selon les permissions effectives du serveur. Les droits sont aussi vérifiés par chaque API.
- État réseau permanent, file locale de synchronisation, blocages, notifications opérationnelles et reprise.
- Administration : annuaire **en lecture seule**, protégé par la permission `administration:read`, restreint au tenant et au périmètre. La gestion complète des comptes n’est pas implémentée dans ce lot UI.
- Rapport consultable avec les libellés de sa définition immuable, historique de révisions et preuve technique.
- Traductions FR/AR/EN, direction RTL en arabe. Les saisies, noms d’organisations et commentaires ne sont pas traduits automatiquement.
- Les nouveaux formulaires acceptent FR/AR et un dictionnaire EN complet optionnel. Les anciennes versions publiées restent immuables ; les libellés connus du pilote ont une traduction d’affichage EN.

## Connexion du pilote

`DEMO_LOGIN_ENABLED=false` par défaut. La connexion synthétique est aussi refusée si `APP_ENV` n’est pas `development`, même si le drapeau est activé.
Les seuls comptes autorisés appartiennent au namespace UUID déterministe Phase 6B ; un identifiant libre ne peut pas être utilisé.
Le pilote local utilise `DEMO_LOGIN_ENABLED=true` dans son `.env` non suivi par Git. Une migration ajoute la permission d’annuaire et le seed ne l’attribue qu’à l’admin synthétique.

Le jeton API reste en mémoire et expire après une heure pour les comptes synthétiques. La navigation interne conserve cette session. Un rechargement complet nécessite une reconnexion en ligne ; une fenêtre locale vérifiée permet de poursuivre hors connexion avec les données déjà préparées. Déconnexion : effacement de la sélection de session, conservation des brouillons appartenant à leur auteur.

Le cache du service worker ne contient que les shells publics et les assets du build, jamais les réponses API. Les données métier restent dans IndexedDB selon leur propriétaire. Le dernier profil et les permissions d’affichage mises en cache sont liés au tenant et à la fenêtre locale.

L’authentification de production reste un chantier Phase 9. La connexion de démonstration ne constitue pas une authentification de production.

## Gate ciblé

Un scénario navigateur vérifie les trois profils, les trois langues et les largeurs mobile/tablette/desktop :

1. Connexion auteur par l’écran normal, navigation mobile, formulaire en anglais, confirmation hors ligne et réception après reconnexion.
2. Responsable territorial : consultation depuis l’inbox, commentaire, demande de correction, absence d’action réservée à l’auteur.
3. Auteur : récupération, passage en arabe, rechargement hors ligne, correction locale et nouvelle confirmation ; reconnexion par l’écran de session, sans saisie manuelle de jeton.
4. Lecteur central : consultation des deux révisions, aucune action d’écriture et navigation limitée à ses droits.
5. Vérification du RTL, de l’absence de débordement horizontal et d’erreur JavaScript.

La preuve du pilote est conservée localement dans `.local/phase7-gate.json`, avec captures mobile, arabe et desktop. Elle ne contient pas de jeton.

Validation proportionnée : trois tests backend sur les nouvelles frontières de permission, un test de compatibilité du moteur de formulaires avec EN, typage, lint, build et ce parcours navigateur. Les suites Core déjà validées ne sont pas relancées sans changement qui le justifie.

## État validé

Gate local passé : 2026-09-29T08:54:50.407Z ; auteurs/responsable/lecteur, FR/AR/EN, RTL et largeurs 390/1024/1440.
Contrôles : TypeScript, ESLint, Ruff, mypy, build Next.js, trois tests de permission et un test de compatibilité EN.
Le moteur métier de synchronisation, les payloads canoniques et les anciennes révisions ne sont pas modifiés.
