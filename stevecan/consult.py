"""Punto de unión de todos los agentes: responde con memoria (conocimiento + código + skills) y,
si no basta, busca en internet, lee fuentes reales y guarda lo aprendido. Nunca inventa."""
import asyncio
import logging
import re
from . import config, embed, llm, memory, tools

log = logging.getLogger("consult")
INSUFFICIENT = "INSUFICIENTE"


async def _queries(question: str) -> list[str]:
    """Multi-consulta: reformulaciones para mejorar la recuperación (sinónimos, términos técnicos, inglés)."""
    data = await llm.ask_json("Genera 3 reformulaciones cortas de la pregunta para buscar en una base de conocimiento y código "
                              "(incluye una en inglés con términos técnicos).",
                              f"Pregunta: {question}\nDevuelve {{\"queries\":[\"...\",\"...\",\"...\"]}}", temperature=0.3, max_tokens=200)
    qs = [q for q in (data or {}).get("queries", []) if isinstance(q, str) and q.strip()][:3]
    return [question] + qs


async def _hybrid(kind: str, table: str, fts_fn, queries: list[str], limit: int) -> list[dict]:
    """FTS5 con todas las reformulaciones + embeddings (si hay) fusionados por RRF."""
    rankings = [[r["id"] for r in fts_fn(q, limit)] for q in queries]
    if embed.enabled():
        rankings.append([ref for ref, _ in await embed.search(kind, queries[0], limit)])
    ids = embed.rrf(*rankings)[:limit]
    return memory.by_ids(table, ids)


async def _memory_context(question: str) -> tuple[str, int]:
    queries = await _queries(question)
    facts, code, skills = await asyncio.gather(
        _hybrid("knowledge", "knowledge", memory.search, queries, 6),
        _hybrid("code", "code_chunks", memory.search_code, queries, 5),
        _hybrid("skill", "skills_lib", memory.search_skills, queries, 2))
    for s_ in skills:
        s_["content"] = (s_.get("content") or "")[:4000]
    parts = []
    if facts:
        parts.append("## Conocimiento verificado\n" + "\n".join(
            f"- [{f['id']}] ({f['topic']}, conf={f['confidence']:.2f}, fuente={f['source']}) {f['content'][:500]}" for f in facts))
    if code:
        parts.append("## Código propio\n" + "\n\n".join(
            f"### {c['repo']}/{c['path']} (líneas {c['start_line']}-{c['end_line']})\n```\n{c['content'][:1800]}\n```" for c in code))
    if skills:
        parts.append("## Skills aplicables\n" + "\n\n".join(f"### {s['name']} ({s['source']})\n{s['content'][:1500]}" for s in skills))
    return "\n\n".join(parts), len(facts) + len(code) + len(skills)


async def _web_context(question: str, n_pages: int = 3) -> tuple[str, list[str]]:
    results = await tools.web_search(question, n=6)
    pages, urls = [], []
    for r in results:
        if len(pages) >= n_pages:
            break
        try:
            text = await tools.fetch_page(r["url"], 6000)
        except Exception:  # noqa: BLE001
            continue
        if len(text) > 300:
            pages.append(f"### {r['title']}\nURL: {r['url']}\n{text}")
            urls.append(r["url"])
    return "\n\n".join(pages), urls


async def _verify_code(answer: str) -> str:
    """Si la respuesta trae código Python autocontenido, lo ejecuta de verdad y adjunta el resultado (o el error)."""
    blocks = re.findall(r"```python\n(.*?)```", answer, flags=re.S)
    notes = []
    for code in blocks[:2]:
        if len(code) > 4000 or "input(" in code:
            continue
        r = await tools.run_python(code, timeout=30)
        notes.append(f"[ejecutado] {'OK' if r['ok'] else 'ERROR'}: {(r['stdout'] or r['stderr'])[-400:].strip()}")
    return "\n".join(notes)


async def consult(question: str, agent: str = "consult", allow_web: bool = True) -> dict:
    ctx, n = await _memory_context(question)
    lessons = memory.top_lessons(question, 3)
    if lessons:
        ctx += "\n\n## Lecciones aprendidas\n" + "\n".join(f"- {l['lesson']}" for l in lessons)
    system = ("Eres el sistema unificado de agentes. Responde SOLO con el contexto dado, citando ids, rutas o URLs. "
              f"Si el contexto no basta para responder con certeza, responde exactamente '{INSUFFICIENT}' y nada más.")
    answer = INSUFFICIENT
    if n:
        answer = (await llm.ask_hard(system, f"Pregunta: {question}\n\n{ctx}", temperature=0.2, max_tokens=1200)).strip()
    used_web, urls = False, []
    if allow_web and (not n or answer.upper().startswith(INSUFFICIENT)):
        web, urls = await _web_context(question)
        if web:
            used_web = True
            answer = (await llm.ask_hard(
                "Eres el sistema unificado de agentes. Responde con base en las fuentes web dadas y el contexto previo, "
                "citando URLs. Si las fuentes no responden a la pregunta, dilo claramente.",
                f"Pregunta: {question}\n\n{ctx}\n\n## Fuentes web\n{web}", temperature=0.2, max_tokens=1400)).strip()
            data = await llm.ask_json(
                "Extrae hechos verificables de las fuentes, cada uno con su URL.",
                f"Pregunta: {question}\n\n{web}\n\n" + 'Devuelve {"facts":[{"content":"...","source":"url","confidence":0.0-1.0}]} (máx 5)',
                max_tokens=900)
            for f in (data or {}).get("facts", [])[:5]:
                if isinstance(f, dict) and f.get("content"):
                    kid = memory.add_knowledge(question[:80], f["content"], f.get("source", urls[0] if urls else ""),
                                               agent, float(f.get("confidence", 0.5)))
                    memory.add_task("verify", {"knowledge_id": kid}, agent, priority=4)
    if answer.upper().startswith(INSUFFICIENT):
        answer = ("No tengo información fiable para responder esto: ni en la memoria ni en las fuentes web consultadas. "
                  "Se ha encolado como tema de investigación.")
        memory.add_task("research", {"topic": question[:120], "area": ""}, agent, priority=2)
    verified = ""
    if not answer.startswith("No tengo información"):
        verified = await _verify_code(answer)
        if "ERROR" in verified:
            answer = await llm.refine(system.replace(f"responde exactamente '{INSUFFICIENT}' y nada más", "dilo"),
                                      f"Pregunta: {question}\n\n{ctx}", answer, checks=f"Resultado de ejecutar el código:\n{verified}",
                                      temperature=0.2, max_tokens=1400)
            verified = await _verify_code(answer)
    memory.log_event(agent, "consult", f"web={used_web} n_ctx={n} q={question[:100]}")
    return {"answer": answer, "used_web": used_web, "sources": urls, "context_items": n, "verification": verified}


if __name__ == "__main__":
    import sys
    print(asyncio.run(consult(" ".join(sys.argv[1:]), "cli"))["answer"])
