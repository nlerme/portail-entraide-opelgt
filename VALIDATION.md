# Validation du bundle 1.1.37

Date : 2 novembre 2026. Base : `portail-entraide-opelgt-1.1.36.zip`, SHA-256 `4ee5a7e6c56d0bad75757c205bca49a0a46ddc78a151a7d998215d3eb2861c6c`.

## Périmètre

- Bandeau commun aux deux connexions : logo Opel de 1964 sur fond blanc, logo du club, QR code de la page correspondante. Les trois éléments conservent la même hauteur et une seule ligne sur la largeur disponible.
- QR codes calculés dans le navigateur par une bibliothèque locale sous licence MIT. L’adresse reprend le protocole et l’hôte du portail consulté et le chemin `/` ou `/admin`, sans paramètres ni fragment. Aucun appel à un générateur externe et aucune transmission de compte ou de session.
- Quatre nouvelles planches : moteur (figures 6A-1 et 6A-4), suspension arrière (3F-5), pont (4B-37), extraites du manuel constructeur *1973 Opel Service Manual*. Onze marqueurs interactifs, dont deux pour les fixations du bras inférieur. Traits des dessins d’origine conservés ; numéros, traits de rappel et légendes français ajoutés. Provenance, pages et empreintes conservées.
- Les 61 lignes et valeurs de serrage, leurs correspondances dans les vues 1 à 3 et les documents antérieurs restent identiques. Les nouvelles correspondances ne complètent que les pièces identifiées sur les planches. Aucun collecteur, traitement OCR, horaire ou mécanisme d’authentification modifié.
- Version 1.1.37 propagée dans les fichiers actifs et la documentation.

## Vérifications réalisées

- **529 tests réussis**, avertissements traités comme erreurs ; vingt contrôles ciblés supplémentaires réussis. Les quatre contrôles système déjà limités lors de la version précédente restent hors du passage applicatif : deux sockets Unix refusés dans cet environnement, réseau IPv4 hors boucle locale et restitution du propriétaire. Leur essai séparé confirme ces limites ; ils restent présents dans la CI GitHub.
- Chromium 134, serveur et API réels avec comptes de validation et aucun accès au compte du club : bandeaux à 320, 390, 844 et 1440 pixels, thème sombre et texte agrandi. Images chargées, hauteur commune à moins d’un pixel, alignement horizontal et absence de débordement de page. Captures inspectées.
- Décodage effectif des QR codes depuis les images rendues : deux pages et quatre largeurs à densité 2, contrôlées avec OpenCV. Deux adresses HTTPS contrôlées à densité 1 avec ZXing ; contrôle indépendant de l’URL exacte, du chemin et de l’absence des paramètres et du fragment.
- Sept options de vues disponibles ; marqueurs et images chargés. Clic sur chacune des nouvelles planches puis navigation inverse depuis la liste vérifiés. PDF et JPEG servis avec le bon type après connexion, et refusés avant connexion. Les quatre nouvelles vues restent accessibles à 320, 390 et 844 pixels sans débordement horizontal de page. Aucune erreur JavaScript non gérée.
- Les quatre PDF ont été rendus et inspectés : dessins lisibles, traits de rappel, repères et légendes dans la page. Le manuel complet et les fichiers de validation ne sont pas distribués.
- Ruff, syntaxe Bash, ShellCheck, syntaxe des JavaScript et modules et empreintes des dépendances contrôlés. Aucun changement des versions de dépendances Python.
- Archive construite à partir des 476 fichiers de la base et des quinze ajouts attendus ; aucun fichier antérieur supprimé. Contrôle du CRC, des permissions, des horodatages, des versions actives et de l’absence de données d’exécution ou de secrets avant livraison.
