import json
import threading
import urllib.request
import urllib.error
import pytest
from http.server import ThreadingHTTPServer
from stevecan import config, serve


@pytest.fixture(scope="module")
def api():
    srv = ThreadingHTTPServer(("127.0.0.1", config.API_PORT), serve.Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True); t.start()
    yield f"http://127.0.0.1:{config.API_PORT}"
    srv.shutdown()


def _req(url, method="GET", data=None, token="test-token"):
    req = urllib.request.Request(url, method=method, data=json.dumps(data).encode() if data is not None else None)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def test_auth_required(api):
    assert _req(api + "/status", token=None)[0] == 401


def test_status_repeated_calls(api):
    for _ in range(3):
        code, body = _req(api + "/status")
        assert code == 200 and json.loads(body)["model_ok"] is False


def test_improve_and_research_enqueue(api):
    code, body = _req(api + "/improve", "POST", {"project": "/tmp/x", "instruction": "prueba"})
    assert code == 202 and "task" in json.loads(body)
    assert _req(api + "/research", "POST", {"topic": "tema"})[0] == 202
    assert _req(api + "/ask", "POST", {})[0] == 400


def test_metrics_and_dashboard(api):
    code, body = _req(api + "/metrics")
    assert code == 200 and "window_24h" in json.loads(body)
    code, body = _req(api + "/dashboard")
    assert code == 200 and "<h1>stevecan</h1>" in body
