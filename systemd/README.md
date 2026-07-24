# Unités systemd

Les unités sont installées par `run_server.sh`. Le fichier `portail-entraide-opel-gt.tmpfiles` crée `/run/portail-entraide-opel-gt` avec le groupe et les permissions nécessaires au socket de contrôle.

Le serveur et les workers sont exécutés sous l’utilisateur non privilégié `opelgt`. Le helper `control@.service` est le seul composant privilégié lié à l’administration ; il n’accepte qu’une liste fermée d’actions JSON. L’action `apply-config` valide le fichier, régénère la planification des mises à jour système et redémarre les trois services applicatifs.

## Catalogues fournisseurs

Après une installation vierge, l’installateur peut créer une unique tâche initiale lorsque le portail ne possède aucun catalogue exploitable. Les récupérations périodiques sont ensuite déclenchées uniquement par `portail-entraide-opel-gt-catalog-update.timer` :

```ini
OnCalendar=Sun *-*-* 00:00:00 Europe/Paris
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
