# Unités systemd

Les unités sont installées par `run_server.sh`. Le fichier `portail-entraide-opel-gt.tmpfiles` crée `/run/portail-entraide-opel-gt` avec le groupe et les permissions nécessaires au socket de contrôle.

Le serveur et les workers sont exécutés sous l’utilisateur non privilégié `opelgt`. Le helper `control@.service` est le seul composant privilégié lié à l’administration ; il n’accepte qu’une liste fermée d’actions JSON. L’action `apply-config` valide le fichier, régénère la planification des mises à jour système et redémarre les trois services applicatifs.

## Catalogues fournisseurs

Après une installation vierge, l’installateur peut créer une unique tâche initiale lorsque le portail ne possède aucun catalogue exploitable. Les récupérations périodiques sont ensuite déclenchées uniquement par `portail-entraide-opel-gt-catalog-update.timer` :

```ini
OnCalendar=Mon,Wed,Fri *-*-* 02:00:00 Europe/Paris
Persistent=false
AccuracySec=1s
```

Le timer ne rattrape pas une échéance manquée après un arrêt et aucune page web ne crée de tâche catalogue.

## Paquets système

`portail-entraide-opel-gt-system-update.service` exécute, en tant que `root`, la commande interne :

```text
/opt/portail-entraide-opel-gt/run_server.sh system-update-execute
```

Elle lance `apt-get update`, puis `apt-get upgrade --with-new-pkgs`, et redémarre la machine lorsque la mise à jour est terminée. Le service possède un verrou exclusif et un délai maximal de six heures.

Le timer est généré au moment de l’installation et à chaque action **Appliquer et redémarrer**, à partir de :

```json
{
  "maintenance": {
    "weekly_package_update_enabled": true,
    "weekly_package_update_day": "Wednesday",
    "weekly_package_update_time": "00:00",
    "timezone": "Europe/Paris"
  }
}
```

La valeur par défaut correspond à :

```ini
OnCalendar=Wed *-*-* 00:00:00 Europe/Paris
Persistent=false
AccuracySec=1s
```

Lorsque `weekly_package_update_enabled` vaut `false`, le timer est désactivé. Le jour doit être écrit en anglais de `Monday` à `Sunday`, et l’heure au format `HH:MM`.

## Cloudflare Tunnel

Lorsque l’option est acceptée pendant l’installation, `cloudflared` est installé séparément comme service système global. Ce service est activé au démarrage par son propre installateur et ne dépend pas des unités du portail.

Le correctif du 23 octobre 2026 installe `/etc/systemd/system/cloudflared.service.d/portail-entraide-opel-gt.conf` : connexion HTTP/2, redémarrage automatique et point de contrôle local `http://127.0.0.1:20241/ready`. Ce fichier ne contient aucun jeton. Le service officiel conserve les paramètres du tunnel.

`portail-entraide-opel-gt-cloudflare-health.timer` démarre deux minutes après le boot, puis déclenche un contrôle chaque minute. Le contrôle contacte le portail local et vérifie les connexions actives du tunnel, même sans visiteur. Trois échecs consécutifs déclenchent un redémarrage ciblé ; un succès remet le compteur à zéro. Un arrêt volontaire du portail ou du connecteur est respecté. Le timer est activé uniquement pour le tunnel configuré par le portail.

La désinstallation arrête et désactive d’abord le timer de surveillance et son service, puis le connecteur géré par le portail, avant de retirer les unités du portail et son seul fichier de surcharge. `uninstall --purge` arrête et désactive systématiquement `cloudflared.service`, y compris sur une ancienne installation sans surcharge. Cela empêche aussi son retour au prochain démarrage. Une erreur laissant un de ces services actif ou activé interrompt la désinstallation avant la suppression des fichiers. Un service déjà absent ou arrêté permet de relancer la purge. Le paquet et la définition globale du service Cloudflare sont conservés.

Diagnostic :

```bash
systemctl status cloudflared portail-entraide-opel-gt-cloudflare-health.timer
journalctl -u cloudflared -u portail-entraide-opel-gt-cloudflare-health.service --since '30 minutes ago'
curl --noproxy '*' -fsS http://127.0.0.1:20241/ready
```

Références : [paramètres officiels Cloudflare](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/run-parameters/) et [contrôle de disponibilité du connecteur](https://github.com/cloudflare/cloudflared/blob/master/metrics/readiness.go).

## Notifications ntfy

`portail-entraide-opel-gt-notifications.timer` est activé à l’installation : `OnBootSec=2min`, `OnUnitInactiveSec=60s`. Il lance `python -m app.notifications` dans l’environnement web, sous `opelgt`, indépendamment des services web et workers. Le délai maximal est de 150 secondes. Il peut ainsi constater leur panne sans dépendre d’une visite du portail. Il ne redémarre aucun service ; la récupération Cloudflare existante est conservée.

Le moniteur lit les réglages ntfy dans le fichier de secrets et les derniers résultats des collectes, conserve une file persistante en cas d’échec d’envoi, et signale les incidents et rétablissements sans répétition à chaque contrôle. Les identifiants ne figurent pas dans l’unité ou la ligne de commande. Installation et désinstallation arrêtent les exécutions en cours ; la purge retire configuration, unités et état local. Voir README pour les limites d’une notification durant une coupure Internet ou une panne complète du serveur.

L’intervalle du timer reste d’une minute. Depuis 1.1.21, l’envoi est limité séparément par `ntfy.interval_days` (1 à 365 jours, au moins 24 h). La file d’événements et la date du dernier envoi réussi sont persistantes. L’administration peut modifier les réglages via l’action `save-ntfy` du helper root ; celui-ci valide uniquement les champs ntfy, conserve les autres secrets et n’accorde pas de droit d’écriture du fichier au service web. Les changements sont lus au prochain passage du moniteur.
