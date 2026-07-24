# Validation du bundle 1.1.15

Date de fabrication : **24 juillet 2026**.

Ce rapport distingue les contrôles reproductibles exécutés dans l’environnement de fabrication des opérations nécessitant le serveur Linux cible, des identifiants membre réels ou l’accès direct aux fournisseurs.


## Corrections 1.1.15

- Le sous-titre « Accès réservé aux membres » suit désormais le titre « Connexion au portail » et les deux sont centrés.
- Le sous-titre « Administration locale » suit désormais le titre « Connexion administrateur » ; le titre conserve exactement la même échelle typographique que la connexion membre.
- Les titres de fenêtre des connexions membre et administrateur correspondent aux libellés demandés.
- Les métadonnées de version, le README, les tests et les références de cache statique sont cohérents en 1.1.15.

## Corrections 1.1.14

- Les cinq cartes de la liste des services adoptent une hauteur naturelle : les espaces vides précédant les boutons ont été supprimés, les titres sont centrés et les boutons d’ouverture sont bleus.
- Les trois boutons de téléchargement de la page Couples de serrage sont centrés dans toute la largeur du référentiel.
- Les titres « Connexion au portail » et « Connexion administrateur » sont centrés et utilisent la même taille ; le texte de durée de la session administrateur a été remplacé par la formulation demandée.
- Les trois pages de service conservent uniquement « Retour à la liste des services » et « Accès à la page d’administration », avec un fond bleu uniforme.
- L’éditeur JSON et les visionneuses de logs utilisent une ligne de grille contrainte, un ascenseur vertical visible et manipulable, un ascenseur horizontal lorsque nécessaire et une gouttière stable.
- Le tableau des tâches de fond utilise des fonds et badges sémantiques selon l’état ; les cartes d’État général et de Statistiques utilisent des badges colorés distincts.
- Le README et les métadonnées de version ont été actualisés.

## Résultat global

- **225 tests automatisés réussis**, avec tous les avertissements Python traités comme des erreurs.
- Compilation Python et syntaxes Bash, JavaScript et JSON validées.
- Rendus Chromium vérifiés aux largeurs 390, 768 et 1 440 px ; défilement effectif de l’éditeur de configuration et des visionneuses de logs contrôlé avec du contenu long.
- Les règles responsive, les libellés, les ressources, les titres, les contrôles communs et l’absence des anciens textes sont couverts par la suite automatisée. Les sept nouvelles captures fournies ont été intégrées au README.
- Démarrage HTTP réel, création des bases, réponse de `/api/health` en version 1.1.15 et arrêt propre validés.
- Les cinq services sont présents sur la page de sélection : Bulletins, Pièces, Couples de serrage, Fiche d’intervention et Fiche d’inventaire.
- Toutes les commandes de `run_server.sh` affichent le même en-tête (titre, édition, version, auteur et commande), puis des étapes numérotées ; les couleurs sont désactivées hors terminal ou avec `NO_COLOR`.
- Les chaînes exactes des saisies utilisateur Cloudflare et administrateur sont couvertes par des tests de non-régression afin que la refonte de l’affichage ne modifie pas le dialogue d’installation.
- La nouvelle page Couples de serrage charge **61 lignes** réparties entre Moteur, Direction, Suspension avant, Suspension arrière et Freins.
- Les correspondances issues du tableur vers les repères numérotés des vues éclatées sont exposées par `/api/couples`. Les 34 emplacements des trois vues possèdent des coordonnées en pixels et en pourcentage, vérifiées sur les images à leur résolution native et centrées sur les numéros imprimés ; la liste des pièces à gauche, la vue interactive à droite, la sélection bidirectionnelle et la désambiguïsation des repères associés à plusieurs lignes restent opérationnelles.
- Les deux formulaires PDF, la liste de visserie française, le PDF complet des couples, le tableur Excel source, les trois vues éclatées PDF et leurs trois aperçus JPEG sont servis uniquement par des routes authentifiées ; aucun de ces documents n’est monté dans l’arborescence statique publique.
- L’inventaire embarqué correspond au PDF recto/verso de 2 pages fourni pour cette correction ; son empreinte SHA-256 est vérifiée par la suite automatisée.
- Les chemins HTML, API, PDF et image des nouveaux services ont été contrôlés systématiquement.
- Le PDF de visserie française est accessible dans le bloc Référentiel embarqué, juste après les deux documents des couples.
- L’assistant Cloudflare contient le parcours de récupération du jeton, une saisie masquée, le dépôt APT officiel, `cloudflared service install` et l’activation du service au reboot.
- La planification des paquets système est générée depuis `maintenance.weekly_package_update_*` ; les variantes activée, désactivée et personnalisée ont été exécutées avec `systemctl` simulé.
- La commande de maintenance a été exécutée avec `apt-get`, `sync` et `systemctl` simulés : `update`, `upgrade --with-new-pkgs`, puis `reboot` sont appelés dans cet ordre logique, tandis qu’aucune commande n’est exécutée lorsque la fonction est désactivée.
- La page Couples conserve sa structure responsive. Le défaut qui plaçait les cercles en haut à gauche a été reproduit puis corrigé : la politique CSP interdisait les styles HTML en ligne utilisés pour les anciennes coordonnées. Les marqueurs sont maintenant rendus dans un SVG superposé, dont le `viewBox` reprend exactement la largeur et la hauteur natives de l’image ; leur position ne dépend plus de styles en ligne. Les cercles de catégorie sont générés dynamiquement à partir des lignes associées.
- Une réinstallation vierge ne réimporte plus automatiquement les PDF, index ou catalogues des anciens bundles.
- Une première récupération des catalogues est mise en file en arrière-plan uniquement lorsqu’aucun catalogue exploitable n’existe dans les données propres au portail.
- La durée de session par défaut est de 30 minutes ; la mise à niveau migre uniquement l’ancienne valeur par défaut de 10 minutes et conserve les autres valeurs personnalisées.
- Les récupérations périodiques restent planifiées le dimanche à 00:00 en Europe/Paris, sans rattrapage au redémarrage.
- Sur la page Services, les barres sont visibles et les boutons Bulletins et Pièces sont désactivés uniquement pendant un traitement actif ; dès sa fin, les barres disparaissent et les boutons sont réactivés.
- La même règle de blocage pendant traitement est appliquée côté interface et côté API sur les pages Bulletins et Pièces.
- Les états catalogue écrits par le worker sont relus sans cache par le serveur web : une tâche prise en charge mais pas encore initialisée apparaît à 0 % en attente, jamais en échec rouge à 100 %.
- Les barres utilisent des états visuels explicites : gris en attente, bleu en cours, vert terminé et rouge uniquement pour un échec ou une indisponibilité.
- La progression de téléchargement des bulletins devient verte à 100 % pendant la phase d’indexation suivante.
- `uninstall --purge` supprime aussi un éventuel répertoire personnalisé défini par `storage.data_dir`.

