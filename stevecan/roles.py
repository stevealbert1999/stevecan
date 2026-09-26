"""Los 8 agentes. Todos comparten el mismo modelo local y la misma memoria."""
import json
import time
from pathlib import Path
from . import config, llm, memory, tools
from .agent import Agent

SEED_TOPICS = [
    "matemáticas avanzadas", "física", "programación en Python", "algoritmos y estructuras de datos",
    "aprendizaje automático", "redes y sistemas", "economía", "historia", "biología", "química",
]


def _ctx(rows, limit=6):
    return "\n".join(f"[{r['id']}] ({r['topic']}, conf={r['confidence']:.2f}) {r['content'][:500]}"
                     for r in rows[:limit]) or "(vacío)"


# 1 -----------------------------------------------------------------------
class Curriculum(Agent):
    """Decide qué aprender: detecta huecos y genera tareas de investigación/código."""
    name = "curriculum"
    interval = config.CYCLE_SECONDS * 3

    async def step(self):
        pend = memory.pending_counts()
        if pend.get("research", 0) >= 12:
            return None
        topics = memory.rows("SELECT topic, COUNT(*) n, AVG(confidence) c FROM knowledge GROUP BY topic ORDER BY n DESC LIMIT 40")
        weak = memory.rows("SELECT topic, AVG(score) s FROM exams GROUP BY topic HAVING s < 0.7 ORDER BY s LIMIT 10")
        known = ", ".join(f"{t['topic']}({t['n']})" for t in topics) or "nada todavía"
        data = await llm.ask_json(
            "Eres el planificador de currículo de una IA que aprende sin parar. Propón temas nuevos, concretos y "
            "verificables (no vagos), priorizando huecos y puntos débiles. Diversifica entre áreas.",
            f"Áreas semilla: {', '.join(SEED_TOPICS)}\nTemas ya cubiertos: {known}\n"
            f"Puntos débiles en exámenes: {json.dumps(weak, ensure_ascii=False)}\n"
            'Devuelve {"topics":[{"topic":"...","area":"...","why":"...","needs_code":true|false}]} con 6 elementos.')
        if not data or "topics" not in data:
            return "sin propuestas"
        n = 0
        for t in data["topics"][:6]:
            if not isinstance(t, dict) or not t.get("topic"):
                continue
            memory.add_task("research", {"topic": t["topic"], "area": t.get("area", "")}, self.name, priority=4)
            if t.get("needs_code"):
                memory.add_task("code", {"topic": t["topic"]}, self.name, priority=6)
            n += 1
        return f"{n} temas nuevos encolados"


# 2 -----------------------------------------------------------------------
class Researcher(Agent):
    """Busca en la web, lee fuentes reales y extrae conocimiento con cita."""
    name = "researcher"

    async def step(self):
        task = memory.take_task("research", self.name)
        if not task:
            return None
        topic = task["payload"]["topic"]
        results = await tools.web_search(topic, n=5)
        if not results:
            memory.finish_task(task["id"], "sin resultados de búsqueda", "failed")
            return f"sin resultados: {topic}"
        pages = []
        for r in results[:3]:
            try:
                pages.append((r["url"], await tools.fetch_page(r["url"], 7000)))
            except Exception as e:  # noqa: BLE001
                self.log.debug("no se pudo leer %s: %s", r["url"], e)
        if not pages:
            memory.finish_task(task["id"], "no se pudo leer ninguna fuente", "failed")
            return f"fuentes ilegibles: {topic}"
        src_text = "\n\n".join(f"FUENTE {u}\n{t}" for u, t in pages)
        data = await llm.ask_json(
            "Eres un investigador riguroso. Extrae hechos concretos y verificables SOLO de las fuentes dadas. "
            "Nada inventado. Cada hecho debe citar la URL de la fuente.",
            f"Tema: {topic}\n\n{src_text}\n\n"
            'Devuelve {"facts":[{"content":"hecho autocontenido (2-4 frases)","source":"url","confidence":0.0-1.0}]} '
            "con entre 3 y 8 hechos.", max_tokens=1800)
        if not data or not data.get("facts"):
            memory.finish_task(task["id"], "sin hechos extraídos", "failed")
            return f"sin hechos: {topic}"
        ids = []
        for f in data["facts"]:
            if isinstance(f, dict) and f.get("content"):
                ids.append(memory.add_knowledge(topic, f["content"], f.get("source", pages[0][0]),
                                                self.name, float(f.get("confidence", 0.5))))
        for kid in ids:
            memory.add_task("verify", {"knowledge_id": kid}, self.name, priority=5)
        memory.add_task("synthesize", {"topic": topic}, self.name, priority=7)
        memory.add_task("exam", {"topic": topic}, self.name, priority=8)
        memory.finish_task(task["id"], f"{len(ids)} hechos")
        return f"{topic}: {len(ids)} hechos de {len(pages)} fuentes"


