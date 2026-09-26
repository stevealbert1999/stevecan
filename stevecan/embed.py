"""Búsqueda semántica opcional (embeddings) que se fusiona con FTS5. Requiere EMBED_BASE_URL (llama-server --embeddings)."""
import asyncio
import logging
import math
import struct
import httpx
from . import config, memory

log = logging.getLogger("embed")
_client: httpx.AsyncClient | None = None


def enabled() -> bool:
    return bool(config.EMBED_BASE_URL)


def _c() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(base_url=config.EMBED_BASE_URL, timeout=120)
    return _client


async def embed_texts(texts: list[str]) -> list[list[float]]:
    r = await _c().post("/embeddings", json={"model": config.EMBED_MODEL, "input": [t[:6000] for t in texts]})
    r.raise_for_status()
    data = sorted(r.json()["data"], key=lambda d: d["index"])
    return [d["embedding"] for d in data]


def pack(v: list[float]) -> bytes:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return struct.pack(f"{len(v)}f", *(x / n for x in v))


def unpack(b: bytes) -> list[float]:
    return list(struct.unpack(f"{len(b) // 4}f", b))


async def index_missing(limit: int = 200) -> int:
    """Calcula embeddings de conocimiento, código, docs y skills que aún no los tienen."""
    if not enabled():
        return 0
    pending = memory.embedding_pending(limit)
    if not pending:
        return 0
    done = 0
    for i in range(0, len(pending), 32):
        batch = pending[i:i + 32]
        try:
            vecs = await embed_texts([p["text"] for p in batch])
        except (httpx.HTTPError, KeyError) as e:
            log.warning("embeddings: %s", e)
            break
        for p, v in zip(batch, vecs):
            memory.set_embedding(p["kind"], p["ref"], pack(v))
            done += 1
    return done


async def search(kind: str, query: str, limit: int = 8) -> list[tuple[int, float]]:
    """Devuelve [(ref_id, similitud)] por coseno. Fuerza bruta en Python (suficiente hasta ~100k vectores)."""
    if not enabled():
        return []
    try:
        q = (await embed_texts([query]))[0]
    except (httpx.HTTPError, KeyError):
        return []
    qn = math.sqrt(sum(x * x for x in q)) or 1.0
    q = [x / qn for x in q]
    try:
        import numpy as np  # opcional: mucho más rápido
        rows = memory.embeddings_of(kind)
        if not rows:
            return []
        mat = np.frombuffer(b"".join(r["vec"] for r in rows), dtype=np.float32).reshape(len(rows), -1)
        sims = mat @ np.asarray(q, dtype=np.float32)
        idx = np.argsort(-sims)[:limit]
        return [(rows[int(i)]["ref"], float(sims[int(i)])) for i in idx]
    except ImportError:
        scored = []
        for r in memory.embeddings_of(kind):
            v = unpack(r["vec"])
            scored.append((r["ref"], sum(a * b for a, b in zip(q, v))))
        scored.sort(key=lambda t: -t[1])
        return scored[:limit]


def rrf(*ranked_lists: list[int], k: int = 60) -> list[int]:
    """Fusión de rankings (Reciprocal Rank Fusion) entre FTS y embeddings."""
    score = {}
    for lst in ranked_lists:
        for rank, ref in enumerate(lst):
            score[ref] = score.get(ref, 0.0) + 1.0 / (k + rank + 1)
    return [ref for ref, _ in sorted(score.items(), key=lambda t: -t[1])]