## Tests automatisés

La suite `pytest` couvre notamment :

- authentification membre commune et authentification administrateur séparée ;
- limites indépendantes et configurables des tentatives de connexion ;
- accès HTTP depuis le réseau local et refus d’un accès public sans HTTPS ;
- sessions fixes, expiration côté serveur, cookies, CSRF et contrôle d’origine ;
- affichage du temps restant sur Services, Bulletins, Pièces, Couples et Administration ;
- commandes Internet, session, thème et taille du texte sur les connexions, Services et Administration ;
- titres de fenêtre et libellés de navigation exacts ;
- préférences d’affichage persistantes et taille normale par défaut sans ancienne préférence ;
- cookies navigateur non persistants, signal de fermeture, délai de grâce et annulation lors d’une navigation interne ;
- endpoint administrateur CPU/RAM protégé et graphique dynamique interactif ;
- présence et destination des cinq cartes de la page Services ;
- refus sans session de `/couples`, `/api/couples` et de chaque document embarqué ;
- réponse authentifiée de l’API Couples, nombre exact de lignes, sections et correspondances aux vues ;
- intégrité des fichiers embarqués : signatures PDF/JPEG/ZIP-XLSX et présence de chaque chemin référencé ;
- navigation commune vers la page Couples depuis les services existants ;
- structure dynamique de la page Couples : deux volets, menu des vues, fiches des pièces, marqueurs, sélection bidirectionnelle et sélecteur de désambiguïsation ;
- page Services sans effet de bord lors de ses rafraîchissements ;
- bouton Bulletins et bouton Pièces activés lorsque leur traitement est inactif, même après un traitement terminé avec avertissement ;
- boutons désactivés et barres affichées lorsque les travaux sont `pending` ou `running` ;
- exécution JavaScript réelle des transitions actif/inactif des deux blocs dynamiques ;
- récupération initiale des catalogues mise en file uniquement en l’absence de catalogue exploitable ;
- absence d’import implicite d’un ancien catalogue pendant la séquence d’installation vierge ;
- migration des anciens bundles uniquement par la commande explicite `run_server.sh migrate` ;
- arrêt des workers pendant cette migration, puis reprise des traitements nécessaires en arrière-plan ;
- timer catalogues exact `Sun *-*-* 00:00:00 Europe/Paris`, `Persistent=false`, sans délai aléatoire ;
- timer de paquets généré depuis le JSON, activable ou désactivable, avec migration des nouvelles clés sans écraser les valeurs personnalisées ;
- exécution contrôlée de `apt-get upgrade --with-new-pkgs` suivie d’un reboot simulé ;
- assistant Cloudflare, jeton masqué, dépôt signé, commande de service et redémarrage automatique ;
- action administrateur `apply-config` autorisée de bout en bout par le canal Unix ;
- annulation lors d’une mise à niveau des anciennes tâches catalogues `pending` ou `running` ;
- progression à 100 % avec fournisseurs indisponibles ou PDF en erreur ;
- récupération des bulletins uniquement après authentification membre ;
- recherche Bulletins refusée pendant le téléchargement comme pendant l’indexation ;
- recherche Pièces refusée pendant la récupération des catalogues ;
- installation, mise à niveau, sauvegarde, restauration, nettoyage, désinstallation et purge ;
- suppression du chemin de données par défaut et d’un chemin `storage.data_dir` personnalisé ;
- restitution récursive du propriétaire du répertoire source après une commande exécutée avec `sudo` ;
- canal de contrôle Unix, permissions et refus des commandes arbitraires ;
- restrictions de domaines, redirections, taille des PDF et résilience HTTP ;
- parseurs, historique des prix et cas de référence des huit fournisseurs.

