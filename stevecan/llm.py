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


async def healthy() -> bool:
    try:
        r = await client().get("/models")
        return r.status_code == 200
    except httpx.HTTPError:
        return False
