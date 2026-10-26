# Validation du bundle 1.1.28

## Géolocalisation des petites annonces — 27 octobre 2026

Base : `portail-entraide-opelgt-1.1.27.zip`, SHA-256 `5d59bdc3280dbd3412447048ad31bf328be39cb53bc92784b12f1abcb883c97d`. Périmètre fonctionnel limité à la résolution et à la reprise des positions géographiques ; les références de version et la documentation sont alignées.

### Diagnostic et correction

- L’ancien `GeoResolver` initialisait un délai de 30 secondes avant la collecte des sites. Ce délai pouvait être consommé par leur scraping, puis empêcher la localisation de la plupart des annonces. Reproduction sur la base 1.1.27 : 21 lieux valides, 13 secondes de collecte simulée puis 5 secondes par réponse géographique donnaient exactement **3 positions sur 21**.
- Le nouveau budget est de 120 secondes consacrées aux seuls appels géographiques, avec 80 requêtes au maximum. Le temps passé sur les sources n’est pas décompté. Les délais de connexion/lecture passent à 5/10 secondes. Le même test produit **21 positions sur 21**, malgré 105 secondes cumulées de géocodage ; une autre collecte simulée de plusieurs minutes ne fait pas expirer la requête suivante.
- Recherche par code postal, avec rapprochement du nom parmi toutes ses communes ; pas de limite à dix candidats. Reconnaissance des libellés « code postal commune », « commune (code postal) », du département entre parenthèses, du préfixe FR/France et de CEDEX. Une commune ambiguë ou sans coordonnées valides n’est pas positionnée artificiellement.
- Réemploi des réponses positives et des recherches postales identiques. Les anciens enregistrements négatifs sans motif sont repris après la mise à niveau. Les pannes temporaires expirent après cinq minutes ; un budget épuisé ne crée aucune entrée négative. Les bonnes positions en cache sont conservées.
- Au début de la collecte existante, sous le même verrou, les positions manquantes sont complétées dans les annonces enregistrées et leur historique avant tout accès aux sites. Ce traitement ne change ni le statut de réussite de la source, ni les dates d’observation, les prix, les numéros, les favoris ou les événements ntfy. Il est donc utile même lorsqu’une source refuse ensuite sa mise à jour. La commande d’installation déclenche déjà ce service ; aucun effacement manuel du cache n’est requis.
- Les anciennes coordonnées d’une annonce ne sont plus réemployées lorsque sa commune, son département ou son code postal ont changé et qu’aucune nouvelle position n’a pu être confirmée.

### Vérifications

- **436 tests réussis**, avertissements traités comme erreurs. Quinze nouveaux cas couvrent le scénario 3/21, le temps de collecte séparé du budget, les libellés postaux, les codes postaux partagés par plus de dix communes, l’ambiguïté, la migration du cache, les échecs temporaires, les limites, le partage des réponses, la réparation préalable des annonces/historiques et le changement de lieu.
- Essai réel sur l’API publique avec 21 communes françaises : Limours, Paris, Lyon, Marseille, Saint-Étienne, Nantes, Montreuil, Nancy, Saint-Germain-en-Laye, Clermont-Ferrand, Bonifacio, Borgo, Saint-Denis (La Réunion), Strasbourg, Lille, Bordeaux, Toulouse, Montpellier, Poitiers, Tours et Rennes. Les quatre premières recherches ont initialement dépassé l’ancien délai ; 17 ont répondu. Après adaptation du délai, les quatre sont résolues à leur tour en conservant les 17 succès : **21/21 coordonnées confirmées**. Les codes postaux d’arrondissements et les deux départements corses sont inclus.
- Essai de reprise avec 21 annonces synthétiques utilisant ces communes et un historique existant : seulement trois positions initiales, puis toutes les sources artificiellement bloquées. Le cache et l’API contiennent ensuite **21 positions valides**, sans suppression d’annonce ni renumérotation.
- Chromium 134 : **21 boutons de repère numérotés**, quatre couleurs, compteur 21/21, récapitulatif d’un repère et filtrage par source vérifiés à 1440, 390 et 320 pixels. Pas d’erreur JavaScript ni de violation CSP. Les tuiles sont remplacées par une image locale pendant le test ; aucun téléchargement automatique de fond OpenStreetMap n’est effectué.
- Ruff, ShellCheck, syntaxe Bash et des 17 fichiers JavaScript/modules, empreintes des verrous Python et cohérence des versions vérifiées. Les collecteurs d’annonces et dépendances verrouillées ne changent pas.

### Limites

Les 21 annonces privées du serveur de l’utilisateur n’ont pas été fournies : les essais portent sur des lieux représentatifs et des annonces synthétiques, pas sur une lecture de ses données de production. Une absence de connexion, une indisponibilité du géocodeur ou une localisation réellement ambiguë peut encore empêcher une nouvelle position ; les annonces et les coordonnées déjà connues restent conservées. Les repères sont des centres de communes, jamais l’adresse précise d’un vendeur. Aucun appel réel aux sources d’annonces ni envoi ntfy n’a été effectué.

Quatre tests système, tentés séparément, restent limités par cet environnement : sockets Unix refusées (deux tests, avec erreurs de teardown associées), accès IPv4 hors boucle locale sans route et changement de propriétaire non appliqué. Ils restent en CI et sont exclus des 436 réussites. Firefox, Safari et appareils physiques n’ont pas été testés ici.

Les rapports, coordonnées de test, captures internes, caches, journaux et secrets de contrôle sont exclus de l’archive. Les rapports antérieurs suivent comme historique.

---

## Historique — validation du bundle 1.1.27

## Pieds de page et adaptation aux écrans — 26 octobre 2026

Base : `portail-entraide-opelgt-1.1.26.zip`, SHA-256 `db669a167a5d465c8d8a62798055bda400797b02ba6925d38369c48a8aa258f6`.

### Périmètre

- Même contenu statique de pied de page sur les quatre services : 46 badges, règle de séparation, auteur/copyright et « Fait avec amour ❤️ ». Les badges reprennent le même inventaire que le README, avec Python 3.11+, PDF.js 6.4.299 et Leaflet 1.9.4. Ils sont générés sous forme de SVG locaux, sans appel externe ni police téléchargée. Leur inventaire et leurs empreintes sont dans `static/common/badges/manifest.json`.
- Styles et couleurs du pied de page centralisés dans `static/common/footer.css`, y compris marges, taille des badges, retour à la ligne, espacement, texte et cœur rouge. Les anciennes règles spécifiques et les traductions de pied de page devenues inutiles sont retirées.
- Contrôles A−/A+ effectifs sur Bulletins grâce aux variables de taille partagées ; retour à la ligne dans la barre des vues des couples ; adaptation des métriques et du sélecteur de rafraîchissement de l’administration ; commandes de connexion utilisables sur 320 pixels avec texte agrandi.
- Les collecteurs, la logique des services, les routes, les notifications et le déploiement ne changent pas. Les données et tous les composants Python/PDF.js/Leaflet sont conservés ; les références actives du bundle passent à 1.1.27.

