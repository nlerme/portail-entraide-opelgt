# Journal des modifications

## 1.1.33 — 27 octobre 2026

- Leboncoin : suppression des arrêts prématurés sur les compteurs par vendeur et le nombre de pages annoncé ; fin confirmée après une page courte malgré un total périmé, dédoublonnage indépendant et protection contre les répétitions sans progrès.
- Suppression du plafond inadapté de vingt pages, bornes de sécurité et de durée conservées ; retour aux en-têtes, cookies et paramètres de recherche standard du SDK avec initialisation bornée. Les refus HTTP restent signalés et ne sont pas présentés comme définitivement supprimés.
- Version en pied de toutes les pages, séparateur horizontal et lien vers le dépôt avec icône GitHub locale sous licence MIT. README, vérifications et références actives alignés.

## 1.1.32 — 27 octobre 2026

- Leboncoin : en-têtes natifs du profil HTTP, suppression de l’identité d’application mobile aléatoire et de l’appel initial non borné à la page d’accueil.
- Recherche commune aux particuliers et professionnels, type de vendeur lu dans la réponse et demande de 100 résultats par page pour réduire le nombre d’appels. Transmission du curseur, décalage adapté à la taille réellement reçue, total explicite et suggestions élargies désactivées.
- Conservation des observations lors d’une interruption réseau, tests traversant le véritable SDK jusqu’au transport HTTP, vérification de la reprise du cache et version/documentation alignées. Les refus du site restent signalés.

## 1.1.31 — 27 octobre 2026

- Numéro de version visible sur les formulaires de connexion membre et administrateur, avec le même style et un contrôle de cohérence avec le fichier VERSION.
- Leboncoin : pagination fondée sur le compteur du groupe de vendeurs et les lignes reçues, indépendamment du dédoublonnage des annonces ; prise en compte de la dernière page annoncée et arrêt explicite si une page se répète intégralement.
- Régression reproduisant onze annonces et l’ancien échec à vingt pages ; conservation des données/préférences et actualisation de la réussite complète vérifiées. README, tests et version alignés.

## 1.1.30 — 27 octobre 2026

- Bulletins : première récupération déclenchée à l’installation sans navigateur, puis collecte incrémentale chaque dimanche à 02:00 (Europe/Paris) et mise en file des OCR nécessaires.
- Saisie masquée du compte membre à l’installation, conservation dans le fichier de secrets protégé et suppression lors de la purge. Les connexions au portail ne déclenchent plus de récupération.
- Planification persistante, verrou anti-concurrence, reprise des données existantes et progression partagée avec l’interface ; documentation, tests et version alignés.

## 1.1.29 — 27 octobre 2026

- Correction de l’horodatage futur du fichier de test géographique dans le ZIP livré.
- Installation : les dates de modification futures sont plafonnées à l’heure du serveur pendant la copie, sans changer les fichiers sources ni masquer les avertissements de `tar`.
- Test de copie réelle avec un fichier et des répertoires datés dans le futur ; documentation et références actives de version alignées.

## 1.1.28 — 27 octobre 2026

- Carte des petites annonces : le budget de géolocalisation compte uniquement le temps des appels géographiques, au lieu d’expirer pendant la collecte des annonces. Délai des appels adapté aux réponses lentes.
- Réparation des positions manquantes des annonces déjà enregistrées avant l’accès aux sources, sans supprimer le cache ni modifier les numéros, favoris ou historiques.
- Reconnaissance des codes postaux intégrés aux libellés, résolution des communes partageant un code postal sans troncature à dix résultats et reprise des anciens échecs de cache. Les échecs temporaires ne restent plus bloqués une journée.
- Tests de régression, vérifications avec 21 communes et 21 repères dans l’interface ; README et version 1.1.28 alignés.

## 1.1.27 — 26 octobre 2026

- Pied de page identique sur Bulletins, Comparateur de pièces, Petites annonces et Couples de serrage : même inventaire de 46 badges locaux, séparation, copyright et mention « Fait avec amour ❤️ ». Styles communs et suppression des anciennes variantes.
- Adaptation des sept pages web aux petits écrans et au texte agrandi : taille de police effective dans Bulletins, barre de sélection des vues, métriques d’administration et commandes de connexion sur petit écran.
- README, tests et version 1.1.27 alignés ; aucune modification des collecteurs, traitements serveur ou données métier.

## 1.1.26 — 25 octobre 2026

- Petites annonces : compteurs et couleurs par source, numéros persistants, filtres de budget/modèle/département, nouveautés, favoris et annonces masquées par compte, historique des prix et regroupement facultatif des doublons possibles.
- Actualisation manuelle en arrière-plan avec limite globale de 30 minutes, publication source par source et maintien de l’accès pendant les collectes ; planification quotidienne à 02:00 conservée.
- Résumé ntfy facultatif des nouveautés et baisses des favoris, fusionné avec la file existante et soumis à sa limite globale d’envoi, sans notification historique artificielle à la migration.
- Carte OpenStreetMap/Leaflet embarqué, repères colorés numérotés et récapitulatifs liés à la liste ; cache des centres de communes via l’API publique française et signalement des lieux non localisables.
- Documentation, licences, tests et version 1.1.26 alignés ; filtres des collecteurs et correctifs précédents conservés.

