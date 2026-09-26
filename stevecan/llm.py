import asyncio
import json
import logging
import re
import httpx
from . import config

log = logging.getLogger("llm")
_sem = asyncio.Semaphore(config.LLM_PARALLEL)
_client: httpx.AsyncClient | None = None


def client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            base_url=config.LLM_BASE_URL,
            headers={"Authorization": f"Bearer {config.LLM_API_KEY}"},
            timeout=httpx.Timeout(600.0, connect=10.0),
        )
    return _client


async def chat(messages: list[dict], temperature: float | None = None,
               max_tokens: int | None = None, json_mode: bool = False) -> str:
    body = {
        "model": config.LLM_MODEL,
        "messages": messages,
        "temperature": config.LLM_TEMPERATURE if temperature is None else temperature,
        "max_tokens": max_tokens or config.LLM_MAX_TOKENS,
        "stream": False,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    delay = 2.0
    while True:
        try:
            async with _sem:
                r = await client().post("/chat/completions", json=body)
            if r.status_code >= 500 or r.status_code == 429:
                raise httpx.HTTPStatusError(r.text, request=r.request, response=r)
            r.raise_for_status()
            data = r.json()
            return data["choices"][0]["message"]["content"] or ""
        except (httpx.HTTPError, KeyError, json.JSONDecodeError) as e:
            log.warning("LLM error (%s); reintento en %.0fs", e, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60)


async def ask(system: str, user: str, **kw) -> str:
    return await chat([{"role": "system", "content": system},
                       {"role": "user", "content": user}], **kw)


def parse_json(text: str):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"(\{.*\}|\[.*\])", text, flags=re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            return None
    return None


async def ask_json(system: str, user: str, **kw):
    for attempt in range(3):
        out = await ask(system + "\nResponde ÚNICAMENTE con JSON válido.", user,
                        json_mode=attempt == 0, **kw)
        data = parse_json(out)
        if data is not None:
            return data
    return None


# ---- inteligencia: razonar, autocriticar, mejor-de-N ------------------------
_think_client: httpx.AsyncClient | None = None


async def ask_hard(system: str, user: str, **kw) -> str:
    """Tarea difícil: modelo *Thinking* si está configurado; si no, razonamiento explícito en dos pasos."""
    if config.LLM_THINK_BASE_URL:
        global _think_client
        if _think_client is None:
            _think_client = httpx.AsyncClient(base_url=config.LLM_THINK_BASE_URL, timeout=httpx.Timeout(900.0, connect=10.0),
                                              headers={"Authorization": f"Bearer {config.LLM_API_KEY}"})
        body = {"model": config.LLM_THINK_MODEL or config.LLM_MODEL, "stream": False,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "temperature": kw.get("temperature", 0.6), "max_tokens": kw.get("max_tokens", config.LLM_MAX_TOKENS) * 4}
        try:
            async with _sem:
                r = await _think_client.post("/chat/completions", json=body)
            r.raise_for_status()
            txt = r.json()["choices"][0]["message"]["content"] or ""
            return re.sub(r"<think>.*?</think>\s*", "", txt, flags=re.S).strip()
        except (httpx.HTTPError, KeyError, json.JSONDecodeError) as e:
            log.warning("modelo thinking no disponible (%s); uso razonamiento en dos pasos", e)
    if not config.REASONING:
        return await ask(system, user, **kw)
    out = await ask(system + "\nPrimero razona paso a paso de forma breve bajo 'RAZONAMIENTO:'. Después escribe la respuesta "
                    "definitiva bajo 'RESPUESTA FINAL:'.", user, **{**kw, "max_tokens": kw.get("max_tokens", config.LLM_MAX_TOKENS) + 800})
    m = re.search(r"RESPUESTA FINAL:\s*(.*)\Z", out, flags=re.S)
    return (m.group(1) if m else out).strip()


async def refine(system: str, user: str, draft: str, checks: str = "", **kw) -> str:
    """Autocrítica: busca errores concretos en el borrador y lo revisa. Si no hay errores, lo devuelve intacto."""
    critique = await ask(
        "Eres un revisor implacable. Señala SOLO errores concretos y verificables del borrador (hechos falsos, código que no "
        "compila o no cumple el objetivo, casos límite, contradicciones). Si no hay errores, responde exactamente 'SIN ERRORES'.",
        f"Tarea:\n{user[:6000]}\n\nBorrador:\n{draft[:8000]}\n{checks}", temperature=0.2, max_tokens=800)
    if critique.strip().upper().startswith("SIN ERRORES"):
        return draft
    return await ask(system, f"{user}\n\nBorrador anterior:\n{draft}\n\nErrores detectados por el revisor:\n{critique}\n\n"
                             "Entrega la versión corregida completa.", **kw)


async def best_of(system: str, user: str, n: int | None = None, judge_hint: str = "", **kw) -> str:
    """Genera N candidatos en paralelo (aprovecha los slots del servidor) y un juez elige el mejor."""
    n = n or config.BEST_OF
    if n <= 1:
        return await ask(system, user, **kw)
    cands = await asyncio.gather(*(ask(system, user, **{**kw, "temperature": 0.8}) for _ in range(n)))
    listing = "\n\n".join(f"### Candidato {i + 1}\n{c[:5000]}" for i, c in enumerate(cands))
    verdict = await ask_json("Eres un juez experto. Elige el candidato más correcto y completo. " + judge_hint,
                             f"Tarea:\n{user[:4000]}\n\n{listing}\n\nDevuelve {{\"best\": número}}", temperature=0.1)
    try:
        return cands[int(verdict["best"]) - 1]
    except (TypeError, KeyError, ValueError, IndexError):
        return cands[0]


async def healthy() -> bool:
    try:
        r = await client().get("/models")
        return r.status_code == 200
    except httpx.HTTPError:
        return False
