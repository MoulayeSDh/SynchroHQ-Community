# Utiliser le shell SynchroHQ

Ouvrir `http://localhost:3000`. Choisir FR, العربية ou EN dans l’en-tête.
Le pilote local propose les comptes synthétiques auteur, responsable territorial, responsable régional,
lecteur central, autre Wilaya et administrateur. La navigation et les actions s’adaptent au compte connecté.

## Auteur

1. Choisir **Collecte**, puis un formulaire dans **Nouveau brouillon**. Les formulaires sont préparés automatiquement en ligne ; **Préparer mes formulaires** permet de les actualiser.
2. Les réponses et fichiers sont sauvegardés sur l’appareil. **Finaliser** vérifie les réponses ; **Confirmer définitivement** nécessite une relecture explicite et fige le rapport.
3. Le bandeau indique le réseau et la file de synchronisation. Après reconnexion, la reprise automatique conserve les identifiants d’opération. Les blocages ne suppriment pas la copie locale.
4. Dans **Inbox**, récupérer les demandes de correction en ligne, puis préparer la correction même après rechargement hors connexion. La nouvelle confirmation est une révision ; l’ancienne reste dans l’historique.

## Responsable territorial

**Inbox** affiche les rapports autorisés. Ouvrir **Filtres** pour la période, le territoire, le formulaire, le statut, l’auteur et l’organisation. Les sous-vues **Rapports reçus** et **Corrections** appliquent le filtre correspondant.
Depuis un rapport : consulter le contenu et l’historique, ajouter un commentaire, demander une correction.
Après réception d’une nouvelle révision, revenir dans l’inbox et **Marquer comme examiné**.

Les obligations distinguent explicitement reçu à temps, reçu en retard, manquant et à venir, avec échéance et justification.

## Lecteur central

Consulter **Rapports** ou **Inbox** selon le périmètre autorisé. Les actions d’écriture ne sont pas proposées.
La consultation des données serveur nécessite le réseau ; l’écran explique leur indisponibilité hors connexion.

## Administration et session

**Administration** est un annuaire en lecture seule, réservé à la permission `administration:read`.
**Profil** montre les affectations, organisations, périmètres et la fin de la fenêtre locale.

Le jeton reste en mémoire. La navigation interne conserve la session ; un rechargement complet en ligne nécessite une reconnexion.
Hors connexion, seul le profil précédemment vérifié peut être restauré dans sa fenêtre locale. Pour réenvoyer après un rechargement hors ligne,
cliquer **Se connecter** dans le bandeau une fois le réseau revenu, puis choisir son compte. Les brouillons sont conservés après déconnexion.

La connexion synthétique est réservée au développement. Pour installer le pilote local :

```powershell
# Dans .env : APP_ENV=development et DEMO_LOGIN_ENABLED=true
docker compose up -d --build
docker compose exec -T backend alembic upgrade head
docker compose exec -T backend python -m app.modules.hierarchy.demo
```

En production, ce mécanisme est refusé. La connexion avancée accepte un jeton Community valide pour les intégrations existantes.

Les textes de l’application et du formulaire pilote sont FR/AR/EN. Les noms, commentaires et réponses sont les données saisies ; ils ne sont pas traduits automatiquement.
Pour un nouveau formulaire, fournir sa traduction `en` en plus de `fr` et `ar`. Les anciennes versions publiées restent immuables ; un formulaire personnalisé sans EN utilise ses libellés FR comme repli.