### Vérifications

- **421 tests réussis**, avertissements traités comme erreurs. Les nouveaux contrôles empêchent une divergence des quatre pieds de page, vérifient la liste des badges par rapport au README, leur disponibilité locale et leur intégrité SVG. Le contrôle commun couvre désormais les sept pages HTML.
- **96 combinaisons principales** dans Chromium 134 : sept pages (`/`, `/services`, `/bulletins`, `/pieces`, `/couples`, `/annonces`, `/admin`) et formulaire de connexion administrateur ; largeurs/hauteurs 1440×1000, 1024×768, 768×1024, 390×844, 320×568 et paysage 844×390 ; texte normal et agrandi. Aucun débordement horizontal global ni élément de commande hors écran en dehors des zones de défilement local prévues.
- Contrôles supplémentaires des sept onglets d’administration, d’un bulletin synthétique dans le lecteur PDF, du tableau des bulletins, de résultats synthétiques du comparateur, de la carte des annonces et des vues éclatées réelles du référentiel embarqué. Les tableaux, éditeurs, vues et navigations conservent leur défilement local.
- Styles calculés des quatre pieds de page identiques, y compris pour le texte et les marges de la mention finale ; les 46 images SVG chargent correctement. Contrôles en mode sombre, captures ordinateur et téléphone inspectées. Aucune erreur JavaScript ni violation CSP. Les tuiles OSM sont remplacées par une image synthétique pendant les essais ; aucune collecte réelle de catalogue, d’annonce, de bulletin distant ni notification n’est déclenchée.
- Ruff, ShellCheck, syntaxe Bash, syntaxe des 17 fichiers JavaScript/modules et empreintes des verrous Python contrôlées. Les ressources et dépendances verrouillées restent identiques à la base.
- Quatre tests système ont été tentés séparément et restent limités par cet environnement : sockets Unix refusées pour deux tests (avec erreurs de teardown associées), réseau IPv4 hors boucle locale sans route et changement de propriétaire non appliqué. Ils restent présents pour la CI complète et ne sont pas comptés parmi les 421 réussites.

### Limites et livraison

Les essais sont réalisés avec Chromium sur des tailles d’écran simulées ; aucun appareil physique, Firefox ou Safari n’a été validé ici. Les captures de contrôle, données synthétiques, journaux, environnements et fichiers de secrets sont exclus du ZIP. Les rapports des versions antérieures sont conservés ci-dessous comme historique.

---

## Historique — validation du bundle 1.1.26

## Petites annonces — 25 octobre 2026

Base : `portail-entraide-opelgt-1.1.25.zip`, SHA-256 `261e9191d7f57d95c6eefe105ad179bd614fdd782bdcb167256bc4cb174dffe3`. Les changements fonctionnels concernent les petites annonces, leur démarrage contrôlé, leur résumé ntfy et leur carte ; les références de version et la documentation suivent la nouvelle version.

### Fonctionnement et protection des données

- Consultation des derniers résultats pendant le verrou de collecte et publication atomique de chaque source ; affichage d’états réels par source, sans progression temporelle artificielle. Une lecture de la page ne lance jamais une collecte.
- Actualisation manuelle protégée par session membre et CSRF, demande coalescée lorsqu’une collecte tourne et limite globale persistante de 30 minutes. Le canal système accepte uniquement le démarrage de l’unité d’annonces fixe, sans argument de commande fourni par le navigateur. Le même verrou protège le mode autonome.
- Préférences indexées par l’empreinte du sujet authentifié, mises à jour sous verrou et écrites atomiquement. Aucune sélection de compte par le corps de requête. Champs et tailles contrôlés, erreurs sans reprise des valeurs sensibles. Favoris, masquage, lecture et abonnements restent distincts entre comptes.
- Historique persistant : numéro monotone, première observation, dernière observation effective et 50 derniers prix. Une annonce conservée lors d’un échec n’est pas faussement revalidée. Les anciennes annonces sont initialisées sans événement de nouveauté. Les favoris absents d’une collecte complète restent disponibles avec réserve sur leur disponibilité.
- Doublons possibles uniquement entre sources différentes avec modèle connu, année, commune, département et prix identiques. Aucun lien n’est supprimé ; regroupement désactivable.
- Résumé ntfy sur abonnement explicite, désactivé au départ. Nouveautés et baisses des favoris sélectionnées avec dates d’abonnement séparées, fusion persistante des événements, curseur sans duplication et acquittement après succès. Les incidents et résumés respectent le même intervalle d’envoi de 24 h minimum ; aucun résumé vide. Le navigateur explique que le sujet du portail est commun à ses abonnés.
- API des communes : hôte fixe HTTPS, pas de suivi de redirection, rapprochement unique du nom ou du code postal dans le département annoncé, cache positif/négatif et budget de 30 secondes pour la collecte. Aucune adresse vendeur ni géolocalisation du visiteur. Les lieux ambigus/absents restent accessibles dans une liste sous la carte.
- Leaflet 1.9.4 et sa licence embarqués depuis le paquet npm dont l’intégrité SHA-512 a été contrôlée ; huit fichiers d’amont inventoriés par SHA-256. Tuiles OpenStreetMap uniquement pour le fond visible, attribution affichée, cache normal du navigateur et Referer limité à l’origine. Aucune clé Google, CDN JavaScript, tuile préchargée ou ressource cartographique collectée en masse.
- CSP sans `unsafe-inline` ni `unsafe-eval`, authentification et protections existantes conservées. La politique de Referer adaptée à la carte est limitée à `/annonces` ; les autres pages gardent `no-referrer`.

### Vérifications

