#!/usr/bin/env python3
"""Puente local y conservador entre ASTUR Safe EA y una IA del VPS.

No abre operaciones ni toca MetaTrader directamente. Recibe contexto del EA,
consulta un modelo local (Ollama o una API compatible con OpenAI), valida la
respuesta y devuelve una accion dentro de una lista cerrada.

ESTADO: ASTUR_SafeEA.mq4 (desde v0.40) ya llama a este puente via
WebRequest cuando UseLocalAI=true. Todas las rutas (incluida /health)
exigen el token compartido ASTUR_AI_SECRET si esta configurado: sin el
token correcto, cualquier peticion recibe 401. Configuralo SIEMPRE antes
de exponer este servicio, aunque solo escuche en localhost.
"""

from __future__ import annotations

import hmac
import json
import os
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


HOST = os.getenv("ASTUR_AI_HOST", "127.0.0.1")
PORT = int(os.getenv("ASTUR_AI_PORT", "8765"))
PROVIDER = os.getenv("ASTUR_AI_PROVIDER", "ollama").strip().lower()
MODEL = os.getenv("ASTUR_AI_MODEL", "qwen2.5:7b").strip()
MODEL_TIMEOUT = float(os.getenv("ASTUR_AI_MODEL_TIMEOUT", "25"))
DATABASE = Path(os.getenv("ASTUR_AI_DATABASE", "astur_ai_memory.sqlite3"))
MIN_MEMORY = int(os.getenv("ASTUR_AI_MIN_MEMORY", "30"))
SHARED_SECRET = os.getenv("ASTUR_AI_SECRET", "").strip()

if PROVIDER == "ollama":
    MODEL_URL = os.getenv("ASTUR_AI_URL", "http://127.0.0.1:11434/api/chat")
else:
    MODEL_URL = os.getenv(
        "ASTUR_AI_URL", "http://127.0.0.1:1234/v1/chat/completions"
    )

MAX_BODY_BYTES = 64 * 1024
DB_LOCK = threading.Lock()


def db_connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DATABASE, timeout=10)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at INTEGER NOT NULL,
            event TEXT NOT NULL,
            ticket INTEGER,
            side TEXT,
            score INTEGER,
            action TEXT NOT NULL,
            confidence REAL NOT NULL,
            reason TEXT,
            payload_json TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS outcomes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at INTEGER NOT NULL,
            root_ticket INTEGER,
            side TEXT,
            score INTEGER,
            profit REAL,
            result TEXT,
            payload_json TEXT NOT NULL
        )
        """
    )
    connection.commit()
    return connection


def recent_performance_summary() -> dict[str, Any]:
    """Resumen corto; nunca modifica reglas ni parametros por su cuenta."""
    with DB_LOCK:
        connection = db_connect()
        try:
            rows = connection.execute(
                """
                SELECT side, score, COUNT(*),
                       SUM(CASE WHEN profit > 0 THEN 1 ELSE 0 END),
                       COALESCE(SUM(profit), 0.0),
                       COALESCE(AVG(profit), 0.0)
                FROM (
                    SELECT * FROM outcomes ORDER BY id DESC LIMIT 200
                )
                GROUP BY side, score
                """
            ).fetchall()
        finally:
            connection.close()

    groups = []
    total = 0
    for side, score, count, wins, net, average in rows:
        total += int(count)
        groups.append(
            {
                "side": side,
                "score": score,
                "count": count,
                "win_rate": (wins / count if count else 0.0),
                "net": net,
                "average": average,
            }
        )
    return {"sample_size": total, "groups": groups}


def build_prompt(payload: dict[str, Any]) -> list[dict[str, str]]:
    event = str(payload.get("event", "ENTRY")).upper()
    allowed = ["ALLOW", "BLOCK"] if event == "ENTRY" else ["HOLD", "PROTECT", "CLOSE"]
    summary = recent_performance_summary()
    system = (
        "Eres un revisor conservador de riesgo para EURUSD M15. "
        "No puedes abrir operaciones por tu cuenta, aumentar lotes, quitar el stop loss, "
        "ampliar el riesgo ni prometer beneficios. El algoritmo determinista siempre manda. "
        f"Para este evento solo puedes elegir una accion de {allowed}. "
        "Si la evidencia es insuficiente, usa BLOCK para una entrada o HOLD para gestion. "
        "Devuelve exclusivamente JSON valido con action, confidence entre 0 y 1 y reason breve."
    )
    user = json.dumps(
        {"market_context": payload, "recent_closed_sample": summary},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def http_json(url: str, body: dict[str, Any]) -> dict[str, Any]:
    raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=raw,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=MODEL_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def query_model(payload: dict[str, Any]) -> dict[str, Any]:
    messages = build_prompt(payload)
    if PROVIDER == "ollama":
        response = http_json(
            MODEL_URL,
            {
                "model": MODEL,
                "messages": messages,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.1},
            },
        )
        content = response.get("message", {}).get("content", "")
    elif PROVIDER in {"openai", "openai_compatible", "lmstudio"}:
        response = http_json(
            MODEL_URL,
            {
                "model": MODEL,
                "messages": messages,
                "temperature": 0.1,
                "response_format": {"type": "json_object"},
            },
        )
        content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
    else:
        raise ValueError(f"Proveedor no soportado: {PROVIDER}")

    if isinstance(content, dict):
        return content
    return json.loads(str(content).strip())


def sanitize_decision(payload: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    event = str(payload.get("event", "ENTRY")).upper()
    allowed = {"ALLOW", "BLOCK"} if event == "ENTRY" else {"HOLD", "PROTECT", "CLOSE"}
    fallback = "BLOCK" if event == "ENTRY" else "HOLD"

    action = str(raw.get("action", fallback)).strip().upper()
    if action not in allowed:
        action = fallback

    try:
        confidence = float(raw.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    reason = str(raw.get("reason", "sin explicacion")).replace("|", "/")
    reason = " ".join(reason.split())[:240]
    sample_size = recent_performance_summary()["sample_size"]
    if sample_size < MIN_MEMORY:
        # Con poca memoria la respuesta sigue sirviendo en modo sombra, pero
        # no supera el umbral normal del EA para ejecutar una accion.
        confidence = min(confidence, 0.49)
        reason = f"muestra local insuficiente ({sample_size}/{MIN_MEMORY}); {reason}"[:240]
    return {"action": action, "confidence": confidence, "reason": reason}


def save_decision(payload: dict[str, Any], decision: dict[str, Any]) -> None:
    with DB_LOCK:
        connection = db_connect()
        try:
            connection.execute(
                """
                INSERT INTO decisions
                (created_at,event,ticket,side,score,action,confidence,reason,payload_json)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    int(time.time()),
                    str(payload.get("event", "")),
                    payload.get("ticket"),
                    payload.get("side"),
                    payload.get("score"),
                    decision["action"],
                    decision["confidence"],
                    decision["reason"],
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
            connection.commit()
        finally:
            connection.close()