## 1.1.25 — 24 octobre 2026

- Leboncoin : profil HTTP explicite et configurable, excluant le profil Android Chrome 131 déconseillé par l’auteur de lbc ; temporisation minimale de deux secondes et absence de nouvelle tentative après refus.
- Conservation des annonces valides reçues avant une interruption ; fusion avec les anciennes annonces non revérifiées, dédoublonnage, protection contre une chute anormale et avertissement de collecte incomplète. La date de dernière réussite complète reste exacte.
- Tests du profil, des interruptions et de la conservation des données ; README et version 1.1.25 alignés. Un refus DataDome reste possible et n’est pas présenté comme définitivement supprimé.

## 1.1.24 — 24 octobre 2026

- Bulletins : remplacement de l’iframe PDF, bloquée par les en-têtes du portail et dépendante du lecteur natif, par une visionneuse PDF.js locale dans la fenêtre existante. Navigation, zoom, page de recherche, adaptation aux écrans mobiles, annulation des rendus et nettoyage à la fermeture.
- Maintien des PDF derrière l’authentification et des protections contre les iframes ; autorisation WebAssembly limitée à la page Bulletins et aux ressources du moteur PDF.
- Moteur PDF.js legacy, polices, CMaps, décodeurs et licences embarqués ; documentation, tests et version 1.1.24 alignés.

## 1.1.23 — 24 octobre 2026

- Ajout en tête du README des badges des langages et formats, des bibliothèques applicatives, de la collecte, de l’OCR, de l’hébergement, des notifications et des outils de développement et de validation présents dans le bundle.
- Version 1.1.23 propagée aux métadonnées, exemples, ressources statiques, tests et instructions courantes.

## 1.1.22 — 24 octobre 2026

- README réorganisé : historique retiré de l’introduction, galerie limitée aux captures, description et tableau des quatre sources déplacés dans Services inclus, sections ntfy et Cloudflare résumées, section Publication sur GitHub supprimée et mention « Fabriqué avec amour ❤️ » ajoutée à l’auteur.
- Suppression d’utilitaires internes, de constantes et d’imports sans appelant dans le bundle ; conservation des routes, commandes, collecteurs et mécanismes de compatibilité utilisés.
- Version 1.1.22 propagée aux métadonnées, exemples, ressources statiques, tests et instructions courantes.

## 1.1.21 — 23 octobre 2026

- README : remplacement de la capture Liste des services et ajout de la capture Petites annonces fournies ; documentation ntfy alignée sur les nouveaux réglages.
- Administration : onglet Notifications, réglage des identifiants et de l’intervalle ntfy, sans retour des secrets au navigateur et avec écriture privilégiée limitée.
- Notifications : regroupement des événements et au maximum un message par intervalle de 1 à 365 jours, par défaut 24 heures ; limite persistante après redémarrage, conservation des événements différés.
- Version 1.1.21 propagée dans le bundle.


## 1.1.20 — 23 octobre 2026

- Notifications ntfy : configuration interactive en début d’installation, jeton ou mot de passe masqué, surveillance indépendante, file persistante en cas de coupure, détection des rétablissements et arrêt/purge complets.
- Leboncoin : utilisation du client Python etienne-hd/lbc 1.1.7 et de ses recherches par type de vendeur, pagination et délais bornés. Les refus DataDome restent visibles ; aucune réussite d’accès n’est présumée.
- Petites annonces : ajout du prix et de la devise, de Classic Number et de Classic Trader, avec filtrage France et exclusion des GT modernes.
- Version 1.1.20 propagée aux métadonnées, ressources statiques, exemples, tests et documentation.


## 1.1.19 — 2026-10-23

- Sixième service « Petites annonces » : Opel GT 1100, 1900 et GT/J d’époque en France, sources lesAnciennes et Leboncoin, sélection initiale de toutes les sources, cartes avec lien direct et cinq tris réversibles. Informations absentes et restrictions d’accès signalées explicitement.
- Collecte quotidienne à 02:00 Europe/Paris par timer systemd, première collecte en arrière-plan à l’installation, conservation par source en cas d’échec, et verrou interprocessus. Pendant la mise à jour, accès désactivé depuis Services, cartes masquées et annonces exclues de l’API.
- GT Teile : traduction groupée après la collecte des pages, cache persistant et reprise des traductions précédentes ; appels réseau et concurrence bornés, options CLI appliquées et durée totale maximale de trente minutes. Les prix et disponibilités restent actualisables si le traducteur est indisponible.
- Version 1.1.19 propagée dans le bundle ; README aligné sur les services, les sources et leurs limites, l’installation et les planifications. Tests ciblés ajoutés.

## 1.1.18 — 2026-10-23

