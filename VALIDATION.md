# Validation du bundle 1.1.38

Date : 9 novembre 2026. Base : `portail-entraide-opelgt-1.1.37.zip`, SHA-256 `4739757166cb7d973fad58683c924f0394d41d77f722d4c571a98ed07019d317`.

## Périmètre

- Couples de serrage : retrait des vues 4 à 7, de leurs huit documents et de leur fichier de provenance. Les trois vues conservées portent leur emplacement réel : suspension avant et direction ; suspension avant et freins ; direction. Aucune vue du moteur ou de la suspension arrière n'est annoncée parmi ces trois schémas.
- Les 61 lignes, leurs valeurs, les sections, les documents antérieurs et les coordonnées des repères des vues 1 à 3 restent identiques à la base. Seules les correspondances vers les vues retirées sont supprimées.
- Mode d'emploi actualisé, taille de police commune aux deux titres et poignée de hauteur commune aux deux volets. Réglage conservé après rechargement, utilisable à la souris et au clavier, y compris lorsque les volets passent l'un sous l'autre.
- QR codes des deux connexions recalculés après redimensionnement et zoom, modules alignés sur les pixels physiques et affichage agrandi au clic. L'adresse reste celle du portail consulté, avec le chemin `/` ou `/admin`, sans paramètres ni fragment. Aucun générateur externe utilisé.
- Leboncoin : recherche sans élargissement automatique, total explicite, réutilisation des sessions anonymes par profil, un seul profil de recours temporisé avant réception de la première page et pause persistante de deux heures après refus. Le refus et le caractère incomplet d'une collecte restent visibles ; les données précédentes sont conservées. L'accueil propose la recherche directe lorsque la source est indisponible.
- Version 1.1.38 propagée aux fichiers actifs. Aucune dépendance de production ajoutée ou mise à jour.

## Tests automatisés et contrôles statiques

- **524 tests réussis, 14 désélectionnés**, avec avertissements traités comme erreurs. Les tests de transport passent par le véritable SDK `lbc` avec un transport HTTP simulé : refus, temporisation, pagination, identité et cookies persistants, permissions `0600`, reprise après fichier corrompu, isolement des profils et pause après refus.
- Le premier passage complet a révélé les limites de cet environnement : exécution sans privilèges root pour les tests de désinstallation, sockets Unix refusés et réseau IPv4 hors boucle locale inaccessible. Une assertion portant sur l'ancien texte d'aide a été actualisée. Les tests système concernés sont toujours présents ; ils ne sont pas présentés comme validés ici. Le fichier de tests de désinstallation Cloudflare a été exclu en entier du dernier passage, ce qui comprend un cas qui avait réussi lors du premier passage.
- Ruff, syntaxe Bash de `run_server.sh`, syntaxe de tous les fichiers JavaScript et modules, et empreintes des trois fichiers de dépendances verrouillées contrôlés avec succès. Versions des dépendances inchangées.

## Contrôles de l'interface

- Chromium 134 avec serveur et API réels, comptes de validation et aucun accès au compte du club. Aucun message JavaScript non géré.
- Décodage effectif par ZXing des QR codes rendus : deux pages, huit largeurs de 320 à 1440 pixels, densités 1, 1,25, 2 et 3, soit 64 combinaisons. Douze contrôles supplémentaires émulent le zoom du navigateur de 67 % à 200 % en adaptant la largeur CSS et la densité. Chemin et adresse décodés contrôlés.
- QR agrandi également décodé, fermeture possible sans perdre les champs du formulaire ; superposition correcte au formulaire d'administration. Captures inspectées.
- Couples : exactement trois options, tailles de police des titres identiques, clic sur les repères des trois vues, documents retirés inaccessibles. Agrandissement commun des deux volets par glissement de souris, réduction au clavier, persistance après rechargement, hauteurs égales et absence de débordement horizontal de page de 320 à 1440 pixels.
- Lien direct Leboncoin visible sur l'accueil avec un état simulé de restriction. Les captures et comptes de validation ne sont pas distribués.

## Essais réels Leboncoin et limite restante

Les essais ont été effectués avec le SDK et les dépendances verrouillés. Un premier appel de recherche a reçu HTTP 200. Une collecte suivante a reçu une page de 100 résultats bruts, puis HTTP 403 à la page suivante ; aucun véhicule admissible n'avait encore été retenu. Les essais de la recherche stricte avec les deux profils de recours ont ensuite reçu HTTP 403 / DataDome. Les accès ont été arrêtés après ces refus, sans rafale de tentatives, service de résolution de CAPTCHA ni changement d'adresse réseau.

Ces observations confirment que l'accessibilité de la recherche dans un navigateur ne garantit pas celle du collecteur. La réutilisation des sessions et la reprise bornée sont couvertes par les tests de transport ; **une collecte Leboncoin complète n'a pas pu être validée en ligne**. Cette livraison ne garantit donc ni la disparition des refus DataDome ni la disponibilité permanente de cette source. Les annonces déjà disponibles restent conservées et la recherche directe fournit un recours pour les membres.

## Archive

- Construction à partir du manifeste de la base : **482 fichiers**, soit les 491 fichiers d'origine moins les neuf retraits attendus. Aucun fichier de validation temporaire ni nouvelle dépendance embarquée.
- CRC, chemins, permissions exécutables du script, horodatages non futurs, cohérence des versions actives et absence de données d'exécution ou de secrets contrôlés avant livraison.