- **419 tests réussis**, avertissements traités comme erreurs. Les nouveaux cas couvrent les préférences par compte et écritures concurrentes, la migration, la stabilité des numéros, les variations de prix, la conservation des favoris, les filtres et doublons, le géocodage sans correspondance inventée, l’actualisation, le canal système fixe, les abonnements et la livraison ntfy limitée avec reprise après échec, puis les licences et empreintes Leaflet.
- Quatre tests système ont été tentés séparément et restent bloqués par cet environnement : deux sockets Unix refusées par `Operation not permitted` (avec erreurs de teardown associées), accès IPv4 hors boucle locale sans route et changement de propriétaire non appliqué. Ils restent présents pour la CI Linux complète ; ils ne sont pas comptés parmi les 419 réussites.
- Essais réels dans Chromium 134 avec le serveur FastAPI et des annonces synthétiques : compteurs/couleurs, favoris conservés après rechargement, masquage/réaffichage, nouveautés et marquage comme vues, budget, départements, regroupement, plusieurs numéros dans une commune, récapitulatif cliquable, lien avec la liste, filtrage des repères, actualisation sans retrait des cartes, affichage aux largeurs 1440/390/320 pixels sans débordement global. Les repères restent dans la carte après recentrage sur petit écran. Captures ordinateur et mobile inspectées.
- Aucune erreur JavaScript ni violation CSP dans le scénario final. Présence du Referer d’origine vérifiée sur les demandes de tuiles. Le test remplace les tuiles par une image synthétique : aucun téléchargement automatique de tuiles OpenStreetMap par le navigateur de test. L’affichage du fond réel reste soumis à la connectivité du visiteur et au fournisseur.
- Appel réel préalable à l’API officielle pour Limours/91 : retour de la commune unique et de son centre `[2.0823, 48.6463]`. Les tests ordinaires utilisent des réponses contrôlées et n’interrogent pas le géocodeur.
- Ruff, ShellCheck, syntaxe Bash et des 17 fichiers JavaScript/modules, empreintes des verrous Python, cohérence de version et intégrité des composants embarqués contrôlés. Les dépendances Python verrouillées ne changent pas.

### Limites

La collecte Leboncoin et ses erreurs DataDome gardent les limites décrites pour 1.1.25 : cette version ne promet pas de lever les refus du site ni un nombre fixe d’annonces. Aucun scraping réel supplémentaire ni envoi ntfy réel n’a été effectué pendant ces essais. Le démarrage de l’unité et le timer restent à vérifier sur le serveur systemd de destination. Le navigateur Firefox, Safari et les appareils physiques n’ont pas été testés ici. Les localisations sont des centres de communes, pas des positions exactes de véhicules.

Les données synthétiques, préférences de test, captures internes, journaux et environnements de développement ne sont pas inclus dans l’archive livrée. Les numéros d’un ancien cache sans historique deviennent persistants à sa prochaine collecte. Les rapports des versions antérieures suivent ci-dessous.

---

## Historique — validation du bundle 1.1.25

## Correctif Leboncoin 1.1.25 du 24 octobre 2026

Base : `portail-entraide-opelgt-1.1.24.zip`, SHA-256 `67a9388e30468d2cd5a1fac8e248d58147f409093cb54647ff64486e879575ab`. Périmètre limité au client Leboncoin, à la conservation de ses résultats en cas d’interruption, à ses réglages, tests, documentation et version.

### Diagnostic et changements

