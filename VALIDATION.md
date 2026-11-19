# Validation du bundle 1.1.40

Date : 19 novembre 2026. Base : `portail-entraide-opelgt-1.1.39.zip`, SHA-256 `3b35853bd5f47fbc9e5ee60edad0a49711eea9a4192841f49cd16a88f4931697`.

## Périmètre

Ajout de sept sources aux petites annonces : Car & Classic, Rétrocalage, ParuVendu, AutoScout24, CarJager, Pléthore Cars et Dyler. Collecteurs publics, sélection des sources, couleurs de la liste et de la carte, autorisation des liens directs et hôtes des photos, sélection par défaut et documentation adaptées. Les personnalisations existantes de la sélection sont conservées ; l’ancienne sélection standard de quatre sources devient celle des onze sources.

Les nouvelles collectes gardent les filtres France et Opel GT 1100, 1900 et GT/J d’époque. Elles contrôlent les compteurs et la pagination, signalent les formats inconnus et conservent les données précédentes en cas d’échec. Le client public prend en charge les recherches structurées anonymes utilisées par Dyler et Pléthore Cars, avec les mêmes bornes, contrôles d’hôte et arrêts sur refus que les lectures HTML. La portée des règles robots.txt terminées par `?` est préservée : la bibliothèque standard supprimait ce séparateur et bloquait à tort la recherche constructeur/modèle d’AutoScout24.

Les collecteurs des quatre sources existantes, les horaires, l’authentification et les autres services sont conservés. Les dépendances et leurs verrous restent identiques à la base. La version 1.1.40 est propagée aux références actives.

## Tests automatisés

- **558 tests applicatifs réussis**, avertissements traités comme erreurs ; dont 31 nouveaux cas pour les sept sources.
- Formats publics propres aux sites, GT modernes et pays étrangers exclus, véhicules vendus/annonces de recherche/pièces exclus selon les indicateurs fournis, prix en centimes de Car & Classic convertis, devises d’origine conservées, dates manquantes non inventées, départements et codes postaux contrôlés.
- Pagination complète, pages répétées et compteurs incohérents ; même contexte public de recherche conservé entre les pages Dyler ; refus HTTP 401/403/429 sans répétition ; règles robots.txt autorisées et interdites distinguées.
- Liens directs et hôtes de photos contrôlés ; coordonnées de contact et jetons de renouvellement Rétrocalage absents des données normalisées ; sélection personnalisée ou vide conservée à la mise à niveau.
- 14 tests système désélectionnés comme pour la base : désinstallation Cloudflare, purge privilégiée, deux échanges par socket Unix et accès IPv4 hors boucle locale. Ils ne sont pas présentés comme validés ici et restent inclus dans l’archive.
- Ruff, syntaxe Bash, syntaxe des 19 JavaScript/modules et empreintes des trois verrous de dépendances vérifiés. ShellCheck indisponible dans cet environnement ; le contrôle reste défini dans la CI du dépôt.

## Interface

Chromium 134, serveur et API réels, compte de validation synthétique. Douze combinaisons : largeurs 320, 390, 650, 760, 1024 et 1440 pixels, chacune avec texte normal et agrandi. Aucun débordement horizontal ; les onze sources s’empilent sur téléphone.

Onze couleurs distinctes, onze cases cochées après migration de la configuration standard, sept nouveaux filtres appliqués à la liste et aux repères, sept liens directs et sept fenêtres de carte vérifiés. La superposition de plusieurs annonces au centre d’une même commune garde ses boutons numérotés accessibles. Aucun message JavaScript non géré. Captures téléphone et ordinateur inspectées ; elles ne sont pas distribuées.

Les huit annonces réellement collectées ont aussi été chargées dans l’interface de validation. Les hôtes de photos autorisés côté navigateur et serveur ont été recoupés. Le navigateur de validation ne disposait pas d’un chargement externe des photos exploitable ; les vérifications HTTP séparées ont confirmé une photo AutoScout24 et une photo CarJager. Le CDN des photos Car & Classic a renvoyé une page Cloudflare HTTP 403 depuis ce réseau, malgré une collecte des annonces réussie. Le message de remplacement prévu par l’interface reste donc nécessaire si une image est refusée.

## Collectes réelles des nouvelles sources

Essais publics sans compte, le 19 novembre 2026, avec robots.txt, contrôles de complétude et bornes du bundle :

| Source | Résultat complet | Annonces françaises retenues |
|---|---|---:|
| Car & Classic | Réussite | 5 |
| Rétrocalage | Réussite, aucune offre correspondante | 0 |
| ParuVendu | Réussite ; GT modernes et GT située en Italie exclues | 0 |
| AutoScout24 | Réussite | 2 |
| CarJager | Réussite ; véhicule situé en Italie exclu | 1 |
| Pléthore Cars | Réussite, aucune offre Opel correspondante | 0 |
| Dyler | Réussite ; 280 Opel parcourues sur sept pages | 0 |

Les huit annonces disposent d’une URL de photo et d’un département. Cinq donnent une date de publication exploitable ; les trois autres restent non précisées. Sept communes ont été résolues ; une requête de géolocalisation a reçu HTTP 503. Ce dernier cas suit la politique existante de cache temporaire et de nouvelle tentative ultérieure.

Les résultats vides correspondent aux stocks observés, pas à une garantie de stock futur. Les formats et restrictions des sites peuvent évoluer ; les refus restent visibles et conservent le dernier cache valide. Aucune nouvelle collecte réelle des quatre sources antérieures n’a été lancée pendant cette modification ; leur disponibilité externe, notamment celle de Leboncoin, n’est pas certifiée par ces essais.

## Archive

Archive complète avec un répertoire racine `portail-entraide-opelgt/`, fichiers d’installation exécutables et horodatages antérieurs à la validation. Aucun compte, jeton, cookie, donnée d’exécution, environnement de test, page brute collectée ni capture de validation distribué. Les seuls nouveaux fichiers sont le module des sept collecteurs, la correspondance publique des départements et ses tests.
