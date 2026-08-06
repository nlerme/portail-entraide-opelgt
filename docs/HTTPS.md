# Exposition HTTPS du portail

Le portail écoute par défaut sur `0.0.0.0:8080` et autorise l’authentification en HTTP depuis les adresses privées du réseau local. Pour une exposition sur Internet, configurez explicitement `127.0.0.1:8080` comme ci-dessous ; le reverse proxy installé sur la même machine devient alors le seul composant exposé au réseau.

Dans `/etc/portail-entraide-opel-gt/config.json`, configurez :

```json
{
  "server": {
    "host": "127.0.0.1",
    "port": 8080,
    "public_url": "https://portail.exemple.fr",
    "trusted_proxies": ["127.0.0.1/32", "::1/128"]
  },
  "authentication": {
    "https_only_cookies": true,
    "allow_insecure_lan_http": false,
    "allow_insecure_remote_http": false
  }
}
```

Appliquez ensuite la configuration :

```bash
sudo /opt/portail-entraide-opel-gt/run_server.sh apply-config
```

## Caddy

```caddyfile
portail.exemple.fr {
    reverse_proxy 127.0.0.1:8080
    encode zstd gzip
}
```

Caddy gère automatiquement le certificat TLS lorsque le nom de domaine pointe vers le serveur et que les ports nécessaires sont accessibles.

## Nginx

```nginx
server {
    listen 443 ssl http2;
    server_name portail.exemple.fr;

    ssl_certificate     /etc/letsencrypt/live/portail.exemple.fr/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/portail.exemple.fr/privkey.pem;

    client_max_body_size 2m;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_read_timeout 120s;
    }
}

server {
    listen 80;
    server_name portail.exemple.fr;
    return 301 https://$host$request_uri;
}
```

Ne déclarez dans `trusted_proxies` que les adresses réellement utilisées par le reverse proxy. N’exposez pas directement le port 8080 sur le pare-feu.
