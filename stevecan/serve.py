"""API HTTP del sistema unificado (para tu servidor privado, sin dependencias externas).
  python -m stevecan.serve            # escucha en API_HOST:API_PORT (por defecto 0.0.0.0:8765)
Endpoints (cabecera Authorization: Bearer $API_TOKEN si API_TOKEN está definido):
  GET  /status                      estado del sistema
  POST /ask      {"question": "..."}                         respuesta con memoria + internet
  POST /improve  {"project": "/ruta", "instruction": "..."}  encola mejora para el agente developer
  POST /research {"topic": "..."}                            encola investigación
  GET  /backups?project=/ruta       backups disponibles
  GET  /improvements                informes de mejoras
"""
import asyncio
import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from . import config, llm, memory, projects
from .consult import consult

log = logging.getLogger("api")


class Handler(BaseHTTPRequestHandler):
    def _auth(self) -> bool:
        if not config.API_TOKEN:
            return True
        return self.headers.get("Authorization", "") == f"Bearer {config.API_TOKEN}"

    def _send(self, code: int, payload):
        body = json.dumps(payload, ensure_ascii=False, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return {}

    def log_message(self, fmt, *args):  # noqa: D102
        log.info("%s %s", self.address_string(), fmt % args)

    def do_GET(self):  # noqa: N802
        if not self._auth():
            return self._send(401, {"error": "no autorizado"})
        u = urlparse(self.path)
        if u.path == "/status":
            return self._send(200, {"model": config.LLM_MODEL, "model_ok": asyncio.run(llm.healthy()),
                                    "stats": memory.stats(), "projects": [str(p) for p in config.PROJECT_DIRS]})
        if u.path == "/backups":
            q = parse_qs(u.query).get("project", [None])[0]
            return self._send(200, projects.list_backups(Path(q) if q else None))
        if u.path == "/improvements":
            files = sorted(config.IMPROVEMENTS_DIR.glob("*.md"))[-50:]
            return self._send(200, [{"name": f.name, "content": f.read_text(encoding="utf-8")[:3000]} for f in files])
        return self._send(404, {"error": "ruta desconocida"})

    def do_POST(self):  # noqa: N802
        if not self._auth():
            return self._send(401, {"error": "no autorizado"})
        u, body = urlparse(self.path), self._body()
        if u.path == "/ask":
            q = (body.get("question") or "").strip()
            if not q:
                return self._send(400, {"error": "falta question"})
            return self._send(200, asyncio.run(consult(q, "api")))
        if u.path == "/improve":
            project, instr = body.get("project"), (body.get("instruction") or "").strip()
            if not project or not instr:
                return self._send(400, {"error": "faltan project e instruction"})
            tid = memory.add_task("improve", {"project": str(Path(project).expanduser().resolve()), "instruction": instr}, "api", priority=1)
            return self._send(202, {"task": tid})
        if u.path == "/research":
            topic = (body.get("topic") or "").strip()
            if not topic:
                return self._send(400, {"error": "falta topic"})
            return self._send(202, {"task": memory.add_task("research", {"topic": topic, "area": ""}, "api", priority=2)})
        return self._send(404, {"error": "ruta desconocida"})


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    srv = ThreadingHTTPServer((config.API_HOST, config.API_PORT), Handler)
    log.info("API en http://%s:%d (%s)", config.API_HOST, config.API_PORT, "con token" if config.API_TOKEN else "SIN token: usa solo en red privada")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
