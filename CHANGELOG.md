# Journal des modifications

## 1.1.15 — 2026-07-24

- Place « Accès réservé aux membres » sous « Connexion au portail » et centre les deux éléments sur la connexion membre.
- Place « Administration locale » sous « Connexion administrateur » et harmonise le centrage et la taille du titre administrateur.
- Met à jour les titres de fenêtre des deux écrans de connexion.
- Actualise le README et les métadonnées de version pour une publication publique sur GitHub.

## 1.1.14 — 2026-07-24

- Cartes de la liste des services à hauteur naturelle, titres centrés et boutons d’ouverture bleus.
- Boutons de téléchargement du référentiel de couples centrés.
- Titres des connexions membre et administrateur centrés et harmonisés ; texte de session administrateur simplifié.
- Navigation des services réduite aux accès à la liste des services et à l’administration, avec boutons bleus.
- Ascenseurs visibles et manipulables dans l’éditeur de configuration et les visionneuses de logs.
- Tableau des tâches de fond et cartes d’état/statistiques enrichis par des couleurs sémantiques.
- README actualisé.

## 1.1.13 — 2026-07-23

- Refonte robuste de l’indicateur Internet : contrôles TCP, DNS, HTTPS et ICMP côté serveur, suppression de la dépendance à `navigator.onLine`, seuil de plusieurs échecs avant l’état hors ligne et conservation temporaire du dernier état confirmé.
- Navigation simplifiée sur les trois pages de service et libellés explicites pour le retour à la liste des services et l’accès à l’administration.
- Allègement des cartes de la liste des services et reformulation des deux fiches PDF.
- Agrandissement uniforme des logos dans les en-têtes et fond blanc harmonisé pour la connexion administrateur.
- Administration : courbes CPU individuelles détectées dans `/proc/cpuinfo` et `/proc/stat`, fréquence de rafraîchissement configurable et éditeur JSON avec ascenseurs visibles.
- Ajout de `pieces.scraping.default_enabled_sites` pour choisir les fournisseurs cochés par défaut.
- README entièrement actualisé avec les sept nouvelles captures, les prérequis matériels, les services, la sécurité, les licences, les mises à jour et toutes les commandes de `run_server.sh`.

## 1.1.11 — 2026-07-23

- Ajout de TW-Oldtimerteile au comparateur et au bloc de coordonnées des fournisseurs.
- Nouveau scraper limité à la racine Opel GT, aux catégories directes et à leur pagination : comptage préalable des 11 catégories attendues, exclusion de « J’en ai besoin, je le veux ! » et absence stricte de requête vers les fiches individuelles.
- Extension de la sélection et des statuts à huit fournisseurs, avec tests dédiés du comptage, de l’exclusion, de l’extraction des cartes et du parcours sans fiches produit.

## 1.1.10 — 2026-07-23

- Connexion membre : suppression de l’indication « session inactive », commandes Internet/thème/taille regroupées sur une seule ligne et retrait du cadre décoratif.
- Harmonisation en gras des commandes communes sur toutes les pages.
- État Internet rendu immédiatement lisible par un fond vert ou rouge ; compte à rebours coloré en vert, orange ou rouge selon le tiers de durée restant.
- Élargissement de la page de sélection des services à 1 440 px afin de conserver la devise sur une ligne sur ordinateur.
- Nettoyage de la gestion des écouteurs réseau lors des arrêts et redémarrages du contrôle de connectivité.
- README, tests de déploiement et rapport de validation mis à jour.

## 1.1.9 — 2026-07-23

- Harmonisation des commandes d’état et d’accessibilité sur les connexions, la liste des services, les services et l’administration.
- Mémorisation commune et persistante du mode clair/sombre et de la taille du texte.
- Renommage des boutons de navigation et des titres de fenêtre demandés.
- Nouvelle gestion de fin de session lors de l’expiration et de la fermeture du navigateur, sans interrompre les navigations internes.
- Page Bulletins : titre compact sur une ligne et bouton de déconnexion blanc.
- Page Couples : boutons documentaires bleu et blanc, traits des repères divisés par deux et clignotement du repère sélectionné.
- Page Services : en-tête unifié, commandes déplacées en haut et anciennes actions de bas de page supprimées.
- Administration : en-tête unifié, commandes claires, onglets centrés, suppression d’Actualiser et graphique interactif CPU/RAM actualisé dynamiquement.
- Fond clair harmonisé sur l’ensemble des pages et socle responsive conservé.
- README et validation actualisés.

