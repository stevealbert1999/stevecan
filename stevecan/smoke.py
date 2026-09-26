"""Prueba contra el MODELO REAL: ejercita cada función que depende del modelo y comprueba que la respuesta es
usable (texto no vacío, JSON válido, razonamiento parseado, juez de mejor-de-N, autocrítica, búsqueda web + consulta).
  python -m stevecan.smoke            # en tu servidor, con llama-server arrancado
Sale con código 0 si todo pasa; 1 si algo falla (imprime qué)."""
import asyncio
import json
import sys
import time
from . import config, llm, memory, tools
from .consult import consult

RESULTS = []


async def check(name, coro, ok):
    t0 = time.time()
    try:
        out = await coro
        passed = bool(ok(out))
        detail = (json.dumps(out, ensure_ascii=False) if not isinstance(out, str) else out)[:160].replace("\n", " ")
    except Exception as e:  # noqa: BLE001
        passed, detail = False, f"EXCEPCIÓN: {e!r}"
    RESULTS.append((name, passed, time.time() - t0, detail))
    print(f"{'OK ' if passed else 'FAIL'} {name:<28} {time.time() - t0:5.1f}s  {detail}")
    return passed


async def main() -> int:
    print(f"modelo: {config.LLM_MODEL} en {config.LLM_BASE_URL}")
    if not await llm.healthy():
        print("FAIL el modelo no responde"); return 1
    await check("chat básico", llm.ask("Responde en una palabra.", "¿Capital de Francia?", max_tokens=20),
                lambda s: "par" in s.lower())
    await check("ask_json", llm.ask_json("Devuelve JSON.", 'Devuelve {"n": 7, "lista": [1,2,3]}', max_tokens=100),
                lambda d: isinstance(d, dict) and d.get("n") == 7)
    await check("ask_hard (razonamiento)", llm.ask_hard("Eres matemático.", "¿Cuánto es 17*23? Solo el número al final.", max_tokens=300),
                lambda s: "391" in s)
    await check("refine (autocrítica)", llm.refine("Responde con precisión.", "¿Cuántos días tiene un año bisiesto?", "365", max_tokens=100),
                lambda s: "366" in s)
    await check("best_of (juez)", llm.best_of("Responde brevemente.", "¿Cuál es el planeta más grande del sistema solar?", n=2, max_tokens=60),
                lambda s: "j" in s.lower() and "piter" in s.lower())
    await check("run_python", tools.run_python("print(sum(range(101)))"), lambda r: r["ok"] and "5050" in r["stdout"])
    await check("web_search", tools.web_search("llama.cpp server parallel slots", 3), lambda r: len(r) > 0)
    await check("consult (memoria/web)", consult("¿Qué es la decodificación especulativa en llama.cpp?", "smoke"),
                lambda r: len(r["answer"]) > 40)
    ok_n = sum(1 for _, p, _, _ in RESULTS if p)
    print(f"\n{ok_n}/{len(RESULTS)} pruebas OK · estado memoria: {memory.stats()}")
    return 0 if ok_n == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
