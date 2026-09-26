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
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from . import config, evaluate, llm, memory, projects
from .consult import consult

log = logging.getLogger("api")
_loop = asyncio.new_event_loop()
threading.Thread(target=_loop.run_forever, name="api-loop", daemon=True).start()


def run(coro, timeout=1800):
    """Ejecuta una corrutina en el event loop compartido (los clientes httpx viven en un solo loop)."""
    return asyncio.run_coroutine_threadsafe(coro, _loop).result(timeout)


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

    def _html(self, html: str):
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
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
            return self._send(200, {"model": config.LLM_MODEL, "model_ok": run(llm.healthy(), 30),
                                    "stats": memory.stats(), "projects": [str(p) for p in config.PROJECT_DIRS]})
        if u.path == "/metrics":
            return self._send(200, evaluate.evaluate() | {"history": {k: memory.metric_history(k, 48) for k in
                              ("exam_avg", "kata_pass_rate", "kata_avg_seconds", "improvement_rate", "error_rate")}})
        if u.path in ("/", "/dashboard"):
            return self._html(dashboard_html())
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
            return self._send(200, run(consult(q, "api")))
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


def dashboard_html() -> str:
    """Panel sin dependencias: métricas, alertas, planes y últimos eventos; se refresca solo cada 60 s."""
    q = evaluate.evaluate()
    st = memory.stats()
    cur, prev = q["window_24h"], q["previous_7d"]

    def f(v):
        return "-" if v is None else (f"{v:.2f}" if isinstance(v, float) else str(v))
    rows_ = "".join(f"<tr><td>{k}</td><td>{f(cur.get(k))}</td><td>{f(prev.get(k))}</td></tr>" for k in cur)
    alerts = "".join(f"<li>{a}</li>" for a in q["alerts"]) or "<li class='ok'>sin alertas</li>"
    plans = memory.rows("SELECT domain, SUM(status='done') done, SUM(status='pending') pending, COUNT(*) total FROM plans GROUP BY domain ORDER BY domain")
    plan_rows = "".join(f"<tr><td>{p['domain'][:40]}</td><td>{p['done']}</td><td>{p['pending']}</td><td>{p['total']}</td></tr>" for p in plans)
    events = memory.rows("SELECT agent, kind, substr(detail,1,120) d, created FROM events ORDER BY id DESC LIMIT 25")
    ev_rows = "".join(f"<tr><td>{time.strftime('%H:%M:%S', time.localtime(e['created']))}</td><td>{e['agent']}</td><td>{e['kind']}</td><td>{e['d']}</td></tr>" for e in events)
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><meta http-equiv="refresh" content="60">
<title>stevecan</title><style>body{{font-family:system-ui,sans-serif;margin:24px;background:#111;color:#eee}}
table{{border-collapse:collapse;margin:8px 0 20px}}td,th{{border:1px solid #333;padding:4px 10px;text-align:left}}
th{{background:#222}}.alert li{{color:#ff6b6b}}.ok{{color:#7bd88f}}h2{{margin-top:28px}}code{{color:#9cf}}</style></head><body>
<h1>stevecan</h1><p>modelo <code>{config.LLM_MODEL}</code> · conocimiento {st['knowledge']} (verificado {st['verified']}) ·
temas {st['topics']} · katas {st['katas']} · skills {st['skills_lib']} · código {st['code']}</p>
<h2>Alertas</h2><ul class="alert">{alerts}</ul>
<h2>Métricas (24 h frente a 7 días anteriores)</h2><table><tr><th>métrica</th><th>24 h</th><th>7 d</th></tr>{rows_}</table>
<h2>Planes de estudio</h2><table><tr><th>dominio</th><th>hechos</th><th>pendientes</th><th>total</th></tr>{plan_rows}</table>
<h2>Últimos eventos</h2><table><tr><th>hora</th><th>agente</th><th>tipo</th><th>detalle</th></tr>{ev_rows}</table>
<p><a href="/metrics" style="color:#9cf">/metrics (JSON)</a> · <a href="/status" style="color:#9cf">/status</a></p></body></html>"""


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