- Progression réelle pour les huit catalogues : compteurs de pages, catégories, pièces et traductions, partagés entre threads et processus et relayés pendant l’exécution des scrapers. La progression ne régresse pas et 100 % reste réservé au résultat final après contrôle du catalogue.
- Arrêt des groupes de processus à l’expiration du délai maximal, pour terminer aussi les workers des scrapers utilisant plusieurs processus ; conservation du catalogue précédent et nettoyage des instantanés de progression.
- Désinstallation Cloudflare : arrêt de la surveillance avant le connecteur, arrêt et désactivation systématiques de `cloudflared.service` avec `--purge`, même pour les anciennes installations, et erreur explicite si un service ne peut être arrêté ou désactivé.
- Version portée à 1.1.18 dans les métadonnées, commandes, API, scrapers, paramètres par défaut, ressources web et documentation. Le fichier `VERSION` est la référence commune à l’application, au script serveur et aux scrapers ; les tests vérifient la cohérence des autres fichiers.
- Tests ciblés de progression, concurrence, délais et désinstallation simulée ; maintien des corrections antérieures.

## Correctif Edelschmiede — 2026-10-23 (base 1.1.17 corrigée)

- Suppression des longues séries de reprises réseau par fiche et par traduction ; parallélisme limité, délais de requête transmis au scraper et suspension des fiches après un refus d’accès ou des erreurs répétées.
- Réutilisation du traducteur borné existant, de son cache et des traductions du dernier catalogue valide. En cas de limitation du service de traduction, les noms originaux sont conservés pour permettre l’actualisation des prix et disponibilités.
- Remontée de l’avancement réel d’Edelschmiede vers le comparateur pendant la récupération, même lorsque les sorties du script sont capturées. Les compteurs de pièces traitées et les phases de traduction et de validation remplacent l’affichage figé à 5 %.
- Délai maximal propre à Edelschmiede de 30 minutes, ou délai global configuré s’il est plus court ; terminaison du sous-processus, nettoyage des fichiers temporaires et conservation du dernier catalogue valide en cas d’échec.
- Tests de régression ciblés et récupération réelle du catalogue complet (277 pièces en environ deux minutes).

## Correctif ciblé — 2026-10-23 (base 1.1.17)

- ATZ et Opel GT Source : suppression de la dépendance bloquante au service de traduction ; arrêt des requêtes de traduction après un refus ou une panne, délais bornés et conservation temporaire des désignations originales.
- Réutilisation des traductions persistantes et du dernier catalogue validé, y compris lors d’une écriture dans un fichier de staging ; les traductions manquantes seront retentées à la prochaine mise à jour.
- Opel GT Source : actualisation réseau des pages du catalogue lors des mises à jour du portail, au lieu de préférer indéfiniment les anciennes pages HTML en cache.
- Cloudflare Tunnel : connexion HTTP/2, redémarrage automatique et surveillance périodique de l’origine et des connexions du tunnel, avec récupération après trois échecs consécutifs, sans visite locale nécessaire.
- Installation et retrait des seules unités de surveillance et de la surcharge Cloudflare gérées par le portail ; ajout de tests de régression pour ces deux corrections.

## 1.1.17 — 2026-08-06

- Remplacement des deux logos JPEG par un PNG à fond réellement transparent et suppression des fonds blancs CSS résiduels sur toutes les pages.
- Harmonisation complète des connexions membre et administrateur : même largeur, mêmes polices, mêmes couleurs, mêmes contrôles et même bouton bleu, sans barre de défilement autour des commandes d’accessibilité.
- Renommage des titres visibles et des titres de fenêtre en « Page de connexion membre » et « Page de connexion administrateur ».
- Reformulation des textes de connexion administrateur et déplacement du rappel de session sous le bouton de connexion.
- Uniformisation en bleu des badges de l’onglet « État général ».
- Couleurs sémantiques et pourcentages pertinents dans l’onglet « Statistiques », avec drapeau du pays pour les connexions par adresse IP.
- Mise à jour du README, du rapport de validation, des tests et des métadonnées de version.

## 1.1.16 — 2026-07-30

- Planification des catalogues portée à trois exécutions hebdomadaires, les lundi, mercredi et vendredi à 02:00 en Europe/Paris.
- Correction globale des libellés des boutons de thème : le bouton indique désormais le mode qui sera activé au clic, sur toutes les pages.
- Correction du scraper TW-Oldtimerteile : suppression d’un appel à une fonction inexistante qui interrompait la collecte avant le parcours des catégories.
- Durcissement du scraper Splendid Parts : session persistante, initialisation des cookies de boutique, débit séquentiel limité et reprises progressives sur les refus transitoires.
- Distinction entre une boutique réellement hors ligne et une boutique joignable qui limite le contrôle automatisé ; les réponses HTTP 401/403/429 et les restrictions robots.txt ne sont plus présentées comme une panne Internet.
- Mise à jour du README, du rapport de validation, des tests et des métadonnées de version.

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
