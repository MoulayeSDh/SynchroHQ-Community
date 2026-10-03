# État des phases SynchroHQ

Roadmap révisée le 1er octobre 2026. Référence Core : `8c24a89` / `phase6-core-complete`.

| Phase | Intitulé | Statut |
|---|---|---|
| 0 | Specification V1 | FROZEN |
| 1 | Foundation | DONE |
| 2 | Identity & Authorization | DONE |
| 3 | Forms Engine | DONE |
| 4 | Offline-first & Sync | DONE |
| 5 | Reports & Accountability | DONE |
| 6 | Hierarchical Workflow | DONE |
| 7 | UX/UI & Application Shell | DONE — gate local auteur/responsable/lecteur, FR / AR / EN |
| 8 | Analytics & Geospatial | DONE — pilote local, gates 8A à 8D validés |
| 9 | Production Hardening & Pilot | NEXT |
| 10 | AI & Semantic Intelligence | DONE — gate local, extension Enterprise facultative |

La Phase 7 construit une interface cohérente, responsive et accessible autour du Core existant.
Son gate couvre les parcours auteur, responsable territorial et lecteur central en FR/AR/EN,
avec RTL arabe, sans manipulation manuelle des URLs ou de l’API.

La Phase 8 produit les KPI officiels, séries par période, comparaisons territoriales et points GPS autorisés depuis PostgreSQL/PostGIS. Le dashboard et la carte fonctionnent en FR/AR/EN sur mobile et desktop. Le gate croisé Analytics/Geo réconcilie 10 obligations (8 à temps, 1 tardive, 1 manquante) et 2 points GPS dans une base pilote isolée ; un compte d'une autre Wilaya n'accède à aucune de ces données.

La Phase 10 concerne une extension Enterprise facultative, maintenue dans un
dépôt privé distinct. Aucune clé, image ou dépendance Enterprise n'est requise
pour installer et exploiter Community.

La Phase 9 couvre l’authentification de production, les secrets, le packaging, les
backups/restores, le durcissement et le pilote prolongé. Le dépôt Community
valide son propre parcours d'installation et de restauration.
