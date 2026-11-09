# Validation du bundle 1.1.39

Date : 10 novembre 2026. Base : `portail-entraide-opelgt-1.1.38.zip`, SHA-256 `65af3bdb1df19389bdc906f9d17afc310503a99082c397dc86d39d48b1736ec0`.

## Changements limités à la demande

- Leboncoin : client `lbc` verrouillé en 1.1.9, adaptation à son interface de session et à ses erreurs de transport. `curl-cffi` reste en 0.15.0 ; aucune autre dépendance modifiée.
- Requête commune aux particuliers et professionnels combinant explicitement Opel GT 1900, Opel GT 1100 et Opel GT/J et leurs variantes d'écriture. Filtres côté source : voitures, Opel, GT, première immatriculation 1968–1976. Le filtrage local des modèles et de la France, le curseur, les contrôles de pagination et la conservation des observations restent en place.
- Dénominations recoupées avec le catalogue Bosch Classic et la base historique FIA, référencés dans le README. GT/J est la version Junior du modèle 1,9 litre.
- Profil initial Safari iOS 26.0 avec identité native iOS stable. Le SDK pouvait générer une identité Android pour ce profil iOS ; ce mélange a été observé pendant les essais. Le corriger ne prouve pas qu'il était l'unique cause des refus. Migration de la précédente combinaison livrée, conservation des combinaisons personnalisées, suppression des cookies après refus de la recherche.
- Liens de recherche de secours Leboncoin retirés de la sélection des services et du sélecteur de sources. Le portail garde ses annonces consultables et leurs liens vers la fiche d'origine. Erreurs conservées et nom de source non répété dans le message d'accueil.
- Sélection des services : suppression du carrousel horizontal sur téléphone, six blocs empilés jusqu'à 760 pixels ; deux colonnes de 761 à 1100 pixels, trois au-delà.
- Version 1.1.39 propagée aux références actives, documentation, notices et empreintes des dépendances alignées. Aucun changement aux bulletins, fournisseurs, couples, QR codes, horaires ou authentification en dehors de la version affichée.

## Vérifications automatisées

- **527 tests applicatifs validés au total**, avertissements traités comme erreurs. Le passage principal a validé 526 tests ; l'ancien contrôle exigeant le carrousel horizontal a été adapté à l'empilement demandé puis repassé avec succès séparément.
- 14 tests système désélectionnés, comme pour la base : ensemble du fichier de désinstallation Cloudflare, purge privilégiée, deux échanges par socket Unix et accès IPv4 hors boucle locale. Ils restent présents dans le bundle et ne sont pas présentés comme validés dans cet environnement sans privilèges root.
- Le véritable SDK 1.1.9 est exercé par les tests de transport avec HTTP simulé : requête structurée, total, curseurs, pages plafonnées, refus, reprise bornée, cookies privés et conservation des résultats. Les nouveaux cas vérifient les treize variantes des modèles, la migration des seuls paramètres livrés et l'abandon d'une ancienne identité Android avec ses cookies pour le profil iOS.
- Ruff, syntaxe Bash, syntaxe des JavaScript/modules et empreintes des trois fichiers de dépendances vérifiés. La seule dépendance mise à jour est `lbc` 1.1.7 vers 1.1.9.

## Vérifications de l'interface

Chromium 134 avec serveur et API réels, comptes de validation et données synthétiques ; aucun compte du club utilisé. Aucun message JavaScript non géré.

- 28 combinaisons : largeurs 320, 360, 375, 390, 420, 560, 760, 761, 800, 1024, 1100, 1101, 1280 et 1440 pixels, en texte normal et agrandi. Les six blocs sont entièrement accessibles, sans chevauchement ni débordement horizontal de la page ; empilement vertical et colonnes contrôlés.
- Accès interne de la sélection des services vers `/annonces`, absence de lien de recherche Leboncoin sur les deux pages, maintien des trois autres liens de sources et des liens des annonces en cache vérifiés.
- Message de refus encore affiché, sans duplication du nom Leboncoin. Captures téléphone et ordinateur inspectées ; elles ne sont pas distribuées.

## Essais Leboncoin réels et limite non résolue

Un premier essai avec le SDK 1.1.9 et une recherche ciblée a reçu **HTTP 200, sept résultats sur un total de sept, en une seule page**. Les résultats étaient des Opel GT 1900 ; aucun résultat GT 1100 ou GT/J n'était annoncé pour cette requête.

Les essais suivants passant par le collecteur du bundle ont reçu HTTP 403 / DataDome, d'abord avec le profil iOS puis avec le seul recours autorisé, puis lors du contrôle final de l'identité iOS cohérente. Les essais ont été arrêtés après ces refus. Aucun service payant, changement d'adresse réseau, compte Leboncoin ou résolution de CAPTCHA n'a été ajouté.

**La collecte ciblée a donc fonctionné lors d'un essai, mais la collecte complète du bundle n'a pas été validée de façon reproductible. Le refus DataDome reste non résolu de manière définitive.** Le ciblage et la compatibilité du client sont corrigés ; cette archive ne garantit pas la disponibilité de Leboncoin. Une erreur conserve les annonces précédentes et leur date réelle de dernière réussite ; elle ne devient pas une réussite vide et ne provoque aucun renvoi vers une recherche externe.

## Archive livrée

Même manifeste de **482 fichiers** que la base, sans ajout ni suppression de fichiers. CRC, chemins, permissions du script, horodatages non futurs et propagation de version contrôlés. Aucun fichier de session Leboncoin, identifiant, donnée d'exécution, environnement de test, capture ou fichier temporaire inclus.