Commande finale :

```bash
python -W error -m pytest -q
```

Résultat :

```text
223 passed
```

## Contrôles des nouveaux services

### Couples de serrage

Le tableur fourni a été conservé dans `resources/couples/couples_serrage.xlsx` et transcrit dans `resources/couples/couples_serrage.json`. Les contrôles vérifient :

- 61 lignes exactement ;
- cinq sections attendues ;
- conservation des libellés, valeurs en m·kg et repères de vues ;
- coordonnées comprises dans l’image et présence d’un marqueur pour chaque repère renseigné ;
- absence de marqueur pour les pièces sans couple renseigné ;
- disponibilité de la recherche et des filtres par section et par vue ;
- ouverture et centrage de la vue éclatée depuis une ligne du tableau ;
- sélection d’un repère entouré puis retour vers la ou les lignes correspondantes ;
- génération des colonnes, filtres, cartes et routes documentaires depuis la liste des vues, afin d’accepter les vues futures sans structure HTML figée ;
- liens vers les trois PDF originaux ;
- accès visible, avant les tableaux, au PDF français de la liste de visserie ;
- accès visible, en tête du référentiel, au PDF complet des couples et au tableur Excel source ;
- rayon principal des marqueurs porté de 18 à 27 px, soit exactement +50 %, avec zone cliquable adaptée ;
- hauteurs identiques des volets « Pièces et couples » et « Vue affichée » aux trois largeurs contrôlées ;
- teinte de fond de chaque ligne dérivée de sa catégorie, tout en conservant le nom textuel de la catégorie ;
- mode d’emploi complet et formule de conversion N·m vers m·kg placés avant les deux volets ;
- absence d’exposition non authentifiée de l’API, des images, des PDF et du tableur.

### Documents directs

Les deux cartes documentaires ouvrent directement les formulaires. La page Couples donne accès à la liste de visserie française, au PDF complet des couples et au tableur source :

```text
/documents/fiche-intervention.pdf
/documents/inventaire-avant-deplacement.pdf
/documents/liste-visserie-opel-gt.pdf
/documents/couples-serrage-opel-gt.pdf
/documents/couples-serrage-opel-gt.xlsx
```

Le serveur utilise une liste blanche fermée. Un nom inconnu ou une tentative de traversée de chemin ne permet pas d’accéder à un autre fichier. Les réponses PDF utilisent un affichage intégré au navigateur ; le tableur est proposé en téléchargement. Tous sont protégés par la session membre et les en-têtes anti-cache du portail.

### Revue visuelle et interaction navigateur

Les sept captures fournies par l’utilisateur ont remplacé les anciennes images du README. La cohérence des gabarits, des contrôles communs, des logos, des intitulés et des zones de navigation a été revue sur les pages Connexion membre, Connexion administration, Liste des services, Recherche bulletins, Comparateur de pièces, Couples de serrage et Administration.