# 3 -----------------------------------------------------------------------
class Critic(Agent):
    """Verifica cada hecho contra su fuente original; corrige o elimina."""
    name = "critic"

    async def step(self):
        task = memory.take_task("verify", self.name)
        if not task:
            return None
        kid = task["payload"]["knowledge_id"]
        row = memory.rows("SELECT * FROM knowledge WHERE id=?", (kid,))
        if not row:
            memory.finish_task(task["id"], "no existe", "failed")
            return None
        k = row[0]
        source_text = ""
        if k["source"] and k["source"].startswith("http"):
            try:
                source_text = await tools.fetch_page(k["source"], 8000)
            except Exception:  # noqa: BLE001
                source_text = ""
        data = await llm.ask_json(
            "Eres un verificador escéptico. Compara la afirmación con la fuente. Detecta errores, "
            "exageraciones o afirmaciones no respaldadas.",
            f"Afirmación: {k['content']}\nFuente ({k['source']}):\n{source_text or '(no accesible)'}\n\n"
            'Devuelve {"verdict":"correct|fix|delete","confidence":0.0-1.0,"fixed_content":"solo si verdict=fix","reason":"..."}')
        if not data:
            memory.finish_task(task["id"], "sin veredicto", "failed")
            return None
        v = data.get("verdict")
        conf = float(data.get("confidence", k["confidence"]))
        if v == "delete":
            memory.delete_knowledge(kid)
        elif v == "fix" and data.get("fixed_content"):
            memory.update_knowledge(kid, content=data["fixed_content"], confidence=conf, verified=True)
        else:
            memory.update_knowledge(kid, confidence=conf, verified=True)
        memory.finish_task(task["id"], f"{v}: {data.get('reason', '')}")
        return f"hecho {kid}: {v} ({conf:.2f})"


# 4 -----------------------------------------------------------------------
class Coder(Agent):
    """Aprende haciendo: escribe código Python, lo ejecuta de verdad y guarda lo que funciona."""
    name = "coder"

    async def step(self):
        task = memory.take_task("code", self.name)
        if not task:
            return None
        topic = task["payload"]["topic"]
        known = _ctx(memory.search(topic))
        code, result = "", {}
        feedback = ""
        for attempt in range(3):
            data = await llm.ask_json(
                "Eres un programador que aprende experimentando. Escribe un script Python autocontenido "
                "(solo librería estándar) que demuestre o compruebe algo concreto del tema, imprimiendo resultados.",
                f"Tema: {topic}\nConocimiento previo:\n{known}\n{feedback}\n"
                'Devuelve {"goal":"qué se comprueba","code":"..."}', max_tokens=2000)
            if not data or not data.get("code"):
                continue
            code = data["code"]
            result = await tools.run_python(code)
            if result["ok"]:
                break
            feedback = f"Intento anterior falló:\n{result['stderr'][-1500:]}\nCorrígelo."
        if not result.get("ok"):
            memory.finish_task(task["id"], result.get("stderr", "sin código"), "failed")
            return f"{topic}: código fallido"
        summary = await llm.ask(
            "Resume en 2-4 frases qué demuestra este experimento y qué se aprendió. Solo hechos derivados de la salida.",
            f"Tema: {topic}\nCódigo:\n{code}\nSalida:\n{result['stdout']}", max_tokens=400)
        path = config.WORKSPACE_DIR / f"{int(time.time())}_{topic[:40].replace('/', '_').replace(' ', '_')}.py"
        path.write_text(code, encoding="utf-8")
        kid = memory.add_knowledge(topic, summary, f"file://{path}", self.name, confidence=0.8)
        memory.update_knowledge(kid, verified=True)
        memory.finish_task(task["id"], str(path))
        return f"{topic}: experimento OK -> {path.name}"


# 5 -----------------------------------------------------------------------
class Synthesizer(Agent):
    """Consolida los hechos de un tema en una nota Markdown coherente."""
    name = "synthesizer"

    async def step(self):
        task = memory.take_task("synthesize", self.name)
        if not task:
            return None
        topic = task["payload"]["topic"]
        facts = memory.rows("SELECT * FROM knowledge WHERE topic=? ORDER BY confidence DESC LIMIT 30", (topic,))
        if len(facts) < 2:
            memory.finish_task(task["id"], "pocos hechos", "failed")
            return None
        note = await llm.ask(
            "Eres un redactor técnico. Escribe una nota de estudio en Markdown, clara y estructurada, usando "
            "SOLO los hechos dados. Incluye sección 'Fuentes' con las URLs.",
            f"Tema: {topic}\nHechos:\n{_ctx(facts, 30)}\nFuentes: {sorted({f['source'] for f in facts if f['source']})}",
            max_tokens=2000)
        path = config.NOTES_DIR / (topic[:60].replace("/", "_").replace(" ", "_") + ".md")
        path.write_text(note, encoding="utf-8")
        memory.finish_task(task["id"], str(path))
        return f"nota escrita: {path.name}"


