"""Punto de unión de todos los agentes: responde con memoria (conocimiento + código + skills) y,
si no basta, busca en internet, lee fuentes reales y guarda lo aprendido. Nunca inventa."""
import asyncio
import logging
from . import llm, memory, tools

log = logging.getLogger("consult")
INSUFFICIENT = "INSUFICIENTE"


def _memory_context(question: str) -> tuple[str, int]:
    facts = memory.search(question, 6)
    code = memory.search_code(question, 5)
    skills = memory.search_skills(question, 2)
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


async def consult(question: str, agent: str = "consult", allow_web: bool = True) -> dict:
    ctx, n = _memory_context(question)
    system = ("Eres el sistema unificado de agentes. Responde SOLO con el contexto dado, citando ids, rutas o URLs. "
              f"Si el contexto no basta para responder con certeza, responde exactamente '{INSUFFICIENT}' y nada más.")
    answer = INSUFFICIENT
    if n:
        answer = (await llm.ask(system, f"Pregunta: {question}\n\n{ctx}", temperature=0.2, max_tokens=1200)).strip()
    used_web, urls = False, []
    if allow_web and (not n or answer.upper().startswith(INSUFFICIENT)):
        web, urls = await _web_context(question)
        if web:
            used_web = True
            answer = (await llm.ask(
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
    memory.log_event(agent, "consult", f"web={used_web} n_ctx={n} q={question[:100]}")
    return {"answer": answer, "used_web": used_web, "sources": urls, "context_items": n}


if __name__ == "__main__":
    import sys
    print(asyncio.run(consult(" ".join(sys.argv[1:]), "cli"))["answer"])
