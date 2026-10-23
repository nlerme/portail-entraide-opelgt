# Contribution

Ce dépôt contient le portail Linux serveur de l’Entraide Opel GT.

## Préparer l’environnement

```bash
python -m venv .venv-dev
. .venv-dev/bin/activate
python -m pip install -r requirements-dev.lock
```

Les dépendances système utilisées par l’OCR et la validation sont détaillées dans le README.

## Vérifications obligatoires

Avant une proposition de modification :

```bash
python -W error -m pytest -q
ruff check .
bash -n run_server.sh
shellcheck run_server.sh
find static -type f -name '*.js' -print0 | xargs -0 -n1 node --check
sha256sum -c requirements.lock.sha256
```

Ne jamais commiter `config.json`, `secrets.json`, les bases SQLite, les journaux, les catalogues téléchargés ou les bulletins privés. Les PDF et le tableur présents sous `resources/` sont des ressources publiques explicitement embarquées dans le projet.

## Portée des changements

Conserver la compatibilité Linux `x86_64` et `aarch64`, l’authentification commune, les routes protégées et les unités `systemd`. Toute modification de l’interface doit être vérifiée au minimum aux largeurs 390 px, 768 px et 1440 px.
