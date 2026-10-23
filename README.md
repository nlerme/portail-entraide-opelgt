# Portail Entraide Opel GT

**Version 1.1.21 — Linux serveur**

Version 1.1.21 du 23 octobre 2026 : captures **Liste des services** et **Petites annonces** fournies actualisées dans ce README, onglet **Notifications** dans l’administration pour les identifiants ntfy et l’intervalle d’envoi, limité à **une notification au maximum par période de 24 heures**.

Version 1.1.20 du 23 octobre 2026 : notifications **ntfy** d’incident et de rétablissement, configuration à l’installation, collecteur Leboncoin remplacé par **etienne-hd/lbc 1.1.7**, prix sur les cartes d’annonces et sources **Classic Number** / **Classic Trader**.

Version 1.1.19 du 23 octobre 2026 : ajout du service **Petites annonces**, avec sélection des sources, cinq tris et collecte quotidienne à 02:00 (Europe/Paris). Pendant la collecte, son accès est désactivé et les annonces déjà affichées sont masquées. Le traitement GT Teile sépare désormais la collecte du catalogue et la traduction afin d’éviter les attentes prolongées autour de 79 %.

Correctif 1.1.18 du 23 octobre 2026 : progression réelle étendue aux huit catalogues, arrêt et désactivation de Cloudflare lors de la purge, et version du bundle centralisée dans `VERSION` avec contrôles de cohérence.

Correctif Edelschmiede du 23 octobre 2026 : récupération et traduction bornées, progression réelle par pièce et arrêt contrôlé en cas d’indisponibilité prolongée. Le test complet a récupéré 277 pièces avec leurs prix et disponibilités en environ deux minutes.

Correctif ciblé du 23 octobre 2026 : mises à jour des catalogues ATZ et Opel GT Source, et maintien de la connexion Cloudflare Tunnel. Les autres fonctionnalités sont conservées.

Portail web auto-hébergé réunissant six services dans une interface commune : recherche dans les bulletins, comparaison de pièces, petites annonces d’Opel GT d’époque en France, couples de serrage avec localisation sur vues éclatées, fiche d’intervention et fiche d’inventaire.

Le portail est conçu pour fonctionner en permanence sur un Raspberry Pi ou un petit serveur Debian/Ubuntu. Il s’installe sans Docker, démarre automatiquement avec `systemd`, conserve ses données localement et n’ouvre aucun navigateur sur la machine hôte.

## Sommaire