- `lbc` 1.1.7 peut choisir aléatoirement `chrome131_android`, alors que [son mainteneur conseille de l’éviter depuis le 20 octobre 2026](https://github.com/etienne-hd/lbc/issues/23). Avec `curl-cffi` 0.15.0, l’alias `chrome_android` correspond également à ce profil. Le bundle fixe désormais `safari170` et permet un autre profil supporté via `annonces.leboncoin.impersonate`. Les deux noms du profil défaillant sont refusés. Cela retire cet aléa ; aucun profil ne garantit l’acceptation future du serveur.
- Délai de deux secondes entre les recherches, configurable entre 2 et 30 secondes. Vérification TLS conservée, aucun nouvel essai automatique après refus de recherche et absence de rotation de profils. Le temps d’attente et le délai des requêtes tiennent compte de la limite de collecte.
- Un refus après une première page ou un premier groupe de vendeurs faisait auparavant perdre toutes les nouvelles observations de cette tentative. L’exception de collecte partielle conserve maintenant uniquement les annonces déjà validées par les filtres existants.
- Publication atomique des observations reçues, fusion sans doublons avec les anciennes annonces non revérifiées, priorité aux valeurs fraîchement reçues, protection contre une baisse inhabituelle. Un groupe incomplet conserve ses anciennes annonces absentes du résultat partiel ; un groupe complet peut les retirer, sauf si la baisse déclenche le contrôle de cohérence.
- Le message et le statut continuent de signaler la restriction ou l’échec. Une collecte partielle ne change pas la date de dernière réussite complète. Les alertes ntfy existantes restent donc pertinentes. Les autres sources, filtres France/modèles, tris, prix et planification quotidienne à 02:00 restent en place.

### Essai réel et limites

Un seul essai de collecte a été exécuté depuis cet environnement avec le profil explicite. Il s’est terminé après environ 13,84 secondes par une **collecte partielle avec refus HTTP 403 / DataDome**. Le code a atteint le chemin de conservation des observations ou d’un groupe déjà parcouru ; l’essai n’a pas enregistré de décompte exploitable. Aucune nouvelle tentative n’a été lancée après ce refus.

**La suppression définitive de DataDome et le retour garanti à une vingtaine d’annonces ne sont pas établis.** Le correctif élimine le choix du profil connu comme problématique et la perte des observations déjà obtenues. Un blocage dès le départ peut encore laisser Leboncoin vide en l’absence de cache. Les données disponibles dépendent du site et de la connexion du serveur ; aucun succès depuis le serveur de l’utilisateur n’est présumé. Aucun proxy payant, solveur de CAPTCHA, identifiant ou cookie externe ajouté au bundle.

### Vérifications

- **392 tests réussis**, avec les avertissements traités comme erreurs. Dix-sept cas supplémentaires vérifient le profil déterministe, les profils et délais invalides, les bornes autorisées, les refus et erreurs en cours de pagination, la fermeture des sessions, la première collecte partielle, les fusions sans doublons, les valeurs actualisées, les groupes complets/incomplets et les chutes anormales.
- Quatre tests système ont été tentés séparément et restent bloqués par l’environnement : sockets Unix refusées pour deux tests, absence de route IPv4 non locale et changement de propriétaire non appliqué. Leurs assertions et leur présence en CI sont conservées.
- Ruff, ShellCheck, syntaxes Bash/JavaScript/MJS et empreintes des dépendances verrouillées vérifiés. Les versions des dépendances Python et du moteur PDF embarqué sont inchangées.
- Version **1.1.25** propagée aux métadonnées, paramètres par défaut, exemples, ressources statiques, assertions de tests et instructions courantes. Les références antérieures dans les journaux ci-dessous restent historiques.
- ZIP réextrait et contrôlé avant livraison ; aucune annonce réelle, donnée de vendeur, session, secret, cache ni environnement de test n’est inclus.

## Historique : validation du bundle 1.1.24

## Correctif 1.1.24 du 24 octobre 2026

Base : `portail-entraide-opelgt-1.1.23.zip`, SHA-256 `88d35238ed87e094f1f151b6d8551020fefdd50c096830e95a69f4933974f1c3`. Périmètre : affichage des bulletins, ressources nécessaires à la visionneuse, contrôles associés, documentation et version.

### Correction et protection des données

- Cause constatée : l’iframe chargeait directement une réponse PDF portant `X-Frame-Options: DENY` et `frame-ancestors 'none'`. Le lecteur natif dépendait également de sa disponibilité dans le navigateur, notamment sur mobile.
- Remplacement par PDF.js 6.4.299, build legacy, chargé à la première consultation. Les pages sont dessinées dans un canvas, sans iframe ni lecteur PDF natif. Les titres et boutons des bulletins ainsi que des résultats de recherche ouvrent la même fenêtre ; les clics modifiés conservent le comportement du lien natif.
- Navigation précédente/suivante, numéro de page et zoom, ajustement après redimensionnement ou rotation, ouverture à la page du résultat de recherche. Une seule page est rendue à la fois, avec au maximum huit millions de pixels pour son canvas. Annulation et destruction du chargement/rendu à la fermeture, à la déconnexion et lors d’une nouvelle ouverture. Protection contre les événements de fermeture différés après réouverture.
- Le worker, les polices standards, CMaps et décodeurs d’image sont embarqués ; aucune ressource de la visionneuse n’est chargée depuis un CDN. Le paquet npm amont a été vérifié avec son intégrité SHA-512. Les notices sont conservées et les 201 fichiers d’amont sont inventoriés avec leur SHA-256 dans `UPSTREAM.json`.
- Les routes PDF et leurs contrôles d’authentification sont conservés. Les réponses complètes et partielles sont protégées par `no-store`. Les accès anonymes, y compris avec un en-tête Range, restent refusés. La visionneuse n’accepte que les URL de bulletins de la même origine.
- Les interdictions d’intégration du portail dans une iframe restent actives. Les workers sont limités à l’origine locale ; l’autorisation WebAssembly concerne seulement la page Bulletins et les ressources PDF.js. L’évaluation JavaScript dynamique reste interdite et `isEvalSupported` est désactivé dans le moteur PDF.

### Contrôles effectués

- **375 tests réussis**, avertissements traités comme erreurs. Trois tests supplémentaires couvrent la protection et les lectures partielles des PDF, les types MIME et la CSP limitée à la visionneuse, puis l’intégrité et la présence des ressources nécessaires au fonctionnement local. Quatre tests système nécessitant des capacités indisponibles dans cet environnement restent exclus et présents pour la CI Linux complète.
- Chromium 134, lecteur PDF natif désactivé : contrôle effectif des pixels rendus, textes et image JPEG 2000 nécessitant le décodeur OpenJPEG embarqué. PDF synthétique de trois pages dépassant le seuil des requêtes partielles ; neuf réponses HTTP 206 observées par scénario.
- Écrans 1280 × 900, 390 × 844, paysage 844 × 390 et petit écran 320 × 568 avec texte agrandi : lecture, navigation, saisie du numéro de page, zoom, rotation et hauteur disponible de la zone de lecture vérifiés. Rendu ordinateur et mobile inspecté visuellement.
- Ouverture depuis les résultats à la page demandée, fermeture suivie immédiatement d’une autre ouverture, effacement du canvas à la fermeture, document absent avec message explicite, puis expiration de session avec retour à la connexion. Aucune erreur JavaScript ni violation CSP pendant ces essais. Les avertissements concernant les badges externes volontairement bloqués et les réponses 404/401 provoquées par les tests sont attendus.
- **Limite des essais navigateur :** Firefox 135 a pu démarrer mais pas ouvrir une page de test ; WebKit 18.4 a fermé son contexte lors de cette étape. Aucun contenu du portail n’a donc été testé sur ces deux moteurs ici. Ces essais Chromium ne constituent pas une validation sur tous les navigateurs et appareils de l’utilisateur.
- Ruff, ShellCheck, syntaxe Bash et syntaxe de tous les fichiers JavaScript et modules MJS vérifiés. Le workflow CI prend désormais en compte les modules MJS. Les verrous des dépendances Python sont inchangés.
- Version **1.1.24** propagée aux métadonnées, exemples, ressources HTML, chargement de la visionneuse, assertions de tests et instructions courantes. Les versions de composants tiers et les références historiques restent distinctes.

Aucun bulletin privé n’a été utilisé ni ajouté au bundle : les essais visuels utilisent uniquement un document synthétique. Les captures internes, données de test, navigateurs et bibliothèques de validation sont exclus du ZIP. L’archive est réextraite et comparée aux fichiers validés avant livraison.

## Historique : validation du bundle 1.1.23

## Modifications 1.1.23 du 24 octobre 2026

Base : `portail-entraide-opelgt-1.1.22.zip`, SHA-256 `bf1d42ec8f383a1c4cef732971985edfb32adc8d6cb0b335128615e36ed5c46c`. Révision limitée à l’ajout des badges au début du README, à la version et à ses documents de suivi.

- **43 badges** regroupés en cinq rubriques : langages et formats ; application et collecte ; données, documents et OCR ; hébergement et notifications ; développement et validation. Inventaire établi à partir des imports, des dépendances verrouillées, de l’installation et du workflow CI du bundle.
- Badges statiques Shields.io : noms et textes alternatifs vérifiés, URL encodées selon le format officiel ; les 43 images ont répondu en HTTP 200 et leur contenu SVG a été analysé pour vérifier le nom attendu. Aucun statut de tests ou de déploiement distant n’est présumé.
- Le contenu du README après les badges reste identique à la base, à l’exception du numéro de version. Comparaison de chaque fichier avec l’archive 1.1.22 : autres différences limitées au journal des versions, au présent rapport et aux substitutions de version. Aucun changement de dépendance ni de code fonctionnel.
- **9 tests de cohérence de version réussis**, dont les huit commandes de scrapers `--version`, avec les avertissements traités comme erreurs. Ruff, syntaxe Bash et empreintes des dépendances verrouillées vérifiés. La suite fonctionnelle complète n’a pas été relancée pour cet ajout documentaire ; ses résultats antérieurs restent dans l’historique ci-dessous.
- Version **1.1.23** propagée dans `VERSION`, les métadonnées Python, les exemples d’agents HTTP, les paramètres de cache des ressources HTML, les assertions de tests et les instructions courantes du README. Les références antérieures dans les journaux ci-dessous restent historiques.
- ZIP final vérifié par réextraction et comparaison avec les fichiers validés. Aucun secret, fichier de production, cache, environnement de test ni aperçu de contrôle inclus.

## Historique : validation du bundle 1.1.22

## Modifications 1.1.22 du 24 octobre 2026

Base : `portail-entraide-opelgt-1.1.21.zip`, SHA-256 `aa0619368b3baec2c5652c3146a8fab5be5cc9922200562e089224c8fdfd987b`. Modifications limitées à la réorganisation du README, au retrait de code sans appelant et à la propagation de la version. Aucun changement de dépendance, d’horaire ni de comportement fonctionnel prévu.

- README : historique de versions retiré de l’introduction ; paragraphe introductif des captures et passage des essais réels jusqu’à la mention des captures documentaires supprimés ; aperçu Petites annonces limité à sa capture ; description demandée reproduite à l’identique et suivie immédiatement du tableau Source/Périmètre/Collecte dans Services inclus.
- Sections ntfy et Cloudflare résumées ; informations sur les catalogues replacées avec le comparateur ; détection Internet regroupée avec la configuration ; sommaire complet et liens locaux vérifiés ; section Publication sur GitHub retirée ; mention « Fabriqué avec amour ❤️ » ajoutée après Copyright 2026.
- Nettoyage : retrait de 16 fonctions et d’une classe sans appelant, de sept constantes de couleur et de huit imports devenus inutiles. Recherche de références dans le bundle et vérification des suppressions par comparaison des arbres syntaxiques avec la base. Routes HTTP, commandes CLI, fonctions d’entrée des scrapers et chemins de migration utilisés conservés.
- Version **1.1.22** contrôlée dans `VERSION`, les métadonnées Python, les agents HTTP par défaut et exemples, l’API de santé, les en-têtes du script serveur, les huit commandes de scrapers et les paramètres de cache des pages HTML. Les mentions antérieures dans CHANGELOG et les rapports ci-dessous sont des références historiques.
- **372 tests réussis**, avec les avertissements traités comme erreurs. Les quatre tests système complémentaires ont été tentés séparément et restent bloqués par cet environnement : création de sockets Unix refusée pour deux tests (`Operation not permitted`), absence de route réseau pour le test IPv4 non local et changement de propriétaire non appliqué pour le test d’installation. Ils restent présents pour une exécution Linux complète, sans modification ni assouplissement de leurs assertions.
- Ruff global et contrôle additionnel des imports/variables inutilisés dans tous les scrapers ; ShellCheck, syntaxes Bash et JavaScript, empreintes des dépendances verrouillées vérifiés.

Les captures documentaires existantes sont conservées à l’identique. Aucun accès réel aux sites de collecte ni envoi ntfy nécessaire à cette révision. Le ZIP final est contrôlé par réextraction et exclut les secrets d’exploitation, caches, bases, journaux et environnements de validation.

## Historique : validation du bundle 1.1.21

## Modifications 1.1.21 du 23 octobre 2026

Base : `portail-entraide-opelgt-1.1.20.zip`, SHA-256 `01b600b3f2d54f669c03d59029f48bcd892196e9881b6d91a306db7898e0662e`. Modifications limitées aux deux captures fournies et au README, aux réglages et à la limite de fréquence ntfy dans l’administration, à leur documentation/tests et à la version. Collecteurs d’annonces, scrapers de pièces et horaires de collecte inchangés.

- Les fichiers `docs/screenshots/liste-services.png` et `docs/screenshots/petites-annonces.png` sont des copies identiques octet pour octet des pièces jointes demandées ; les deux images sont référencées dans le README. La mention obsolète de la capture Services antérieure à l’ajout des annonces est retirée.
- Administration : nouvel onglet Notifications, activation, serveur/sujet, choix d’authentification, remplacement de jeton ou mot de passe, intervalle en jours et rechargement. Les champs secrets sont masqués et vides après chargement, enregistrement, échec ou expiration de session. Les réponses API ne contiennent que des indicateurs de présence des secrets.
- Authentification administrateur, CSRF et absence d’écho d’identifiants même sur des requêtes invalides vérifiés. Une écriture de production passe par l’action root limitée `save-ntfy`. Les autres secrets, propriétaires et permissions du fichier sont conservés ; une valeur secrète vide conserve l’identifiant existant pour le même mode d’authentification.
- Limite globale : un seul message ntfy au maximum toutes les 24 heures, ou selon un intervalle plus long de 1 à 365 jours. Les valeurs plus fréquentes, non entières ou invalides sont refusées. Les événements sont regroupés, le dernier envoi réussi est persistant et les tests manuels utilisent la même limite. Les messages trop longs laissent leur surplus en attente.
- Tests du passage exact de la borne de 24 heures, de la persistance après redémarrage, du changement d’intervalle, des envois refusés et de la conservation des événements. Les contrôles du moniteur restent effectués chaque minute.
- Chromium 134 : navigation vers Notifications, saisie et enregistrement jeton/mot de passe, remise à vide des champs, conservation implicite des secrets, validation de la fréquence minimale, rechargement, rendu ordinateur et 390 px sombre sans erreur JavaScript. Données synthétiques et captures de contrôle conservées hors du ZIP.
- **372 tests réussis**, avertissements traités comme erreurs. Quatre tests système restent exclus dans cet environnement : deux sockets Unix, accès sur une adresse IPv4 non locale et modification de propriétaire. Ils sont conservés pour la CI Linux complète.
- Ruff, ShellCheck, syntaxe Bash/JavaScript, cohérence des versions et empreintes des dépendances vérifiées. Aucun changement de dépendance.
- Version **1.1.21** propagée aux métadonnées, exemples, ressources statiques, tests et instructions courantes. Les références de versions antérieures ci-dessous restent historiques.

Aucun message ntfy réel n’a été envoyé pendant les tests : publications et données de compte synthétiques. L’installation sur le serveur de l’utilisateur reste à effectuer. Le ZIP est vérifié après réextraction et exclut les secrets d’exploitation, files d’attente, bases, caches, environnements et captures internes ; seules les deux captures explicitement demandées sont ajoutées à la documentation.

## Historique : validation du bundle 1.1.20

## Ajouts 1.1.20 du 23 octobre 2026

Base : dernière version `portail-entraide-opelgt-1.1.19.zip`, SHA-256 `32cf0002a5e66cb55f368da556b23c1e299ce741ecd32912e9bac8ee1814c4b0`. Modifications limitées aux notifications ntfy, au collecteur Leboncoin demandé, aux prix et aux deux nouvelles sources d’annonces, à la version, aux dépendances nécessaires et à leur documentation/tests. Les huit scrapers de pièces sont inchangés.

### Notifications

- Tests de la file persistante : deux échecs de connexion, incident conservé hors ligne, reprise du moniteur, envoi ordonné de l’incident puis du rétablissement, absence de répétition à chaque contrôle et conservation lors d’un refus ntfy.
- Publication JSON ntfy testée avec réponses contrôlées : aucune authentification, jeton Bearer et authentification Basic UTF-8. Redirections refusées, délais bornés, titres Unicode et absence d’identifiants dans les journaux.
- Configuration interactive avant installation des paquets, saisie masquée, validation HTTPS/sujet/authentification, conservation des autres secrets et permissions `0600`/`0640` vérifiées.
- Désinstallation simulée avec unités actives : arrêt/désactivation du moniteur, purge effective du fichier de secrets et de la file d’attente ; conservation de la configuration lors d’une désinstallation sans purge. La gestion Cloudflare précédente est conservée.
- Le moniteur utilise son propre timer et ne dépend pas du démarrage du serveur web. Les contrôles de résultats catalogues/annonces, des workers et du connecteur Cloudflare sont testés avec états contrôlés.
- Aucun identifiant ntfy réel n’a été fourni ici : l’envoi réel est testé en fin d’installation sur le serveur, une fois les paramètres saisis. Une coupure Internet diffère l’envoi ; une panne complète du serveur nécessite une surveillance externe.

### Annonces et interface

- `lbc==1.1.7`, `curl-cffi==0.15.0` et leurs dépendances nouvelles sont verrouillés. Le collecteur appelle `lbc.Client.search`, sépare les recherches particuliers/professionnels, contrôle leur pagination et ferme la session. Il ne consulte pas les profils vendeurs. La pagination incomplète et DataDome conservent les anciennes annonces.
- Essai réel Leboncoin : HTTP 403 / DataDome depuis cet environnement distant, malgré l’utilisation de `lbc`. Aucune réussite depuis la connexion du serveur utilisateur n’est présumée.
- Essais réels : 9 annonces françaises sur lesAnciennes avec prix ; 1 sur Classic Number (enchère, indiquée comme telle), sur 3 offres consultées ; 0 sur Classic Trader, dont les 9 offres consultées sont étrangères ou modernes. Le résultat vide de Classic Trader est un résultat filtré valide.
- Tests des prix, devises, informations absentes, types de vendeur, dates originales, photos, liens directs, filtrage France/modèles, données Astro et structures inattendues. Aucune date de mise à jour n’est substituée à la date de publication.
- Chaque source est limitée à 180 secondes et 20 pages ; la collecte globale reste encadrée par le service de quinze minutes.
- Chromium 134 : quatre sources cochées initialement, prix sous les photos, liens directs, filtrage, masquage/reprise pendant collecte, rendu ordinateur et 390 px en mode sombre, sans erreur JavaScript ni débordement global. Données et photos synthétiques utilisées uniquement hors du bundle.

### Contrôles

- **359 tests réussis**, avec avertissements traités comme erreurs. Quatre tests système exclus pour les restrictions de cet environnement : deux sockets Unix, une adresse IPv4 non locale et une modification de propriétaire. Ils restent inclus dans la CI.
- Ruff, ShellCheck, syntaxe Bash et de tous les JavaScript, compilation Python et empreintes des dépendances vérifiées.
- Cohérence de `VERSION`, métadonnées, exemples, API, commandes `--version`, ressources statiques, README et tests en **1.1.20**. Les mentions de versions antérieures ci-dessous restent historiques.
- ZIP contrôlé après réextraction, permissions exécutables, absence de secrets de production, données réelles de collecte, bases, caches, journaux, environnements Python et captures de test.

La mise en service réelle se fait avec `sudo ./run_server.sh install`. Aucune installation sur le serveur de l’utilisateur n’a été effectuée ici.

## Historique : validation du bundle 1.1.19

## Ajouts et correctif 1.1.19 du 23 octobre 2026

Base : pièce jointe `portail-entraide-opelgt-1.1.18(2).zip`, SHA-256 `bc78eeae440500dedbe5d7227dd05dd65126cb3024da8ff1fcbf3cfb48997b16`. Modifications limitées au service Petites annonces, au blocage des pages pendant sa mise à jour, au correctif GT Teile, à l’incrément de version et à leurs tests et documentation.

### Petites annonces

- Collecte réelle lesAnciennes : **9 annonces** d’Opel GT d’époque situées en France, avec modèle, année, département, date de publication originale et photo. Les véhicules étrangers et GT modernes présents dans la même recherche sont exclus. Huit annonces ne fournissaient pas le type de vendeur dans les résultats publics : elles sont signalées « Type non précisé », sans déduire « particulier » d’un badge absent.
- Leboncoin : refus réel **HTTP 403**, et restrictions d’automatisation présentes dans son robots.txt. Le connecteur public est fourni et ses données structurées sont testées avec des réponses synthétiques ; sa collecte réelle ne peut pas être validée tant que cet accès est restreint. Aucune donnée n’a été inventée ni protection contournée.
- Tests des trois modèles, du périmètre France, des départements (dont Corse et outre-mer), des dates, photos et liens, de la pagination complète et des refus de structure ou d’accès. Échecs par source, conservation des derniers résultats et reprise après arrêt du processus testés.
- Verrou partagé avec les lecteurs et exclusif pour la collecte : les réponses API ne contiennent aucune annonce pendant une mise à jour, y compris si un ancien fichier d’annonces existe. Une brève lecture ne doit pas faire sauter l’échéance quotidienne. Un fichier de statut ancien ne suffit pas à bloquer le service après la mort du processus.
- Authentification et absence de collecte déclenchée par les pages/API vérifiées. Les deux unités systemd sont intégrées à l’installation et à la désinstallation ; timer quotidien exact `*-*-* 02:00:00 Europe/Paris`, rattrapage activé et durée maximale de quinze minutes.
- Chromium : sélection initiale des deux sources, filtres conservés après rafraîchissement, tri réversible, liens directs, une photo par carte, masquage pendant collecte ou perte de l’état, réapparition à la fin, et désactivation/réactivation de la carte Services. Contrôle visuel sur ordinateur et à 390 px en mode sombre, sans débordement global ni erreur JavaScript. Essais avec données synthétiques et photos de test, hors du bundle.

### GT Teile

Essai réel complet : **15 catégories**, **19 pages**, **748 pièces uniques**, **748 prix connus** et **748 disponibilités connues**, en **134,1 secondes**. Aucune fiche produit individuelle consultée. Le traducteur étant indisponible, les désignations originales ont été conservées pour les traductions manquantes ; la collecte des prix a abouti.

Les régressions vérifient l’absence d’appel de traduction lors de l’extraction d’une page, l’interruption des lots après HTTP 429 malgré un `Retry-After` long, la réutilisation des traductions antérieures, les limites réseau/parallélisme, les phases monotones et la conservation du dernier catalogue à l’expiration du délai maximal. La durée en production est plafonnée à 1 800 secondes, ou au délai configuré s’il est inférieur.

### Contrôles du bundle

- **335 tests automatisés réussis**, avec avertissements traités comme erreurs ; quatre tests système exclus dans cet environnement : deux sockets Unix (`Operation not permitted`), accès sur une adresse non locale et restauration de propriétaire (`chown`). Ces tests restent présents pour une machine Linux complète et la CI.
- Ruff, ShellCheck, syntaxe Bash et JavaScript, compilation Python et empreintes des dépendances verrouillées vérifiées.
- Cohérence de `VERSION`, métadonnées, API, en-tête serveur, huit commandes `--version`, configuration exemple et ressources HTML en **1.1.19**. Les références historiques ci-dessous restent inchangées.
- Vérification du ZIP réextrait, du mode exécutable de `run_server.sh`, de son intégrité et de l’absence de secrets, annonces réelles, catalogues, caches, journaux, bases et environnements Python d’exploitation.

La mise en service des unités systemd sur le serveur de l’utilisateur reste à effectuer par `sudo ./run_server.sh install`. Aucun déploiement sur cette machine n’a été réalisé ici.

## Correctif 1.1.18 du 23 octobre 2026

Base : dernier ZIP corrigé Edelschmiede, intégrant déjà les corrections ATZ, Opel GT Source et de surveillance Cloudflare. Le périmètre de cette version est limité à la progression des huit catalogues, à l’arrêt de Cloudflare lors de la désinstallation, à la propagation du numéro de version et à leurs tests et documentation. Les sections suivantes conservent les validations historiques.

- **299 tests réussis**, avec avertissements Python traités en erreurs ; quatre tests système exclus pour les restrictions déjà constatées de cet environnement : changement de propriétaire, accès IPv4 local non routable et deux sockets Unix interdits.
- Pour les huit fournisseurs, un véritable sous-processus publie plusieurs états intermédiaires observés avant le remplacement du catalogue. La progression est monotone, le fichier précédent reste intact pendant la collecte et 100 % est publié uniquement à la clôture. Les délais maximaux et la conservation du catalogue précédent sont vérifiés pour chaque fournisseur.
- Les boucles réelles des scrapers sont testées avec réponses réseau ou tâches contrôlées : fiches Opelix, pages et traductions Splendid, catégories et pages GT Teile, pages dans les deux langues et appariement Oldtimer, découverte progressive de pages TW, collecte et traduction indisponible ATZ / Opel GT Source, ainsi que les régressions Edelschmiede conservées.
- Quatre processus concurrents incrémentent le même compteur sans perte ni fichier partiellement lisible. Un essai avec processus descendant vérifie que le délai maximal termine aussi les workers et ferme leurs sorties héritées.
- Désinstallation simulée avec services actifs et activés : arrêt de la surveillance avant Cloudflare, purge des installations avec ou sans marqueur de gestion, nouvelle purge sans erreur, conservation des autres surcharges et interruption explicite si l’arrêt d’un service échoue.
- `VERSION`, métadonnées Python, API, en-tête serveur, huit commandes `--version`, paramètres par défaut et versions de ressources HTML sont contrôlés en **1.1.18**. Les numéros des entrées historiques restent inchangés.
- Syntaxes Python, Bash et JavaScript, ShellCheck, intégrité des verrous de dépendances et Ruff sur les fichiers ajoutés ou modifiés hors l’import inutilisé `time` préexistant de `app/main.py` vérifiés. Aucun fichier de travail ni donnée de tests n’est destiné au ZIP public.

Les huit catalogues et le service Cloudflare sont vérifiés ici avec des données et commandes contrôlées. Cette version n’a pas été installée sur le serveur de l’utilisateur ; le test du tunnel réel après purge devra se faire sur cette machine. Les essais en ligne des versions antérieures sont conservés ci-dessous avec leur contexte.

## Correctif Edelschmiede du 23 octobre 2026

Périmètre de ce correctif : scraper Edelschmiede, suivi et bornage de son seul sous-processus dans l’orchestrateur, tests et documentation correspondants. Le point de départ est le dernier bundle corrigé ATZ / Opel GT Source / Cloudflare. Les autres fichiers applicatifs sont identiques à cette version. Les sections suivantes conservent les validations antérieures.

### Blocage corrigé

Le scraper cumulait jusqu’à cinq reprises réseau supplémentaires pour chaque requête, y compris les appels de traduction individuels, et pouvait attendre longtemps le délai `Retry-After` d’un service limité. Ses options de délai et de parallélisme n’étaient pas appliquées. Le portail fixait la progression à 5 % puis attendait la fin du sous-processus, sans recevoir ses compteurs.

La correction borne les requêtes, applique les options, réutilise la traduction groupée avec cache et interruption sur panne, et publie des instantanés atomiques de progression à partir du nombre réel de pièces traitées. Le portail les relaie pendant l’exécution ; 100 % reste réservé à l’état terminal après les contrôles du catalogue. La durée totale d’Edelschmiede est limitée à 30 minutes, ou au délai global configuré s’il est inférieur. Un dépassement termine et récupère le sous-processus, ferme le suivi et conserve le catalogue précédent.

### Essai complet en ligne

- Parcours déclenché par l’orchestrateur réel avec le même sous-processus que le worker du portail.
- **14 pages et 277 pièces récupérées en 118 secondes**, avec 277 prix numériques et 277 disponibilités connues.
- Progression observée pendant l’exécution : 6 %, 10 %, puis incréments liés aux compteurs de pièces, phase de traduction à 90 %, fin à **100 %** après validation et archivage.
- Service de traduction indisponible lors de l’essai : les 277 désignations originales ont été conservées sans empêcher la mise à jour du catalogue. Elles seront retentées à une prochaine mise à jour et les traductions existantes sont réutilisées lorsqu’elles sont disponibles.
- Aucun catalogue réel, cache, journal, cookie ou donnée d’exploitation issu de cet essai n’est inclus dans le ZIP destiné à GitHub.

### Tests et contrôles

- **259 tests réussis**, avertissements Python traités en erreurs. Quatre tests système exclus pour les mêmes restrictions de l’environnement que lors de la version précédente (changement de propriétaire, accès IPv4 local et deux sockets Unix).
- Quinze nouvelles régressions couvrent notamment les erreurs 429 et délais réseau, l’arrêt des requêtes répétées, la traduction indisponible, le respect des options CLI, la progression intermédiaire d’un véritable sous-processus, l’expiration du délai maximal et la conservation du catalogue précédent.
- Vérification que le compteur ne régresse pas, qu’un statut terminé n’est pas écrasé et qu’un catalogue incomplet n’est jamais publié.
- Ruff vérifié sur l’orchestrateur et les nouveaux tests ; compilation du scraper et de l’orchestrateur validée. Les contrôles Bash, JavaScript et des verrous de dépendances du bundle restent applicables. L’import `time` inutilisé déjà signalé dans `app/main.py` est conservé hors périmètre.

## Correctif ciblé du 23 octobre 2026

Périmètre : mises à jour ATZ / Opel GT Source et maintien du tunnel Cloudflare. Les pages, styles, documents, dépendances et paramètres fonctionnels du portail n’ont pas été modifiés. Les sections historiques ci-dessous décrivent les validations précédentes.

### Catalogues : validation réelle

- Erreurs HTTP 429 reproduites sur le service de traduction utilisé par les deux scrapers.
- ATZ : 14 pages de recherche et la catégorie complémentaire lues, **1 136 produits uniques** écrits et schéma JSON validé.
- Opel GT Source : 65 pages catalogue lues, **683 pièces uniques** écrites, conversion USD/EUR et schéma JSON validés.
- Les deux parcours complets ont terminé avec un code de retour 0 malgré la limitation du service de traduction ; aucune fiche produit individuelle n’a été ouverte. Les prix et disponibilités ont été récupérés avec les désignations originales lorsque la traduction manquait.
- La réutilisation des traductions existantes, les associations nom/traduction et la nouvelle tentative des noms non traduits au prochain passage sont couvertes par des tests. Une panne de traduction ne produit plus une multiplication récursive de requêtes.

### Cloudflare : validation simulée

- Installation du fichier de surcharge, activation conditionnelle du timer, passage à HTTP/2 et absence de jeton dans les nouveaux fichiers vérifiés avec commandes système simulées.
- Contrôles périodiques de l’origine et du point `/ready`, récupération après trois échecs consécutifs, remise à zéro après un succès et respect d’un arrêt volontaire testés.
- La connexion Cloudflare réelle, le redémarrage de la machine et la tenue du tunnel pendant une longue période d’inactivité doivent être vérifiés sur le serveur de l’utilisateur : cet environnement ne dispose ni de son jeton ni de ses journaux. La cause précise de la coupure initiale n’est donc pas établie ici.

### Contrôles automatisés

- **244 tests réussis, 4 tests exclus pour restrictions de l’environnement** : un changement de propriétaire refusé par le système de fichiers, un accès réseau IPv4 local non routable et deux tests de sockets Unix non autorisés. Les nouvelles régressions sont toutes exécutées et réussies.
- Tests lancés avec avertissements Python traités en erreurs, environnement Python isolé et variables de proxy retirées pour les seuls tests sans réseau.
- `bash -n`, ShellCheck, Ruff sur les fichiers ajoutés et le code applicatif modifié, syntaxe JavaScript et empreintes des dépendances vérifiés.
- Le contrôle Ruff global retrouve un import `time` inutilisé préexistant dans `app/main.py` ; ce fichier est conservé identique à la pièce jointe pour respecter le périmètre demandé.
- Les données réelles de validation et les fichiers de travail ne sont pas intégrés au ZIP distribué. L’historique `.git` présent dans la pièce jointe est exclu de l’archive destinée au dépôt public.

Date de fabrication initiale : **6 août 2026**.

Ce rapport distingue les contrôles reproductibles exécutés dans l’environnement de fabrication des opérations nécessitant le serveur Linux cible, des identifiants membre réels ou l’accès direct aux fournisseurs.


## Corrections 1.1.17

- Les logos communs sont des PNG RGBA ; les zones blanches du JPEG source sont transparentes et aucune règle CSS ne recrée un fond blanc.
- Les deux formulaires de connexion utilisent le même gabarit de 34 rem, les mêmes espacements, champs, polices et bouton bleu.
- Les quatre commandes Internet, thème et taille du texte restent sur une ligne sans ascenseur horizontal ou vertical ; elles peuvent se contracter sur les petits écrans.
- Les titres visibles et les titres de fenêtre utilisent « Page de connexion membre » et « Page de connexion administrateur ».
- Le texte administrateur demandé est regroupé dans un seul paragraphe et le rappel de session est placé sous le bouton de connexion avec une durée mise à jour dynamiquement.
- Les six cartes de l’onglet « État général » utilisent toutes le même bleu.
- Les cartes de l’onglet « Statistiques » utilisent le vert, l’orange, le rouge ou le noir selon la métrique ; les ratios pertinents affichent un pourcentage calculé.
- Les codes pays ISO à deux lettres sont convertis en emoji drapeau dans la colonne Pays des connexions par adresse IP.
- Les métadonnées, le README et les tests sont cohérents en version 1.1.17.

## Corrections 1.1.16

- Le timer catalogue exécute désormais les récupérations les lundi, mercredi et vendredi à 02:00 en Europe/Paris, sans rattrapage au redémarrage.
- Le calcul de la dernière échéance catalogue prend en charge plusieurs jours dans une même semaine et sélectionne correctement l’occurrence la plus récente.
- Les boutons de thème indiquent partout le mode cible : « Mode sombre » sur une page claire et « Mode clair » sur une page sombre.
- Le scraper TW-Oldtimerteile n’appelle plus la fonction inexistante qui faisait échouer la collecte après le comptage des catégories ; la catégorie exclue reste ignorée sans ouverture de fiche individuelle.
- Le scraper Splendid Parts utilise une session persistante, initialise les cookies PrestaShop, limite volontairement son débit et réessaie progressivement les réponses 403/429 transitoires.
- Les contrôles de disponibilité distinguent désormais une boutique hors ligne d’une boutique joignable qui restreint l’automatisation ; aucune règle robots.txt n’est contournée.
- Les métadonnées, le README, les unités systemd et les tests sont cohérents en version 1.1.16.

## Corrections 1.1.14

- Les cinq cartes de la liste des services adoptent une hauteur naturelle : les espaces vides précédant les boutons ont été supprimés, les titres sont centrés et les boutons d’ouverture sont bleus.
- Les trois boutons de téléchargement de la page Couples de serrage sont centrés dans toute la largeur du référentiel.
- Les titres « Connexion au portail » et « Connexion administrateur » sont centrés et utilisent la même taille ; le texte de durée de la session administrateur a été remplacé par la formulation demandée.
- Les trois pages de service conservent uniquement « Retour à la liste des services » et « Accès à la page d’administration », avec un fond bleu uniforme.
- L’éditeur JSON et les visionneuses de logs utilisent une ligne de grille contrainte, un ascenseur vertical visible et manipulable, un ascenseur horizontal lorsque nécessaire et une gouttière stable.
- Le tableau des tâches de fond utilise des fonds et badges sémantiques selon l’état ; les cartes d’État général et de Statistiques utilisent des badges colorés distincts.
- Le README et les métadonnées de version ont été actualisés.

## Résultat global

- **231 tests automatisés réussis**, avec tous les avertissements Python traités comme des erreurs.
- Compilation Python et syntaxes Bash, JavaScript et JSON validées.
- Rendus Chromium vérifiés aux largeurs 390, 768 et 1 440 px ; défilement effectif de l’éditeur de configuration et des visionneuses de logs contrôlé avec du contenu long.
- Les règles responsive, les libellés, les ressources, les titres, les contrôles communs et l’absence des anciens textes sont couverts par la suite automatisée. Les sept nouvelles captures fournies ont été intégrées au README.
- Démarrage HTTP réel, création des bases, réponse de `/api/health` en version 1.1.17 et arrêt propre validés.
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
- Les récupérations périodiques sont planifiées les lundi, mercredi et vendredi à 02:00 en Europe/Paris, sans rattrapage au redémarrage.
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
- timer catalogues exact `Mon,Wed,Fri *-*-* 02:00:00 Europe/Paris`, `Persistent=false`, sans délai aléatoire ;
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
231 passed
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
OnCalendar=Mon,Wed,Fri *-*-* 02:00:00 Europe/Paris
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
- version retournée : `1.1.17` ;
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
