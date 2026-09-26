"""Pregunta al modelo local sobre tu código y conocimiento (RAG sobre la memoria compartida).
Uso: python -m stevecan.ask "¿dónde se inicializa el bus CAN?" """
import asyncio
import sys
from . import llm, memory


async def answer(question: str, code_limit: int = 8, knowledge_limit: int = 5) -> str:
    code = memory.search_code(question, code_limit)
    facts = memory.search(question, knowledge_limit)
    ctx = "\n\n".join(f"### {c['repo']}/{c['path']} (líneas {c['start_line']}-{c['end_line']})\n```\n{c['content']}\n```"
                      for c in code) or "(sin código indexado relevante)"
    kctx = "\n".join(f"- ({f['topic']}) {f['content'][:400]}" for f in facts) or "(nada)"
    sk = memory.search_skills(question, 2)
    if sk:
        kctx += "\n\n## Skills aplicables\n" + "\n\n".join(f"### {s['name']} ({s['source']})\n{s['content'][:1500]}" for s in sk)
    return await llm.ask(
        "Eres el asistente del proyecto. Responde SOLO con base en el código y hechos dados; cita rutas y líneas. "
        "Si la respuesta no está en el contexto, dilo claramente.",
        f"Pregunta: {question}\n\n## Código relevante\n{ctx}\n\n## Conocimiento relacionado\n{kctx}",
        max_tokens=1200, temperature=0.2)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    print(asyncio.run(answer(" ".join(sys.argv[1:]))))