def save_outcome(payload: dict[str, Any]) -> None:
    with DB_LOCK:
        connection = db_connect()
        try:
            connection.execute(
                """
                INSERT INTO outcomes
                (created_at,root_ticket,side,score,profit,result,payload_json)
                VALUES (?,?,?,?,?,?,?)
                """,
                (
                    int(time.time()),
                    payload.get("root_ticket"),
                    payload.get("side"),
                    payload.get("score"),
                    payload.get("profit"),
                    payload.get("result"),
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
            connection.commit()
        finally:
            connection.close()


def is_authorized(headers: Any) -> bool:
    """Autoriza la peticion contra el token compartido.

    Sin ASTUR_AI_SECRET configurado, el servicio queda abierto a cualquier
    proceso que alcance el puerto (solo aceptable en pruebas locales muy
    controladas). hmac.compare_digest evita filtrar el token por timing.
    """
    if not SHARED_SECRET:
        return True
    provided = headers.get("X-ASTUR-Token", "")
    return hmac.compare_digest(provided, SHARED_SECRET)


class Handler(BaseHTTPRequestHandler):
    server_version = "ASTUR-AI/0.40"

    def log_message(self, fmt: str, *args: Any) -> None:
        print("[%s] %s" % (self.log_date_time_string(), fmt % args), flush=True)

    def send_text(self, status: int, text: str, content_type: str = "text/plain") -> None:
        raw = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:  # noqa: N802
        if not is_authorized(self.headers):
            self.send_text(401, "no autorizado")
            return
        if self.path == "/health":
            self.send_text(
                200,
                json.dumps(
                    {"status": "ok", "provider": PROVIDER, "model": MODEL},
                    ensure_ascii=False,
                ),
                "application/json",
            )
            return
        self.send_text(404, "not found")

    def read_payload(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > MAX_BODY_BYTES:
            raise ValueError("tamano de peticion invalido")
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_POST(self) -> None:  # noqa: N802
        if not is_authorized(self.headers):
            self.send_text(401, "no autorizado")
            return
        try:
            payload = self.read_payload()
            if self.path == "/outcome":
                save_outcome(payload)
                self.send_text(200, "OK")
                return
            if self.path != "/decision":
                self.send_text(404, "not found")
                return

            raw_decision = query_model(payload)
            decision = sanitize_decision(payload, raw_decision)
            save_decision(payload, decision)
            self.send_text(
                200,
                f"{decision['action']}|{decision['confidence']:.4f}|{decision['reason']}",
            )
        except (ValueError, json.JSONDecodeError) as exc:
            self.send_text(400, f"ERROR|0|peticion invalida: {exc}")
        except (urllib.error.URLError, TimeoutError) as exc:
            self.send_text(503, f"ERROR|0|modelo local no disponible: {exc}")
        except Exception as exc:  # servicio local: registrar sin tumbar el proceso
            self.send_text(500, f"ERROR|0|fallo interno: {type(exc).__name__}: {exc}")


def main() -> None:
    with DB_LOCK:
        connection = db_connect()
        connection.close()
    if not SHARED_SECRET:
        print(
            "ADVERTENCIA: ASTUR_AI_SECRET no esta configurado. Cualquier "
            "proceso que alcance este puerto podria usar el puente. "
            "Configura ASTUR_AI_SECRET antes de activar UseLocalAI en el EA.",
            flush=True,
        )
    if HOST not in ("127.0.0.1", "localhost", "::1"):
        print(
            f"ADVERTENCIA: ASTUR_AI_HOST={HOST} no es loopback. Este servicio "
            "quedara alcanzable desde fuera de esta maquina; asegurate de que "
            "ASTUR_AI_SECRET este configurado y de que el firewall lo proteja.",
            flush=True,
        )
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(
        f"ASTUR AI bridge escuchando en http://{HOST}:{PORT} "
        f"(provider={PROVIDER}, model={MODEL}, "
        f"auth={'activada' if SHARED_SECRET else 'DESACTIVADA'})",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