Les tests automatisés et les contrôles statiques couvrent notamment :

- suppression du bouton correspondant au service courant dans les trois pages de service ;
- renommage des liens de retour et d’administration ;
- textes exacts des cartes de la page Liste des services ;
- détection Internet côté serveur, sans dépendance à `navigator.onLine`, avec plusieurs méthodes et seuil d’échecs successifs ;
- présence du paquet `iputils-ping` dans l’installation afin que la sonde ICMP soit disponible sur une installation minimale ;
- lecture de chaque processeur logique dans `/proc/cpuinfo` et `/proc/stat`, exposition des séries séparées et sélecteur de fréquence ;
- défilement vertical et horizontal de l’éditeur de configuration ;
- prise en compte de `pieces.scraping.default_enabled_sites` ;
- remplacement complet des captures documentaires du README.

## Contrôles statiques

Les commandes suivantes ont réussi :

```bash
python -m compileall -q app scrapers server_entry.py server_control.py
bash -n run_server.sh
find static -type f -name '*.js' -print0 | xargs -0 -n1 node --check
sha256sum -c requirements.lock.sha256
```

Le contrôle Ruff reste défini dans `pyproject.toml` et verrouillé dans `requirements-dev.lock`, mais son binaire n’était pas présent dans l’environnement de fabrication ; il n’est donc pas compté parmi les contrôles locaux ci-dessus. La compilation Python et les 225 tests avec avertissements transformés en erreurs ont, eux, été exécutés après la dernière modification.

Le script `run_server.sh` a en outre été exécuté en mode `--help` avec et sans couleurs. Son en-tête commun et ses étapes numérotées sont contrôlés par la suite, tout comme la présence inchangée des invites interactives existantes.

Tous les fichiers JSON du dépôt ont été chargés par le parseur Python. La configuration Pytest fixe explicitement la portée des boucles asynchrones afin que la suite puisse être exécutée avec les avertissements traités comme des erreurs.

## Installation vierge et migration

La séquence reproduite par les tests est désormais :

1. initialisation des répertoires et bases du portail ;
2. normalisation des anciens états de tâche ;
3. contrôle des catalogues propres au portail ;
4. création d’une tâche catalogue initiale uniquement si aucun catalogue exploitable n’est présent ;
5. démarrage du worker catalogue qui exécute cette tâche hors du processus web.

La commande `install` ne contient plus d’appel à `app.manage migrate`. Un ancien catalogue placé dans un répertoire de comparateur séparé reste donc absent d’une installation vierge. L’import volontaire reste disponible par `run_server.sh migrate`, qui arrête temporairement les services applicatifs, annule les tâches catalogue conflictuelles, effectue la copie sans écrasement puis redémarre les workers.

Le répertoire `resources` fait partie du code applicatif copié sous `/opt/portail-entraide-opel-gt` lors d’une installation ou d’une mise à niveau. Les routes des nouveaux services utilisent ce chemin installé et non le répertoire depuis lequel l’archive a été extraite.

## Progression et disponibilité des services dynamiques

Pour Bulletins et Pièces, l’état `running` exposé par `/api/services` est la seule cause de désactivation du bouton et d’affichage des barres :

- traitement actif : barres visibles, bouton désactivé ;
- aucun traitement actif : barres masquées, bouton activé.

L’état `ready` reste fourni à titre informatif pour indiquer la présence de données exploitables, mais il ne maintient plus un bouton de service désactivé après la fin d’une tâche. Sur les pages individuelles, les recherches sont protégées côté JavaScript et côté API pendant les opérations de récupération ou d’indexation.

Couples de serrage, les deux formulaires PDF et la liste de visserie française sont des ressources embarquées en lecture seule : leur disponibilité ne dépend d’aucune tâche de fond.

## Planification des catalogues

L’unité contient exactement :

```ini
OnCalendar=Sun *-*-* 00:00:00 Europe/Paris
Persistent=false
AccuracySec=1s
```

`systemd-analyze calendar` normalise correctement l’expression. La page Services et la page Pièces ne mettent aucune tâche en file. En dehors de la récupération initiale d’une installation vierge, les mises à jour sont créées uniquement par `portail-entraide-opel-gt-catalog-update.timer`.


## Planification des paquets système

Le modèle d’unité contient par défaut :

