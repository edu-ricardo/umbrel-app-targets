#!/usr/bin/env python3
"""Lista o destino interno (container:porta) de cada app instalado no Umbrel.

Lê os arquivos que o umbrelOS mantém em app-data/<app>/ (umbrel-app.yml e
docker-compose.yml) e monta, para cada app, o endereço que um túnel (Cloudflare
Tunnel, DockFlare) ou outro container usa para alcançá-lo.

Uso:
  python3 targets.py [PASTA]                 # tabela no terminal
  python3 targets.py [PASTA] --format csv    # também: markdown, json
  python3 targets.py [PASTA] --serve         # página web na porta 8080

PASTA é a app-data do Umbrel (/home/umbrel/umbrel/app-data). Sem ela, usa a
variável UMBREL_APP_DATA ou a pasta atual. Só usa a biblioteca padrão do Python.
"""

import argparse
import csv
import io
import json
import os
import re
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parent / "static"
GALLERY_ICON = "https://getumbrel.github.io/umbrel-apps-gallery/{id}/icon.svg"


def _scalar(text, key, indent=""):
    """Valor de `key: valor` (aspas opcionais) com a indentação dada."""
    m = re.search(rf'^{indent}{re.escape(key)}:[ \t]*(?:"([^"\n]*)"|\'([^\'\n]*)\'|([^\n]*?))[ \t]*(?:[ \t]#.*)?$',
                  text, re.M)
    return next(g for g in m.groups() if g is not None).strip() if m else ""


def _env(text, key):
    """Variável de ambiente no formato de mapa (`KEY: v`) ou de lista (`- KEY=v`)."""
    m = re.search(rf'^\s*-?\s*["\']?{re.escape(key)}["\']?\s*[:=]\s*["\']?([^"\'\s#]+)', text, re.M)
    return m.group(1) if m else ""


def _services(compose):
    """Blocos `nome: ...` dentro de `services:` (texto de cada serviço)."""
    m = re.search(r"^services:\s*\n(.*?)(?=^\S|\Z)", compose, re.M | re.S)
    if not m:
        return {}
    body = m.group(1)
    starts = list(re.finditer(r"^( +)([A-Za-z0-9._-]+):\s*$", body, re.M))
    if not starts:
        return {}
    indent = min(len(s.group(1)) for s in starts)
    starts = [s for s in starts if len(s.group(1)) == indent]
    blocks = {}
    for i, s in enumerate(starts):
        end = starts[i + 1].start() if i + 1 < len(starts) else len(body)
        blocks[s.group(2)] = body[s.end():end]
    return blocks


def _published_target(containers, manifest_port):
    """Sem app_proxy: o container que publica a porta do app no host (ex.: 5984:5984)."""
    for c in containers:
        for mapping in c["published_ports"]:
            parts = mapping.split("/")[0].split(":")
            if len(parts) >= 2 and parts[-2] == manifest_port:
                return f"http://{c['container']}:{parts[-1]}"
    return ""


def read_app(folder):
    manifest_path = folder / "umbrel-app.yml"
    compose_path = folder / "docker-compose.yml"
    if not manifest_path.is_file():
        return None
    try:
        manifest = manifest_path.read_text(encoding="utf-8", errors="replace")
        compose = compose_path.read_text(encoding="utf-8", errors="replace") if compose_path.is_file() else ""
    except OSError as e:
        return {"id": folder.name, "name": folder.name, "error": str(e), "icon": "", "port": "", "path": "",
                "kind": "outro", "target": "", "umbrel_login": None, "containers": []}

    app_id = _scalar(manifest, "id") or folder.name
    services = _services(compose)
    proxy = services.get("app_proxy", "")
    app_host = _env(proxy, "APP_HOST")
    app_port = _env(proxy, "APP_PORT")
    host_mode = bool(re.search(r"^\s*network_mode:\s*[\"']?host", compose, re.M))

    containers = []
    for name, block in services.items():
        if name == "app_proxy":
            continue
        container = _scalar(block, "container_name", r"\s+") or f"{app_id}_{name}_1"
        ports_block = re.search(r"^[ \t]*ports:[ \t]*\n((?:[ \t]*-[^\n]*(?:\n|$))+)", block, re.M)
        ports = re.findall(r'^\s*-\s*["\']?([\d-]+(?::[\d-]+)?(?::[\d-]+)?(?:/\w+)?)["\']?\s*$',
                           ports_block.group(1) if ports_block else "", re.M)
        containers.append({"service": name, "container": container,
                           "host_network": "network_mode" in block and "host" in _scalar(block, "network_mode", r"\s+"),
                           "published_ports": ports})

    proxy_auth = _env(proxy, "PROXY_AUTH_ADD").lower() != "false" if proxy else None
    manifest_port = _scalar(manifest, "port")
    published = _published_target(containers, manifest_port)
    if app_host and app_port:
        kind = "proxy"
        target = f"http://{app_host}:{app_port}"
    elif host_mode:
        kind = "host"
        target = ""  # depende do IP do Umbrel; a página monta com o IP informado
    elif published:
        kind = "porta"
        target = published
    else:
        kind = "outro"
        target = ""

    return {
        "id": app_id,
        "name": _scalar(manifest, "name") or app_id,
        "version": _scalar(manifest, "version"),
        "icon": _scalar(manifest, "icon") or GALLERY_ICON.format(id=app_id),
        "port": manifest_port,
        "path": _scalar(manifest, "path"),
        "kind": kind,
        "app_host": app_host,
        "app_port": app_port,
        "target": target,
        "umbrel_login": proxy_auth,
        "containers": containers,
    }