## 1.1.8 — 2026-07-23

- ajout d’un séparateur vertical déplaçable entre la liste des pièces et la vue éclatée sur la page Couples de serrage ;
- ajout d’un bouton permettant de masquer ou de réafficher entièrement le volet « Pièces et couples » ;
- regroupement des téléchargements PDF des couples, Excel des couples et PDF de visserie dans le bloc « Référentiel embarqué » ;
- suppression du bloc autonome « Documentation pratique » et du texte de version du référentiel.

## 1.1.7 — 2026-07-22

- agrandissement de 50 % des cercles de repérage des vues éclatées ;
- hauteurs identiques pour les volets « Pièces et couples » et « Vue affichée » ;
- fond des lignes teinté selon la catégorie de la pièce ;
- déplacement du mode d’emploi complet en tête du référentiel et ajout de la conversion N·m vers m·kg ;
- ajout des téléchargements protégés du PDF complet des couples et du tableur Excel source ;
- ajout d’un socle responsive commun aux pages du portail ;
- préparation du dépôt GitHub avec `.gitattributes`, guide de contribution et CI corrigée ;
- suppression de la fonction JavaScript inutilisée `authErrorMessage`.

## 1.1.6 — 2026-07-22

- Refonte de l’affichage de `run_server.sh` : en-tête synthétique commun à toutes les commandes, couleurs compatibles avec `NO_COLOR`, grandes étapes numérotées et masquage des sorties techniques sans intérêt.
- Conservation stricte des saisies interactives existantes, notamment le choix Cloudflare, la saisie masquée du jeton et la définition du mot de passe administrateur.
- Correction du positionnement des repères de la page Couples de serrage : remplacement des marqueurs HTML dépendant de styles en ligne bloqués par la CSP par un calque SVG dimensionné sur la résolution native de chaque vue.
- Enregistrement des coordonnées vérifiées en pixels et en pourcentage, centrées sur les numéros imprimés des trois vues, avec conservation des couleurs par catégorie et des interactions bidirectionnelles.
- Suppression des états JavaScript, styles et commentaires devenus obsolètes, des artefacts temporaires de test et du chargement WebSocket inutilisé ; README et rapport de validation mis à jour.

## 1.1.5 — 2026-07-22

- Mise en évidence en gras et en rouge du contrôle initial de disponibilité des boutiques, avec demande explicite de patienter quelques secondes.
- Recentrage précis des marqueurs Couples de serrage sur les numéros imprimés dans chacune des trois vues éclatées.
- Attribution d’une couleur daltonien-compatible par catégorie ; les repères communs à plusieurs catégories utilisent un cercle segmenté.

## 1.1.4 — 2026-07-22

- Remaniement complet de la page Couples de serrage en deux volets synchronisés : liste des pièces et couples à gauche, vue éclatée interactive à droite.
- Ajout du sélecteur dynamique de vue, de la sélection bidirectionnelle pièce ↔ repère numéroté et de la désambiguïsation lorsqu’un repère correspond à plusieurs lignes.
- Affichage simultané de tous les repères disposant d’un couple dans la vue active, avec mise en évidence distincte de la pièce sélectionnée.
- README mis à jour.

## 1.1.3 — 2026-07-22

- Ajout, pendant `sudo ./run_server.sh install`, d’un assistant facultatif pour Cloudflare Tunnel : explication du parcours de récupération du jeton, saisie masquée, installation depuis le dépôt officiel, création du service `cloudflared` et redémarrage automatique après chaque reboot.
- Ajout en haut de la page Couples de serrage d’un accès visible à la liste de visserie Opel GT exclusivement en français, servie par une route authentifiée.
- Ajout d’une mise à jour hebdomadaire configurable des paquets APT avec prise en charge des nouvelles dépendances, puis redémarrage de la machine ; planification par défaut le mercredi à 00:00.
- Ajout des paramètres `maintenance.weekly_package_update_*` et de l’action « Appliquer et redémarrer » dans l’administration pour valider le JSON, régénérer le timer et redémarrer le portail.
- README, documentation systemd, manifeste et tests de déploiement mis à jour.

## 1.1.2 — 2026-07-21

