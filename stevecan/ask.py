"""Pregunta al sistema unificado: memoria (conocimiento + código + skills) y, si no basta, internet con fuentes.
Uso: python -m stevecan.ask "¿dónde se inicializa el bus CAN?" """
import asyncio
import sys
from . import config, llm
from .consult import consult


async def answer(question: str) -> str:
    r = await consult(question, "ask")
    out = r["answer"]
    if r["sources"]:
        out += "\n\nFuentes web:\n" + "\n".join(f"- {u}" for u in r["sources"])
    return out


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    if not asyncio.run(llm.healthy()):
        sys.exit(f"el modelo no responde en {config.LLM_BASE_URL}: arranca llama-server (scripts/llama-server.sh) o revisa LLM_BASE_URL")
    print(asyncio.run(answer(" ".join(sys.argv[1:]))))
