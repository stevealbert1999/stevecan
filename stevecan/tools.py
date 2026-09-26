"""Herramientas reales: búsqueda web, descarga de páginas, ejecución de código."""
import asyncio
import base64
import html
import re
import sys
import urllib.parse
import httpx
from . import config

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
      "Accept-Language": "es,en;q=0.8"}


def _strip_html(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style|noscript|svg|nav|footer|header).*?</\1>", " ", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    raw = html.unescape(raw)
    return re.sub(r"\s+", " ", raw).strip()


def _decode_bing(href: str) -> str:
    m = re.search(r"[?&]u=a1([A-Za-z0-9_\-=]+)", href)
    if not m:
        return href
    raw = m.group(1).replace("-", "+").replace("_", "/")
    raw += "=" * (-len(raw) % 4)
    try:
        return base64.b64decode(raw).decode("utf-8", "ignore")
    except Exception:  # noqa: BLE001
        return href


async def _search_searxng(c: httpx.AsyncClient, query: str, n: int) -> list[dict]:
    if not config.SEARXNG_URL:
        return []
    r = await c.get(config.SEARXNG_URL.rstrip("/") + "/search",
                    params={"q": query, "format": "json", "language": "es-ES"})
    if r.status_code != 200:
        return []
    return [{"url": x["url"], "title": x.get("title", ""), "snippet": x.get("content", "")}
            for x in r.json().get("results", [])[:n]]


async def _search_ddg(c: httpx.AsyncClient, query: str, n: int) -> list[dict]:
    r = await c.get("https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query}))
    if r.status_code != 200:
        return []
    out = []
    for m in re.finditer(r'<a rel="nofollow" class="result__a" href="([^"]+)"[^>]*>(.*?)</a>.*?'
                         r'class="result__snippet"[^>]*>(.*?)</a>', r.text, flags=re.S):
        href = html.unescape(m.group(1))
        if "uddg=" in href:
            href = urllib.parse.parse_qs(urllib.parse.urlparse(href).query).get("uddg", [href])[0]
        out.append({"url": href, "title": _strip_html(m.group(2)), "snippet": _strip_html(m.group(3))})
        if len(out) >= n:
            break
    return out


async def _search_bing(c: httpx.AsyncClient, query: str, n: int) -> list[dict]:
    r = await c.get("https://www.bing.com/search?" + urllib.parse.urlencode({"q": query}))
    if r.status_code != 200:
        return []
    out = []
    for item in re.split(r'<li class="b_algo"', r.text)[1:]:
        m = re.search(r'<h2[^>]*>\s*<a[^>]*href="(http[^"]+)"[^>]*>(.*?)</a>', item, flags=re.S)
        if not m:
            continue
        s = re.search(r"<p[^>]*>(.*?)</p>", item, flags=re.S)
        out.append({"url": _decode_bing(html.unescape(m.group(1))), "title": _strip_html(m.group(2)),
                    "snippet": _strip_html(s.group(1)) if s else ""})
        if len(out) >= n:
            break
    return out


async def web_search(query: str, n: int = 6) -> list[dict]:
    """Búsqueda real. Orden: SearXNG propio (ilimitado) -> DuckDuckGo -> Bing."""
    async with httpx.AsyncClient(headers=UA, timeout=30, follow_redirects=True) as c:
        for backend in (_search_searxng, _search_ddg, _search_bing):
            try:
                res = await backend(c, query, n)
            except Exception:  # noqa: BLE001
                res = []
            if res:
                return res
    return []


async def fetch_page(url: str, max_chars: int = 12000) -> str:
    async with httpx.AsyncClient(headers=UA, timeout=30, follow_redirects=True) as c:
        r = await c.get(url)
    r.raise_for_status()
    ctype = r.headers.get("content-type", "")
    text = r.text if "html" in ctype or "text" in ctype or "json" in ctype else ""
    if "html" in ctype:
        text = _strip_html(text)
    return text[:max_chars]


async def run_python(code: str, timeout: int = 60) -> dict:
    path = config.WORKSPACE_DIR / "_run.py"
    path.write_text(code, encoding="utf-8")
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-I", str(path), cwd=config.WORKSPACE_DIR,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return {"ok": False, "stdout": "", "stderr": f"timeout {timeout}s"}
    return {"ok": proc.returncode == 0, "stdout": out.decode()[-6000:], "stderr": err.decode()[-3000:]}


async def run_python_in(cwd, args: list[str], timeout: int = 120) -> dict:
    """Ejecuta `python <args>` dentro de un directorio (p. ej. tests unittest de una kata)."""
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-B", *args, cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return {"ok": False, "stdout": "", "stderr": f"timeout {timeout}s"}
    return {"ok": proc.returncode == 0, "stdout": out.decode()[-6000:], "stderr": err.decode()[-3000:]}