- Renommage du service « Inventaire avant déplacement » en « Fiche d’inventaire » sur la page de sélection.
- Passage de la durée de session par défaut de 10 à 30 minutes, avec migration automatique de l’ancienne valeur par défaut lors d’une mise à niveau.
- Ajout d’une correspondance visuelle bidirectionnelle entre les lignes de couples et les repères des vues éclatées : marqueurs superposés, centrage du repère, détail des lignes associées et retour direct au tableau.
- Génération dynamique des colonnes, filtres, cartes, marqueurs et légendes à partir du référentiel, afin de préparer l’ajout de nouvelles vues.
- Saut de ligne ajouté avant « Fais avec amour ❤️ » dans le pied de page Couples de serrage.
- README et tests de non-régression mis à jour.

## 1.1.1 — 2026-07-21

- Remplacement de l’inventaire embarqué par la version recto/verso correcte fournie avec le bundle.
- Réduction de l’étalement vertical sur smartphone et tablette : services, navigations et collections denses parcourables horizontalement.
- Conservation des tableaux Bulletins, Couples et Pièces dans des zones de défilement horizontal compactes, avec en-tête et première colonne fixes.
- Mise à jour du README et ajout de contrôles de non-régression sur les ressources et règles responsive.

## 1.1.0 — 2026-07-21

- Ajout de trois services sur la page de sélection : Couples de serrage, Fiche d’intervention et Inventaire avant déplacement.
- Nouvelle page protégée des couples de serrage, avec recherche, filtres par section et vue, tableau responsive et accès aux trois vues éclatées.
- Intégration fidèle des 61 valeurs du tableur fourni et de leurs correspondances avec les repères des vues 1, 2 et 3.
- Distribution protégée des deux formulaires PDF et des vues éclatées, sans exposition par le montage statique public.
- Navigation, documentation, manifeste et tests de déploiement mis à jour ; chemins HTML, API, PDF et images vérifiés.

## 1.0.10 — 2026-07-21

- Clarification de l’expiration de session sur les pages de connexion et affichage uniforme de « Temps restant avant déconnexion ».
- Lecture interprocessus fiable de l’état catalogue écrit par le worker, sans conversion prématurée des fournisseurs en échec à 100 %.
- État neutre à 0 % avant le démarrage effectif de la récupération, bleu pendant le traitement, vert à la fin et rouge uniquement en cas d’échec.
- Passage au vert de la progression de téléchargement des bulletins à 100 %, sur la page Services comme sur la page Bulletins.
- Extension des tests JavaScript et API sur les états transitoires et terminaux des deux services.

## 1.0.9 — 2026-07-21

- Suppression de la migration automatique des anciens bundles pendant l’installation, afin qu’une réinstallation après `uninstall --purge` reparte réellement sans PDF, index ni catalogue réimporté.
- Migration des anciens bundles conservée sous forme de commande explicite `run_server.sh migrate`.
- Première récupération des catalogues mise en file en arrière-plan uniquement lors d’une installation vierge sans catalogue exploitable ; mises à jour périodiques toujours limitées au dimanche à 00:00.
- Logique uniforme sur la page Services : barres visibles et bouton désactivé uniquement pendant une récupération ou une indexation ; barres masquées et bouton réactivé dès la fin.
- Recherche Bulletins et Pièces bloquée côté interface et côté API pendant leurs traitements respectifs.
- Purge étendue au répertoire personnalisé défini par `storage.data_dir`.
- README, documentation systemd et tests de déploiement mis à jour.

## 1.0.8 — 2026-07-21

- Suppression définitive du déclenchement des catalogues depuis la page Services et depuis le démarrage ou l’installation du portail.
- Planification exclusive des catalogues le dimanche à 00:00 en Europe/Paris, sans rattrapage au redémarrage et sans délai aléatoire.
- Annulation automatique, lors d’une mise à niveau, des anciennes tâches catalogues restées en attente ou en cours ; conservation intégrale des catalogues valides.
- Vérification de l’absence d’effet de bord de la page Services sur les catalogues et les bulletins.
- Sessions membre et administrateur communes de 10 minutes par défaut, paramétrables par `sessions.duration_minutes`.
- Affichage dynamique du temps restant sur toutes les pages authentifiées et information de durée sur les deux pages de connexion.
- Restitution des droits du répertoire extrait à l’utilisateur ayant invoqué `sudo`, afin de permettre sa suppression sans privilèges après désinstallation.
- Mise à jour de la documentation et extension des tests de déploiement, planification, expiration et migration.
- Fermeture systématique des connexions SQLite de courte durée et validation de la suite sans avertissement de ressources.