def scan(app_data):
    root = Path(app_data)
    apps = [a for a in (read_app(p) for p in sorted(root.iterdir()) if p.is_dir()) if a]
    return sorted(apps, key=lambda a: a["name"].lower())


def resolved_target(app, host="umbrel.local"):
    if app.get("target"):
        return app["target"]
    if app.get("kind") == "host" and app.get("port"):
        return f"http://{host}:{app['port']}"
    return ""


COLUMNS = [
    ("App", lambda a, h: a["name"]),
    ("ID", lambda a, h: a["id"]),
    ("Destino", resolved_target),
    ("Porta no Umbrel", lambda a, h: a.get("port", "")),
    ("Login do Umbrel", lambda a, h: {True: "sim", False: "não", None: "-"}[a.get("umbrel_login")]),
    ("Tipo", lambda a, h: a.get("kind", "")),
]


def render(apps, fmt, host):
    rows = [[col(a, host) for _, col in COLUMNS] for a in apps]
    header = [name for name, _ in COLUMNS]
    if fmt == "json":
        return json.dumps(apps, indent=2, ensure_ascii=False)
    if fmt == "csv":
        out = io.StringIO()
        csv.writer(out).writerows([header] + rows)
        return out.getvalue()
    if fmt == "markdown":
        lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
        lines += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
        return "\n".join(lines)
    widths = [max(len(str(x)) for x in col) for col in zip(header, *rows)]
    fmt_row = lambda r: "  ".join(str(c).ljust(w) for c, w in zip(r, widths))
    return "\n".join([fmt_row(header), fmt_row(["-" * w for w in widths])] + [fmt_row(r) for r in rows])


def serve(app_data, port):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code, body, content_type):
            data = body.encode("utf-8") if isinstance(body, str) else body
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/api/apps":
                try:
                    self._send(200, json.dumps(scan(app_data), ensure_ascii=False), "application/json; charset=utf-8")
                except Exception as e:
                    traceback.print_exc()
                    self._send(500, json.dumps({"error": str(e)}), "application/json; charset=utf-8")
            elif path == "/health":
                self._send(200, "ok", "text/plain")
            elif path in ("/", "/index.html"):
                self._send(200, (STATIC_DIR / "index.html").read_bytes(), "text/html; charset=utf-8")
            else:
                self._send(404, "not found", "text/plain")

        def log_message(self, *args):
            pass

    print(f"Lendo {app_data} — abra http://localhost:{port}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


def main():
    parser = argparse.ArgumentParser(description="Destinos internos dos apps instalados no Umbrel.")
    parser.add_argument("app_data", nargs="?", default=os.environ.get("UMBREL_APP_DATA", "."),
                        help="pasta app-data do Umbrel (padrão: $UMBREL_APP_DATA ou a pasta atual)")
    parser.add_argument("--format", choices=["table", "csv", "markdown", "json"], default="table")
    parser.add_argument("--host", default=os.environ.get("UMBREL_HOST", "umbrel.local"),
                        help="IP ou nome do Umbrel, usado nos apps em rede do host")
    parser.add_argument("--serve", action="store_true", help="abre a página web em vez de imprimir")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if not Path(args.app_data).is_dir():
        sys.exit(f"Pasta não encontrada: {args.app_data}")
    if args.serve:
        serve(args.app_data, args.port)
    else:
        print(render(scan(args.app_data), args.format, args.host))


if __name__ == "__main__":
    main()