- [Aperçu](#aperçu)
- [Services inclus](#services-inclus)
- [Matériel et système](#matériel-et-système)
- [Installation](#installation)
- [Notifications ntfy](#notifications-ntfy)
- [Cloudflare Tunnel](#cloudflare-tunnel-facultatif)
- [Commandes de `run_server.sh`](#commandes-de-run_serversh)
- [Configuration](#configuration)
- [Mises à jour automatiques](#mises-à-jour-automatiques)
- [Sécurité et confidentialité](#sécurité-et-confidentialité)
- [Sauvegarde et restauration](#sauvegarde-et-restauration)
- [Développement et validation](#développement-et-validation)
- [Publication sur GitHub](#publication-sur-github)
- [Licences](#licences)

## Aperçu

Les captures ci-dessous illustrent l’interface commune du portail. Les captures « Liste des services » et « Petites annonces » sont celles fournies pour cette mise à jour. Elles présentent les données et les sources visibles au moment de leur prise ; le service actuel propose les quatre sources décrites ci-dessous et affiche aussi les prix.

### Connexion des membres

![Page de connexion membre](docs/screenshots/connexion-membres.png)

### Page de connexion administrateur

![Page de connexion administrateur](docs/screenshots/connexion-administration.png)

### Liste des services

![Liste des services](docs/screenshots/liste-services.png)

### Recherche dans les bulletins

![Recherche dans les bulletins](docs/screenshots/recherche-bulletins.png)

### Comparateur de pièces

![Comparateur de pièces](docs/screenshots/comparateur-pieces.png)

### Petites annonces

![Petites annonces](docs/screenshots/petites-annonces.png)

Accessible depuis la carte **Petites annonces** de la **Liste des services**, ce service recense les voitures proposées en France, par des particuliers et professionnels : Opel GT 1100, GT 1900 et GT/J d’époque. Les GT modernes, annonces de pièces et véhicules localisés à l’étranger sont exclus. Une GT d’époque dont la cylindrée n’est pas fournie reste libellée « Modèle non précisé ».

| Source | Périmètre | Collecte |
|---|---|---|
| [lesAnciennes](https://www.lesanciennes.com/annonces/voiture-collection/opel-gt/) | Annonces automobiles Opel GT, filtrées sur les véhicules d’époque situés en France | Lecture des données publiques des pages de résultats et de leur pagination. |
| [Leboncoin](https://www.leboncoin.fr/recherche?category=2&text=opel%20gt) | Catégorie voitures, recherche Opel GT sur toute la France | Client Python [etienne-hd/lbc](https://github.com/etienne-hd/lbc), version 1.1.7 verrouillée, recherches séparées particuliers/professionnels et pagination contrôlée. |
| [Classic Number](https://www.classicnumber.com/opel-gt-collection-m-58-2648.html) | Opel GT d’époque ; seuls les véhicules situés en France sont conservés | Résultats publics et fiches des véhicules français pour la date originale et le lieu. |
| [Classic Trader](https://www.classic-trader.com/fr/voitures/recherche/opel/gt) | Opel GT ; filtrage strict sur le pays du véhicule et les modèles d’époque | Données structurées publiques Astro des résultats ; aucune consultation de profil vendeur. |

**Essais réels du 23 octobre 2026 :** lesAnciennes a fourni 9 annonces françaises et Classic Number 1 annonce française (aux enchères). Les 9 offres Classic Trader consultées sont situées à l’étranger ou concernent une GT moderne : résultat français vide, sans erreur. Le client `lbc` est installé et utilisé, mais l’essai depuis cet environnement distant reste refusé par DataDome (HTTP 403). Le résultat peut différer depuis la connexion du serveur ; cette intégration ne garantit pas de lever ce blocage. Un refus est affiché et signalé par ntfy si activé. Il n’y a ni solveur de CAPTCHA, ni service payant, ni proxy ajouté au bundle.

- En haut de la page, les quatre sources sont cochées par défaut ; les décocher filtre immédiatement les résultats locaux.
- Chaque carte comporte le type de vendeur, le modèle, le prix avec sa devise, l’année, le lieu et son département, la date originale de mise en ligne et une photo lorsqu’elle est fournie. Un clic ouvre directement l’annonce d’origine.
- Les boutons trient dans les deux sens par type de vendeur, modèle, année, date de l’annonce ou département. Par défaut, les annonces les plus récentes apparaissent en premier ; les informations inconnues restent à la fin.
- Une information absente de la source est indiquée comme non précisée. Un prix sur demande, une invitation à faire offre ou une enchère conserve ce libellé ; aucune estimation n’est présentée comme un prix de vente. L’absence d’un badge professionnel ne suffit pas à qualifier un vendeur de particulier ; la date de collecte ne remplace jamais la date de publication.
- La collecte fonctionne côté serveur, même sans visite du portail. Ouvrir une page ou consulter l’API ne déclenche aucune requête aux sites d’annonces.
- Durant la collecte, le bouton de la page Services est désactivé ; une page Petites annonces déjà ouverte masque ses cartes et indique la mise à jour au prochain contrôle (toutes les deux secondes). L’API ne renvoie aucune annonce pendant ce traitement. Les résultats et les sélections réapparaissent à sa fin.
- Chaque source est enregistrée atomiquement. Un échec, une pagination incomplète ou une baisse inhabituelle conserve ses dernières données valides et affiche un avertissement. Le verrou de collecte est libéré automatiquement si le processus s’arrête.

Les annonces et leurs métadonnées sont conservées sous `/var/lib/portail-entraide-opel-gt/annonces/`. Les photos sont chargées depuis le site source ; aucun fichier de collecte, donnée personnelle de vendeur ou cache de production n’est embarqué dans le dépôt public. Les captures documentaires fournies sont incluses dans `docs/screenshots/`.

### Couples de serrage

![Couples de serrage](docs/screenshots/couples-serrage.png)

### Administration

![Page d’administration](docs/screenshots/administration.png)

L’interface est responsive et partage sur toutes les pages :

- un logo PNG transparent, sans rectangle blanc en mode sombre ;
- des pages de connexion membre et administrateur harmonisées ;
- un mode clair/sombre mémorisé dans le navigateur ;
- une taille de police ajustable et persistante ;
- un indicateur de connectivité calculé côté serveur ;
- un compte à rebours avant expiration de la session ;
- une navigation homogène entre les services et l’administration.

## Services inclus

### Recherche dans les bulletins

- authentification avec le compte membre du site du club ;
- récupération incrémentale des PDF après la connexion ;
- OCR français et anglais avec Tesseract lorsque le PDF ne contient pas de texte exploitable ;
- index local SQLite FTS5 ;
- recherche plein texte avec filtres par année et numéro de bulletin ;
- consultation des PDF locaux ;
- poursuite de la récupération et de l’indexation côté serveur lorsque le navigateur est fermé.

Les identifiants du site membre ne sont ni enregistrés sur disque ni écrits dans les journaux.

### Comparateur de pièces

Le comparateur travaille sur des catalogues locaux historisés. Les boutiques ne sont pas interrogées à chaque recherche utilisateur.

Fournisseurs pris en charge :

- Opelix Parts ;
- SplendidParts ;
- Edelschmiede ;
- GT Teile ;
- ATZ Online ;
- Opel GT Source ;
- Oldtimer Motorenteile ;
- TW-Oldtimerteile.

Fonctions principales :

- recherche multilingue avec normalisation des termes ;
- comparaison des prix et disponibilités ;
- historique des catalogues et indication des variations de prix ;
- filtres, tri, mémorisation des préférences et export CSV ;
- contrôle de cohérence avant remplacement d’un catalogue valide ;
- coordonnées des fournisseurs intégrées à la page.

Pour TW-Oldtimerteile, le scraper compte les catégories Opel GT, exclut la catégorie « J’en ai besoin, je le veux ! », parcourt uniquement les listes et leurs paginations, et n’ouvre pas les fiches individuelles.

La récupération Splendid Parts réutilise une session de boutique persistante et temporise les requêtes afin de ne pas confondre une protection anti-rafale avec une indisponibilité. La couche de contrôle de disponibilité ne contourne aucune restriction `robots.txt` : elle signale une limitation de l’automatisation sans présenter la boutique comme hors ligne.

Les fournisseurs cochés par défaut sont configurables avec `pieces.scraping.default_enabled_sites` :

```json
{
  "pieces": {
    "scraping": {
      "default_enabled_sites": [
        "opelix_parts",
        "splendid_parts",
        "edelschmiede",
        "pro_gt",
        "atz_online",
        "opel_gt_source",
        "oldtimer_motorenteile",
        "tw_oldtimerteile"
      ]
    }
  }
}
```

Retirer un identifiant de cette liste laisse le fournisseur disponible, mais décoché à l’ouverture du comparateur. La clé `disabled_sites` permet de désactiver complètement un fournisseur.

### Couples de serrage

- 61 valeurs issues du tableur embarqué ;
- filtrage par section et présence dans une vue ;
- correspondance bidirectionnelle entre la liste et les repères des vues éclatées ;
- repères colorés par catégorie et mise en évidence du repère sélectionné ;
- volet « Pièces et couples » redimensionnable ou masquable ;
- téléchargement du PDF des couples, du fichier Excel et du PDF français de visserie ;
- conversion rappelée dans l’interface : `m·kg = N·m ÷ 9,80665`.

Les vues éclatées embarquées ne sont pas considérées comme exhaustives : de nouvelles vues peuvent être ajoutées au référentiel.

### Fiche d’intervention

PDF A4 recto/verso à compléter, avec choix du véhicule 1900, 1100 ou GT/J, préparation de l’intervention, pièces utilisées, serrages appliqués et contrôles.

### Fiche d’inventaire

PDF A4 recto/verso de préparation du véhicule, des documents, de l’outillage, des pièces de rechange et du chargement avant déplacement.

### Administration

- édition contrôlée de `/etc/portail-entraide-opel-gt/config.json` ;
- éditeur JSON avec coloration syntaxique, numéros de ligne, ligne courante, parenthèses correspondantes et ascenseurs horizontal/vertical ;
- contrôle du serveur par socket Unix privilégié limité à une liste d’actions autorisées ;
- consultation des tâches de fond et des journaux ;
- état général avec badges bleus uniformes et statistiques avec couleurs sémantiques, pourcentages pertinents et drapeaux de pays ;
- graphique interactif de la RAM et de chaque cœur CPU détecté dans `/proc/cpuinfo` et `/proc/stat` ;
- fréquence de rafraîchissement du graphique réglable de 1 à 30 secondes.

## Détection de la connexion Internet

L’indicateur commun aux pages est calculé côté serveur, et non à partir du seul état `navigator.onLine` du navigateur. Le contrôle combine :

- connexions TCP vers plusieurs destinations indépendantes ;
- résolution DNS de plusieurs domaines ;
- requêtes HTTPS légères ;
- `ping` ICMP lorsque la commande est disponible.

Une seule méthode réussie suffit à confirmer la connexion. Plusieurs échecs successifs sont nécessaires avant d’afficher un état hors ligne, et une courte période de grâce évite les faux négatifs provoqués par un délai DNS ou réseau transitoire.

## Matériel et système

### Minimum fonctionnel

- Linux 64 bits : Raspberry Pi OS, Debian ou Ubuntu Server ;
- architecture ARM64/AArch64 ou x86-64 ;
- processeur double cœur ;
- 4 Gio de RAM ;
- 16 Gio de stockage disponible ;
- accès Internet pour l’installation, l’authentification et les synchronisations.

### Configuration recommandée

- Raspberry Pi 5 avec 8 Gio de RAM et refroidissement actif ;
- SSD USB 3 ou NVMe de 64 Gio minimum plutôt qu’une carte microSD ;
- alimentation stable ;
- connexion Ethernet ;
- sauvegarde périodique avec `run_server.sh backup`.

Pour une indexation OCR plus rapide ou plusieurs utilisateurs simultanés, un mini-PC x86-64 avec quatre cœurs, 8 à 16 Gio de RAM et un SSD est préférable.

## Installation

```bash
unzip portail-entraide-opelgt-1.1.21.zip
cd portail-entraide-opelgt
chmod +x run_server.sh
sudo ./run_server.sh install
```

L’installation suit huit grandes étapes :

1. vérification de Linux et de l’architecture, puis saisie des réglages ntfy et des options d’accès ;
2. préparation des paquets système ;
3. création du compte système non privilégié `opelgt` ;
4. installation des fichiers applicatifs ;
5. création des environnements Python et installation des dépendances verrouillées ;
6. installation de la configuration et des unités `systemd` ;
7. initialisation des données et des tâches de fond ;
8. définition du mot de passe administrateur et affichage des adresses d’accès.

La création des environnements Python peut prendre plusieurs minutes sur un Raspberry Pi.

Le nom du répertoire extrait et du dépôt public est `portail-entraide-opelgt`. Les chemins système installés sous `/opt`, `/etc` et `/var/lib` conservent le nom `portail-entraide-opel-gt` afin de préserver la compatibilité des installations existantes.

## Notifications ntfy

Dès le début de `sudo ./run_server.sh install`, le portail propose d’activer les notifications. Renseignez :

- le serveur HTTPS (par défaut `https://ntfy.sh`) et le sujet auquel vous abonnez l’application ntfy du smartphone ;
- l’authentification requise par ce serveur : aucune, jeton d’accès, ou utilisateur/mot de passe. Les jetons et mots de passe sont saisis avec masquage.

Un serveur ntfy n’exige pas nécessairement un compte pour publier. Sur un sujet public, choisissez un nom long et imprévisible ; pour contrôler les lecteurs et les éditeurs, utilisez un sujet protégé et ses identifiants. Le jeton doit autoriser la publication dans le sujet choisi. Le compte ou les identifiants ntfy ne sont pas ceux du portail ou de Leboncoin. La création du compte et l’abonnement du téléphone se font auprès du serveur ntfy choisi.

Lors d’une mise à niveau, l’installateur propose de conserver la configuration existante ou de la remplacer. Refuser l’activation enregistre `enabled: false` et retire les anciens identifiants ntfy. Un message de test est mis en file en fin d’installation. Il est soumis à la même limite d’envoi que les alertes ; si une notification a déjà été remise pendant l’intervalle choisi, il attend la prochaine échéance. Un échec de remise le conserve également en attente. Pour réessayer explicitement :

```bash
sudo ./run_server.sh ntfy-test
```

`portail-entraide-opel-gt-notifications.timer` lance un contrôle indépendant environ chaque minute, à partir de deux minutes après le démarrage. Il surveille : Internet (plusieurs destinations), la réponse du portail local, les workers OCR/catalogues, le connecteur Cloudflare et ses connexions actives lorsqu’il est géré par le portail, les échecs des catalogues et des sources d’annonces, et un traitement catalogue dépassant sa durée maximale. Si `server.public_url` est renseigné, son `/api/health` est également vérifié lorsque Internet fonctionne.

Deux contrôles réseau/processus en échec consécutifs confirment un incident. Un échec de collecte déjà enregistré crée directement un événement. L’apparition d’un problème et son rétablissement sont enregistrés une seule fois, puis regroupés dans les envois autorisés ; le même incident n’est pas répété à chaque minute. Le moniteur continue de fonctionner si le service web tombe. Un arrêt volontaire des services peut donc aussi déclencher une alerte s’il se prolonge.

**Une coupure Internet ne permet pas un envoi immédiat depuis ce serveur.** Les événements sont conservés sur disque et transmis lorsque la connexion revient, avec leurs dates. Les refus ntfy (identifiants, quota, serveur indisponible) gardent également les messages en attente. **Au maximum un message ntfy est remis par intervalle choisi : 1 jour par défaut, soit au moins 24 heures entre deux envois réussis.** Le premier envoi peut partir au prochain contrôle si aucune notification récente n’a consommé ce délai. Les événements arrivés ensuite attendent la prochaine échéance et sont regroupés en un message. L’intervalle est réglable de 1 à 365 jours ; une valeur inférieure à un jour est refusée côté serveur. La date du dernier envoi réussi est persistée : un redémarrage ou une modification des identifiants ne remet pas ce compteur à zéro. Un envoi échoué ne consomme pas le délai et sera réessayé. Les messages respectent la limite de taille ntfy ; un éventuel surplus reste en file pour une échéance ultérieure. Au-delà de 200 événements en attente, les plus anciens sont regroupés explicitement. Un arrêt complet du serveur ou une panne d’alimentation nécessite une surveillance externe pour être signalé pendant la panne.

### Réglages dans l’administration

Ouvrez **Administration → Notifications** pour activer ou désactiver ntfy, régler le serveur et le sujet, choisir l’authentification, remplacer le jeton ou le mot de passe, et choisir l’**intervalle minimal entre deux envois**, en jours. La valeur `1` correspond à la fréquence maximale autorisée : une notification toutes les 24 heures. Ce réglage concerne les **messages ntfy** ; la surveillance continue chaque minute et la collecte des petites annonces reste programmée à 02:00.

Les champs Jeton et Mot de passe sont masqués et toujours vides lors du chargement. Pour le même mode d’authentification, laissez un champ secret vide afin de conserver sa valeur enregistrée. Changer de mode retire l’ancien type d’identifiant ; désactiver ntfy efface ses identifiants. Le bouton **Enregistrer les réglages ntfy** applique les changements dès le prochain contrôle, sans redémarrage ; **Recharger les réglages** abandonne les modifications non enregistrées. L’onglet ne déclenche aucun envoi de test automatique.

L’API est réservée aux sessions administrateur et les modifications exigent leur jeton CSRF. En production, les écritures du fichier de secrets passent par l’action limitée `save-ntfy` du canal root existant. Seule la section ntfy est modifiée, en conservant le secret d’application, le mot de passe administrateur et les permissions/propriétaires du fichier.

La configuration ntfy est enregistrée uniquement dans la section `ntfy` de `/etc/portail-entraide-opel-gt/secrets.json`, appartenant à root et au groupe du service, mode `0640`. Ses secrets ne sont jamais renvoyés au navigateur : l’administration indique seulement si un jeton ou mot de passe existe. Ils ne sont ni copiés dans les unités systemd, ni ajoutés aux lignes de commande ou aux journaux. Les messages ne contiennent pas ces identifiants. L’état et les messages en attente sont conservés dans `/var/lib/portail-entraide-opel-gt/notifications/`, avec des permissions restreintes.

`sudo ./run_server.sh uninstall --purge` arrête d’abord le moniteur, désactive son timer, retire ses unités et supprime ses identifiants ainsi que son état et sa file d’attente avec les autres secrets/données du portail. Une désinstallation sans purge conserve la configuration pour une réinstallation. Les sauvegardes exportées hors du serveur et les messages déjà remis au serveur ntfy ne peuvent pas être effacés par cette commande locale.

Documentation : [publication JSON et authentification ntfy](https://docs.ntfy.sh/publish/).

## Cloudflare Tunnel facultatif

Pendant `install`, le script peut installer `cloudflared` et enregistrer le tunnel comme service `systemd`. Le jeton se récupère dans le tableau de bord Cloudflare :

```text
Networking → Tunnels → tunnel concerné → Overview → Add a replica → Linux
```

Le jeton correspond à la longue chaîne commençant généralement par `eyJ` dans la commande `cloudflared service install`. Il est saisi de manière masquée.

Le service `cloudflared` :

- démarre automatiquement après chaque redémarrage de la machine ;
- maintient une connexion sortante vers Cloudflare ;
- ne nécessite aucune redirection de port sur le routeur.

Le correctif utilise HTTP/2 pour la connexion du tunnel, avec redémarrage automatique du connecteur et contrôle toutes les minutes. Le contrôle sonde `/api/health` sur le portail local puis `/ready` sur le connecteur : après trois échecs consécutifs, il redémarre uniquement le service concerné. Il reste actif sans visite locale et respecte un arrêt volontaire des services. Le timer `portail-entraide-opel-gt-cloudflare-health.timer` est activé uniquement avec un tunnel géré par l’installateur.

La désinstallation arrête d’abord ce timer et tout contrôle encore en cours, puis arrête et désactive le connecteur géré par le portail. Avec `--purge`, elle exécute également `systemctl disable --now cloudflared.service` pour les anciennes installations sans fichier de gestion. Si un service reste actif ou activé après un échec de cette commande, la désinstallation s’interrompt avec une erreur explicite. Le paquet Cloudflare et la définition globale de son service restent installés, avec le service arrêté et désactivé.

Pour déployer ce correctif, relancer `sudo ./run_server.sh install` depuis le nouveau bundle. Sur une installation antérieure à ce correctif, répondre **oui** à l’option Cloudflare et saisir le jeton du tunnel existant pour installer sa surveillance. La configuration et les données existantes sont conservées.

Les catalogues ATZ, Opel GT Source et GT Teile réutilisent leurs traductions en cache et celles du dernier catalogue validé. Si le service de traduction refuse les requêtes (HTTP 429) ou devient indisponible, les prix et disponibilités peuvent être mis à jour avec les désignations originales pour les noms encore non traduits. Ces noms sont retentés lors d’une prochaine mise à jour. Les contrôles d’intégrité du catalogue restent appliqués.

Pour GT Teile, la lecture des pages n’effectue plus de traduction individuelle. Les traductions sont groupées dans une phase distincte, à concurrence limitée, avec arrêt des lots restants dès l’indisponibilité du traducteur. Les options de délai et de parallélisme sont appliquées. La mise à jour complète est limitée à 30 minutes ou au délai global configuré s’il est inférieur ; un dépassement termine les processus et conserve le dernier catalogue valide. Une phase réseau peut rester stable tant qu’aucune page ne se termine : le pourcentage correspond au travail réel, sans progression artificielle.

Pour les huit fournisseurs, les barres de progression suivent les pages, catégories, fiches et traductions réellement traitées. Les compteurs sont partagés entre les threads et processus des scrapers et transmis au portail pendant la collecte. Le pourcentage reste inférieur à 100 % jusqu’au résultat final et aux contrôles précédant la publication du catalogue ; en cas d’échec, le dernier catalogue valide reste conservé.

La route publiée doit pointer vers :

```text
http://127.0.0.1:8080
```

Le DNS public doit être un CNAME proxifié vers le tunnel concerné :

```text
<UUID-DU-TUNNEL>.cfargotunnel.com
```

Un tunnel peut apparaître « sain » alors que le DNS du sous-domaine pointe vers un autre tunnel. En cas d’erreur Cloudflare 1033, vérifier en priorité la cible CNAME et l’UUID du tunnel utilisé par `cloudflared`.

## Commandes de `run_server.sh`

Chaque commande affiche un en-tête avec le nom du bundle, la version, l’auteur et l’action exécutée.

| Commande | Rôle |
|---|---|
| `sudo ./run_server.sh install` | Installe ou met à niveau le portail en conservant la configuration et les données existantes. |
| `sudo ./run_server.sh start` | Démarre les trois services applicatifs. |
| `sudo ./run_server.sh stop` | Arrête les services applicatifs. |
| `sudo ./run_server.sh restart` | Redémarre les services applicatifs. |
| `sudo ./run_server.sh status` | Affiche l’état des services, timers et du socket de contrôle. |
| `sudo ./run_server.sh health` | Interroge le point de santé `/api/health`. |
| `sudo ./run_server.sh ntfy-test` | Envoie un test ntfy ; conserve le message pour réessayer si l’envoi échoue. |
| `sudo ./run_server.sh logs [N]` | Suit les journaux locaux, avec éventuellement un nombre de lignes initiales. |
| `sudo ./run_server.sh set-admin-password` | Redéfinit le mot de passe administrateur et invalide les anciennes sessions. |
| `sudo ./run_server.sh retry-ocr` | Remet en file les PDF non indexés. |
| `sudo ./run_server.sh migrate` | Importe explicitement les données des anciens bundles. |
| `sudo ./run_server.sh backup [--output PATH]` | Sauvegarde les données, la configuration et les secrets. |
| `sudo ./run_server.sh restore ARCHIVE` | Restaure transactionnellement une sauvegarde complète. |
| `sudo ./run_server.sh cleanup` | Nettoie les fichiers temporaires et les anciens travaux. |
| `sudo ./run_server.sh apply-config` | Valide la configuration, actualise les timers puis redémarre le portail. |
| `sudo ./run_server.sh uninstall` | Désinstalle l’application en conservant configuration et données. |
| `sudo ./run_server.sh uninstall --purge` | Arrête et désactive aussi `cloudflared`, puis supprime l’application, les données, PDF, index, catalogues, caches, journaux, sauvegardes et le compte système. |

`system-update-execute` est une commande interne réservée à l’unité `systemd` de maintenance.

## Configuration

Fichier principal :

```text
/etc/portail-entraide-opel-gt/config.json
```

Secrets :

```text
/etc/portail-entraide-opel-gt/secrets.json
```

Données persistantes :

```text
/var/lib/portail-entraide-opel-gt/
```

Après une modification manuelle ou depuis l’administration :

```bash
sudo /opt/portail-entraide-opel-gt/run_server.sh apply-config
```

Sections principales :

- `server` : adresse d’écoute, port, URL publique et proxies de confiance ;
- `sessions` : durée avant déconnexion ;
- `authentication` : URLs du site membre, délais et limites de tentatives ;
- `admin` : activation, identifiant et taille des journaux ;
- `storage` : répertoire des données ;
- `bulletins` : OCR, réseau et taille maximale des PDF ;
- `pieces.scraping` : concurrence, limites réseau, fournisseurs désactivés et fournisseurs cochés par défaut ;
- `pieces.catalog_validation` : seuils de validation d’un nouveau catalogue ;
- `maintenance` : fuseau, calendrier des catalogues, mises à jour système et nettoyage.

Un exemple complet est fourni dans `config.example.json`. Les secrets sont séparés dans `secrets.json` et ne doivent jamais être commités.

## Mises à jour automatiques

### Catalogues fournisseurs

Par défaut : lundi, mercredi et vendredi à 02:00, fuseau `Europe/Paris`.

```text
portail-entraide-opel-gt-catalog-update.timer
```

Une installation vierge met également en file une première récupération lorsqu’aucun catalogue exploitable n’est présent.

### Petites annonces

Tous les jours à **02:00**, fuseau **Europe/Paris**, par les unités :

```text
portail-entraide-opel-gt-annonces-update.timer
portail-entraide-opel-gt-annonces-update.service
```

Le timer est installé et activé par `sudo ./run_server.sh install`, y compris lors d’une mise à niveau. Cette commande lance également une collecte en arrière-plan, sans attendre sa fin. Les réglages de l’horaire des catalogues n’affectent pas celui des annonces. `Persistent=true` rattrape une échéance manquée après l’arrêt du serveur. Un verrou commun empêche deux collectes simultanées. La durée du service est limitée à quinze minutes et chaque source possède ses limites de requêtes et de durée.

Pour consulter la planification et les derniers résultats :

```bash
systemctl list-timers portail-entraide-opel-gt-annonces-update.timer
sudo journalctl -u portail-entraide-opel-gt-annonces-update.service -n 100
```

La désinstallation arrête la collecte éventuelle, désactive le timer et retire ses deux unités. Sans `--purge`, les annonces collectées sont conservées avec les autres données ; avec `--purge`, elles sont supprimées.

### Paquets système

Par défaut : mercredi à 00:00, puis redémarrage de la machine.

```json
{
  "maintenance": {
    "weekly_package_update_enabled": true,
    "weekly_package_update_day": "Wednesday",
    "weekly_package_update_time": "00:00"
  }
}
```

Le jour est écrit en anglais, de `Monday` à `Sunday`, et l’heure au format `HH:MM`. La planification est régénérée avec `apply-config`.

### Nettoyage

Le nettoyage quotidien est exécuté vers 03:30. Il supprime les fichiers temporaires et états obsolètes sans toucher aux catalogues valides ni aux PDF utiles.

## Sécurité et confidentialité

- services exécutés avec le compte système non privilégié `opelgt` ;
- configuration et secrets lisibles uniquement par `root` et le groupe de service ;
- mot de passe administrateur haché avec Argon2 ;
- politique de mot de passe : 16 caractères minimum, minuscule, majuscule, chiffre et caractère spécial ;
- cookies de session signés, durée configurable et révocation à la déconnexion ;
- protection CSRF sur les opérations d’écriture ;
- limitation des tentatives de connexion membre et administrateur ;
- accès HTTP membre limité au réseau local par défaut ;
- HTTPS requis depuis Internet ;
- en-têtes CSP, anti-framing, anti-MIME sniffing et `noindex` ;
- socket Unix privilégié limité aux commandes explicitement autorisées ;
- unités `systemd` renforcées ;
- aucune conservation des identifiants membres ;
- exclusion des secrets, bases, journaux et données d’exécution par `.gitignore`.

Consultez également :

- [`SECURITY.md`](SECURITY.md) ;
- [`PRIVACY.md`](PRIVACY.md) ;
- [`docs/HTTPS.md`](docs/HTTPS.md) ;
- [`SCRAPING_POLICY.md`](SCRAPING_POLICY.md).

## Sauvegarde et restauration

Créer une sauvegarde :

```bash
sudo /opt/portail-entraide-opel-gt/run_server.sh backup
```

Choisir un fichier de destination :

```bash
sudo /opt/portail-entraide-opel-gt/run_server.sh backup --output /chemin/sauvegarde.tar.gz
```

Restaurer :

```bash
sudo /opt/portail-entraide-opel-gt/run_server.sh restore /chemin/sauvegarde.tar.gz
```

Les sauvegardes peuvent contenir des secrets. Elles doivent être conservées hors du dépôt GitHub et protégées par des permissions adaptées.

## Structure du dépôt

```text
portail-entraide-opelgt/
├── .github/                # CI GitHub Actions et Dependabot
├── app/                    # API, authentification, bulletins, catalogues, annonces et administration
├── docs/                   # documentation HTTPS et captures du README
├── resources/              # PDF, tableur et vues éclatées embarqués
├── scrapers/               # scrapers autonomes et harmonisés
├── static/                 # interfaces web
├── systemd/                # services, socket et timers
├── tests/                  # tests automatisés
├── config.example.json
├── secrets.example.json
└── run_server.sh
```

## Développement et validation

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.lock
python -W error -m pytest -q
ruff check .
bash -n run_server.sh
```

La CI GitHub vérifie également :

- ShellCheck ;
- la syntaxe JavaScript avec Node.js ;
- les empreintes des dépendances verrouillées ;
- l’absence de secrets, bases et journaux d’exécution.

Les tests couvrent notamment l’authentification, les sessions, la configuration, les jobs, les catalogues, les scrapers, les annonces (modèles, France, pagination, tris, échecs et verrouillage), le déploiement, les documents embarqués et les interfaces communes. Les validations de cette version et les limites des essais réels sont détaillées dans [`VALIDATION.md`](VALIDATION.md).

## Publication sur GitHub

Le bundle est préparé pour un dépôt public :

- licence du code à la racine ;
- notices des composants tiers ;
- politique de sécurité et de confidentialité ;
- guide de contribution ;
- workflow GitHub Actions ;
- configuration Dependabot ;
- `.gitignore` excluant secrets et données d’exécution ;
- aucun `config.json`, `secrets.json`, fichier `.env`, base, journal ou archive de sauvegarde inclus.

Avant le premier `push`, vérifier localement :

```bash
git status --short
find . -type f \
  \( -name 'config.json' -o -name 'secrets.json' -o -name '.env' \
     -o -name '*.db' -o -name '*.sqlite*' -o -name '*.log' \) -print
```

Initialisation possible :

```bash
git init
git add .
git commit -m "Publication du Portail Entraide Opel GT 1.1.21"
```

Ne publiez jamais un jeton Cloudflare, une sauvegarde, le fichier `/etc/portail-entraide-opel-gt/secrets.json` ni les données de `/var/lib/portail-entraide-opel-gt/`.

## Licences

Le code du portail est distribué sous **GNU AGPL-3.0-only**. Voir [`LICENSE`](LICENSE).

Les principaux composants tiers et leurs licences sont recensés dans [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md). PyMuPDF est distribué sous AGPL-3.0 ou licence commerciale Artifex ; la notice embarquée figure dans [`LICENSES/PyMuPDF.txt`](LICENSES/PyMuPDF.txt).

Le nom, le logo, les bulletins, les PDF, les photographies, les marques et les contenus éditoriaux restent la propriété de leurs titulaires respectifs et ne sont pas placés sous AGPL par la licence du code.

## Auteur

Nicolas Lermé — Entraide Opel GT — Copyright 2026.
