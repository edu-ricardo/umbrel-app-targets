# Destinos dos Apps (umbrel-app-targets)

Mostra o **endereço interno** de cada app instalado no Umbrel (`http://<container>:<porta>`), que é o que se usa como *Service* no Cloudflare Tunnel, no DockFlare ou em qualquer outro container que precise falar com o app.

Ele lê os arquivos que o umbrelOS mantém em `/home/umbrel/umbrel/app-data/<app>/` (`umbrel-app.yml` e `docker-compose.yml`) e não precisa de acesso ao Docker.

| Tipo | Como o destino é montado |
| --- | --- |
| `proxy` | App atrás do proxy do Umbrel: `http://APP_HOST:APP_PORT` do `app_proxy` (vai direto ao app, sem o login do Umbrel) |
| `host` | App em rede do host (Home Assistant, Scrypted…): `http://<IP do Umbrel>:<porta>` |
| `porta` | App sem proxy que publica a porta no host: `http://<container>:<porta interna>` |

## Como script, direto no Umbrel

Só usa a biblioteca padrão do Python 3.

```bash
curl -fsSLO https://raw.githubusercontent.com/edu-ricardo/umbrel-app-targets/main/app/targets.py
python3 targets.py /home/umbrel/umbrel/app-data
```

Outros formatos: `--format csv`, `--format markdown` ou `--format json`. Para os apps em rede do host, informe o IP com `--host 192.168.0.10`.

## Como página web

```bash
python3 targets.py /home/umbrel/umbrel/app-data --serve --port 8080
```

A página tem busca, ordenação, cópia com um clique, seleção de linhas e exportação em CSV/Markdown. Informando o seu domínio, ela sugere um subdomínio por app (editável) e inclui na exportação.

## Como app do Umbrel

A imagem é publicada pelo workflow [`docker.yml`](.github/workflows/docker.yml) em `ghcr.io/edu-ricardo/umbrel-app-targets`. Para publicar uma versão:

```bash
git tag v1.0.0
git push origin v1.0.0
```

Compose usado na loja (o `app-data` é montado somente leitura):

```yaml
services:
  app_proxy:
    environment:
      APP_HOST: florencio-store-app-targets_web_1
      APP_PORT: 8080

  web:
    image: ghcr.io/edu-ricardo/umbrel-app-targets:1.0.0
    restart: on-failure
    volumes:
      - ${UMBREL_ROOT}/app-data:/umbrel-app-data:ro
```

Mantenha o login do Umbrel ligado nesse app: os arquivos lidos descrevem todos os seus apps.
