# Confidentialité et conservation

Le portail utilise les identifiants membre uniquement pour valider l’accès et télécharger les bulletins autorisés. Le login, le mot de passe et les cookies du site membre ne sont pas persistés.

Les données locales comprennent les PDF téléchargés, l’index OCR, les catalogues, l’historique des prix, les tâches techniques, les logs applicatifs et l’historique des tentatives de connexion. Cet historique contient le type d’accès, l’adresse IP, le pays estimé, le résultat et la date, sans enregistrer le login ni le mot de passe. Les adresses publiques peuvent être transmises à un service de géolocalisation IP afin d’obtenir le pays. Les données restent sur le serveur administré par le club, à l’exception de cette requête de géolocalisation et des messages ntfy lorsque les notifications sont activées.

Les logs ne doivent pas contenir de mot de passe, de cookie ou de contenu intégral de bulletin. Les fichiers temporaires de plus de sept jours et les tâches terminales de plus de quatre-vingt-dix jours sont purgés par la maintenance quotidienne.

L’administrateur est responsable de la durée de conservation des PDF, sauvegardes, logs et statistiques au regard des règles du club et du droit applicable.

Les annonces collectées restent sur le serveur ; leurs photographies sont chargées depuis les sites sources. Lorsque ntfy est activé, les descriptions techniques des incidents et rétablissements sont transmises au serveur ntfy configuré. Les identifiants ntfy restent dans le fichier local de secrets. Une purge supprime leur configuration et la file locale ; elle n’efface ni les messages déjà transmis à ntfy, ni les sauvegardes exportées ailleurs.