## 1.0.7 — 2026-07-19

- Activation du comparateur dès qu’au moins un catalogue fournisseur valide est disponible.
- Un fournisseur indisponible ou en échec est désactivé individuellement sans bloquer les autres catalogues.
- Séparation de la disponibilité des catalogues et de leur fraîcheur : les contrôles automatiques restent planifiés sans invalider les instantanés exploitables.
- Ajout de tests de non-régression pour le cas de six catalogues valides sur sept.

## 1.0.6 — 2026-07-19

- Suppression de la mention « Portail privé » dans l’en-tête de la page de choix des services.
- Reprise immédiate des tâches catalogues laissées en cours après un redémarrage du worker.
- Normalisation à 100 % des fournisseurs terminés ou interrompus afin d’éviter le blocage global à 73 %.
- Remplacement des largeurs inline, refusées par la politique CSP, par des éléments HTML `progress`.
- Barres vertes pour les catalogues prêts, rouges pour les fournisseurs indisponibles ou en échec, et grises pour les états en attente ou absents.
- Nettoyage des règles CSS de progression devenues inutilisées et correction de l’exemple de limitation des connexions dans le README.

## 1.0.5 — 2026-07-18

- Taille du slogan de la page des services alignée sur celle des deux services.
- Suppression des commandes utilisateur de mise à jour des bulletins et des catalogues.
- Fréquence des récupérations automatiques affichée sur la page de choix.
- Limitation configurable à cinq tentatives de connexion sur cinq minutes pour les comptes membre et administrateur.
- Statistiques administrateur enrichies avec les adresses IP, pays, tentatives, succès, refus et blocages.

## 1.0.4 — 2026-07-17

- Uniformisation des en-têtes, des commandes d’affichage et de la navigation des pages de services, avec des commandes non tronquées sur bureau et mobile.
- Page de choix dynamique avec progression des bulletins et des catalogues, fournisseur par fournisseur.
- Désactivation des services tant que leurs données ne sont pas prêtes.
- Déclenchement automatique de la récupération des catalogues depuis la page de choix, avec nouvelle tentative temporisée après une indisponibilité réseau.
- Badge de disponibilité Internet ajouté à la page des bulletins.
- Recherche bulletins désactivée pendant l’indexation, avec affichage du fichier en cours.
- Recherche pièces désactivée pendant la récupération des catalogues.
- Suppression du sélecteur de langue et des mentions nominatives de session.
- Nettoyage du code de traduction devenu obsolète.

## 1.0.3 — 2026-07-17

- Autorisation de la connexion membre et administrateur en HTTP depuis `localhost` et les adresses privées du réseau local.
- Maintien du refus de l’authentification HTTP lorsqu’une adresse cliente publique accède directement au portail.
- Clarification du texte de la page de connexion et de la documentation concernant l’expiration de session et l’usage local.

## 1.0.2 — 2026-07-17

- Correction de l’écoute réseau après installation : le portail écoute désormais par défaut sur `0.0.0.0:8080`.
- Migration automatique des configurations 1.0.x restées sur le réglage par défaut `127.0.0.1`, sans modifier les configurations explicites de reverse proxy.
- Affichage d’une URL réseau réellement utilisable à la fin de l’installation.

## 1.0.1 — 2026-07-17

- Correction du chemin d’import Python utilisé par l’installation et les commandes d’administration, afin que `app.manage` soit résolu depuis `/opt/portail-entraide-opel-gt` quel que soit le répertoire courant.

## 1.0.0 — 2026-07-17

- Fusion du bundle bulletins 1.4.2 et du comparateur 1.4.0.
- Authentification membre et navigation communes.
- Page intermédiaire de sélection du service.
- Serveur FastAPI unique avec routes métier séparées.
- File de tâches SQLite persistante avec leases, heartbeat, déduplication et reprise.
- Worker OCR et worker catalogues séparés.
- Recherche maintenue pendant les mises à jour lorsque des données valides existent.
- Fin de synchronisation à 100 % même lorsqu’un élément échoue.
- Administration commune, configuration sans secrets et socket privilégié limité.
- Migration idempotente des anciennes données.
- Installation, sauvegarde, restauration transactionnelle et purge unifiées.
- Préflight réseau non bloquant et journalisation rotative du serveur et des workers.
- Interface validée sur bureau et mobile avec API entièrement préfixée par service.