# 6 -----------------------------------------------------------------------
class Examiner(Agent):
    """Examina al modelo SIN contexto para medir qué ha interiorizado; reporta huecos."""
    name = "examiner"

    async def step(self):
        task = memory.take_task("exam", self.name)
        if not task:
            return None
        topic = task["payload"]["topic"]
        facts = memory.rows("SELECT * FROM knowledge WHERE topic=? AND verified=1 ORDER BY confidence DESC LIMIT 10", (topic,))
        if not facts:
            memory.finish_task(task["id"], "sin hechos verificados", "failed")
            return None
        qs = await llm.ask_json(
            "Genera preguntas de examen precisas cuya respuesta esté en los hechos dados.",
            f"Tema: {topic}\nHechos:\n{_ctx(facts, 10)}\n"
            'Devuelve {"questions":[{"q":"...","expected":"respuesta breve"}]} con 3 preguntas.')
        if not qs or not qs.get("questions"):
            memory.finish_task(task["id"], "sin preguntas", "failed")
            return None
        scores = []
        for item in qs["questions"][:3]:
            answer = await llm.ask("Responde de forma breve y precisa.", item["q"], temperature=0.2, max_tokens=300)
            grade = await llm.ask_json(
                "Califica la respuesta frente a la esperada.",
                f"Pregunta: {item['q']}\nEsperada: {item['expected']}\nRespuesta: {answer}\n"
                'Devuelve {"score":0.0-1.0,"reason":"..."}', temperature=0.1)
            s = float(grade.get("score", 0)) if grade else 0.0
            scores.append(s)
            memory._q("INSERT INTO exams(topic,question,expected,answer,score,created) VALUES(?,?,?,?,?,?)",
                      (topic, item["q"], item["expected"], answer, s, time.time()))
        avg = sum(scores) / len(scores)
        if avg < 0.6:
            memory.add_task("research", {"topic": topic + " (profundizar)", "area": ""}, self.name, priority=3)
        memory.finish_task(task["id"], f"media {avg:.2f}")
        return f"examen {topic}: {avg:.2f}"


# 7 -----------------------------------------------------------------------
class Curator(Agent):
    """Mantiene la memoria: duplicados, hechos de baja confianza, tareas atascadas."""
    name = "curator"
    interval = config.CYCLE_SECONDS * 6

    async def step(self):
        stale = memory.requeue_stale()
        low = memory.rows("SELECT id FROM knowledge WHERE verified=1 AND confidence<0.3")
        for r in low:
            memory.delete_knowledge(r["id"])
        dups = memory.rows("SELECT topic FROM knowledge GROUP BY topic HAVING COUNT(*) > 8 LIMIT 3")
        merged = 0
        for d in dups:
            facts = memory.rows("SELECT * FROM knowledge WHERE topic=? ORDER BY id", (d["topic"],))
            data = await llm.ask_json(
                "Detecta hechos duplicados o redundantes. Devuelve los ids a eliminar (conserva el más completo).",
                f"{_ctx(facts, 40)}\nDevuelve {{\"delete_ids\":[...]}}", temperature=0.1)
            for kid in (data or {}).get("delete_ids", []):
                if isinstance(kid, int) and any(f["id"] == kid for f in facts):
                    memory.delete_knowledge(kid); merged += 1
        memory._q("DELETE FROM events WHERE created < ?", (time.time() - 7 * 86400,))
        return f"reencoladas={stale} baja_conf={len(low)} duplicados={merged}"


# 8 -----------------------------------------------------------------------
class Orchestrator(Agent):
    """Supervisa el sistema, comprueba el modelo y escribe el informe de estado."""
    name = "orchestrator"
    interval = config.CYCLE_SECONDS * 4

    async def step(self):
        ok = await llm.healthy()
        st = memory.stats()
        if ok and not st["pending"] and st["knowledge"] == 0:
            for t in SEED_TOPICS:
                memory.add_task("research", {"topic": t, "area": t}, self.name, priority=5)
        recent = memory.rows("SELECT agent, kind, detail FROM events ORDER BY id DESC LIMIT 30")
        report = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "model_ok": ok, "stats": st, "recent": recent}
        Path(config.DATA_DIR / "status.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
        return f"modelo={'OK' if ok else 'CAÍDO'} conocimiento={st['knowledge']} verificados={st['verified']} pendientes={st['pending']}"


ALL_AGENTS = [Curriculum, Researcher, Critic, Coder, Synthesizer, Examiner, Curator, Orchestrator]