```ini
OnCalendar=Wed *-*-* 00:00:00 Europe/Paris
Persistent=false
AccuracySec=1s
```

Les tests chargent ensuite une configuration personnalisée (`Friday`, `23:45`) et exécutent réellement la fonction shell de génération dans une arborescence isolée. Ils vérifient l’expression `Fri *-*-* 23:45:00 Europe/Paris`, l’activation du timer, puis sa désactivation lorsque `weekly_package_update_enabled` vaut `false`.

La migration ajoute uniquement les trois clés absentes avec leurs valeurs par défaut. Une configuration personnalisée désactivée le vendredi à 23:45 reste inchangée. L’interface administrateur expose le JSON, enregistre sa version validée et transmet l’action `apply-config` au canal système ; cette action régénère le timer et redémarre les services applicatifs.

La commande interne `system-update-execute` a été exécutée avec des commandes système factices. Les appels observés sont `apt-get update`, `apt-get ... upgrade --with-new-pkgs`, `sync` et `systemctl reboot`. Le cas désactivé n’appelle aucune de ces commandes.

## Installation Cloudflare Tunnel

Le script a été contrôlé statiquement et syntaxiquement pour les points suivants :

- question explicite au début de `install` ;
- explication du parcours **Networking → Tunnels → Overview → Add a replica → Linux** ;
- saisie masquée et validation d’un jeton commençant par `eyJ` ;
- ajout de la clé et du dépôt APT officiels Cloudflare ;
- installation de `cloudflared` ;
- exécution de `cloudflared service install <JETON>` ;
- activation, redémarrage et contrôle de `cloudflared.service` ;
- message explicite indiquant le redémarrage automatique après chaque reboot.

Le jeton n’est écrit ni dans la configuration ni dans les secrets du portail.

## Désinstallation et purge

Le test de purge exécute réellement `run_server.sh uninstall --purge` dans une arborescence isolée contenant :

- code installé ;
- configuration et secrets ;
- données par défaut ;
- données dans un chemin personnalisé ;
- logs ;
- socket et répertoire runtime ;
- unités et fichier `tmpfiles.d`.

Tous ces chemins sont absents après la commande. Les chemins système dangereux tels que `/`, `/var`, `/opt` ou `/home` sont explicitement refusés par la fonction de suppression sécurisée.

## Démarrage HTTP réel

Le serveur a été lancé avec une configuration et une arborescence vierges. Les points suivants ont été contrôlés :

- ouverture du port sans attendre les tâches de fond ;
- création des bases des tâches, statistiques et bulletins ;
- création du journal applicatif ;
- réponse HTTP 200 de `/api/health` ;
- version retournée : `1.1.15` ;
- chargement HTTP 200 de la page de connexion ;
- arrêt propre du processus Uvicorn.

## Unités systemd

`systemd-analyze verify` a analysé toutes les unités. Ses seuls diagnostics dans l’environnement de fabrication concernent les exécutables sous `/opt/portail-entraide-opel-gt`, qui n’existent qu’après installation sur la machine cible.

## Nettoyage de l’archive

Avant création du ZIP, sont supprimés :

- caches Python, Pytest et Ruff ;
- bases, secrets et journaux générés par les tests ;
- environnements virtuels ;
- fichiers temporaires et archives imbriquées ;
- anciens marqueurs de mise à jour forcée.

Le bundle ne contient aucun bulletin privé, catalogue de production, index d’exploitation, login, cookie ou secret généré. Les sept PDF inclus sont exclusivement les deux formulaires, la liste de visserie française, le PDF des couples généré à partir du référentiel et les trois vues éclatées nécessaires aux nouveaux services.

## Limites de la validation

Les contrôles suivants nécessitent la machine cible ou des accès privés :

- authentification réelle sur `entraideopelgt.fr` ;
- téléchargement réel des bulletins réservés aux membres ;
- OCR complet du fonds documentaire ;
- interrogation en direct de tous les fournisseurs ;
- installation effective sous le PID 1 `systemd` ;
- installation réelle de `cloudflared` avec un jeton Cloudflare privé ;
- exécution réelle de la mise à jour APT et du redémarrage planifié de la machine cible.

Les chemins applicatifs reproductibles, les scripts, les règles responsive communes, les téléchargements de visserie/couples/Excel, les correspondances visuelles bidirectionnelles, la génération du timer système, la séquence APT simulée, le canal administrateur, les tâches de fond, la purge, la migration explicite, le démarrage HTTP et les API ont été validés localement.
