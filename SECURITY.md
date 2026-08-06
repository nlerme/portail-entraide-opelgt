# Politique de sécurité

## Versions prises en charge

La branche `1.0.x` est la seule branche prise en charge lors de la publication initiale.

## Signaler une vulnérabilité

N’ouvrez pas d’issue contenant une vulnérabilité, un identifiant, un cookie, une URL membre privée ou un extrait de bulletin. Utilisez le canal privé convenu avec les mainteneurs du dépôt GitHub privé.

Indiquez la version, le scénario reproductible, l’impact, les journaux expurgés et les mesures temporaires déjà appliquées.

## Secrets et données interdites dans Git

Ne versionnez jamais `config.json`, `secrets.json`, une base SQLite, un PDF, un catalogue d’exploitation, un cache, un log, une sauvegarde ou une archive de release. Vérifiez également l’historique Git avant tout partage.

## Déploiement

L’accès HTTP est prévu pour `localhost` et les adresses privées du réseau local. Toute exposition sur Internet doit passer par HTTPS. Ne mettez pas `allow_insecure_remote_http` à `true` hors diagnostic temporaire sur un réseau maîtrisé. Pour imposer HTTPS également sur le LAN, définissez `allow_insecure_lan_http` à `false`. Restreignez les collaborateurs du dépôt et les administrateurs du serveur au strict nécessaire.
