"""Los 8 agentes. Todos comparten el mismo modelo local y la misma memoria."""
import json
import re
import time
import unicodedata
from pathlib import Path
from . import config, llm, memory, tools
from .agent import Agent
from .ingest import index_dir

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
        own = memory.search_code(topic, 4)
        if own:
            known += "\nCódigo propio relacionado:\n" + "\n".join(
                f"[{c['repo']}/{c['path']}:{c['start_line']}]\n{c['content'][:800]}" for c in own)
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


# 9 -----------------------------------------------------------------------
class Librarian(Agent):
    """Conoce tu código: reindexa CODE_DIRS cuando cambian y resume cada fichero en la memoria."""
    name = "librarian"
    interval = config.CYCLE_SECONDS * 3

    async def step(self):
        if not config.CODE_DIRS:
            return None
        indexed = 0
        for d in config.CODE_DIRS:
            if d.is_dir():
                indexed += index_dir(d)["indexed"]
            else:
                self.log.warning("CODE_DIRS: %s no existe", d)
        done = 0
        for f in memory.code_files_without_summary(limit=4):
            text = memory.code_file_text(f["repo"], f["path"])[:12000]
            summary = await llm.ask(
                "Resume este fichero de código para un índice del proyecto: propósito, funciones/clases clave, "
                "dependencias y cómo se usa. 3-6 frases, solo lo que está en el código.",
                f"Fichero: {f['repo']}/{f['path']}\n\n{text}", max_tokens=400, temperature=0.2)
            memory.set_code_summary(f["repo"], f["path"], summary)
            kid = memory.add_knowledge(f"código:{f['repo']}", f"{f['path']}: {summary}",
                                       f"file://{f['repo']}/{f['path']}", self.name, confidence=0.85)
            memory.update_knowledge(kid, verified=True)
            done += 1
        if done:
            for repo in {f["repo"] for f in memory.rows("SELECT DISTINCT repo FROM code_files")}:
                memory.add_task("synthesize", {"topic": f"código:{repo}"}, self.name, priority=6)
        return f"ficheros reindexados={indexed} resumidos={done} {memory.code_stats()}" if (indexed or done) else None


def _slug(text):
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "tema"


# 10 ----------------------------------------------------------------------
class Expert(Agent):
    """Un ingeniero experto por dominio: profundiza sin parar en su campo (subtemas, fichas, ejemplos)."""
    interval = config.CYCLE_SECONDS * 4

    def __init__(self, domain):
        self.domain = domain
        self.name = "expert:" + _slug(domain)[:24]
        super().__init__()

    async def step(self):
        pend = memory.pending_counts()
        if pend.get("research", 0) >= 24:
            return None
        covered = memory.rows("SELECT DISTINCT topic FROM knowledge WHERE topic LIKE ? ORDER BY updated DESC LIMIT 40",
                              (f"%[{self.domain[:20]}%",))
        weak = memory.rows("SELECT topic, AVG(score) s FROM exams WHERE topic LIKE ? GROUP BY topic HAVING s<0.7 LIMIT 5",
                           (f"%[{self.domain[:20]}%",))
        data = await llm.ask_json(
            f"Eres un ingeniero senior experto en: {self.domain}. Diseñas tu propio plan de maestría: "
            "subtemas concretos, prácticos y verificables, de básico a avanzado, sin repetir lo cubierto.",
            f"Cubierto: {[c['topic'] for c in covered]}\nDébil: {weak}\n"
            'Devuelve {"subtopics":[{"topic":"...","practical":true|false}]} con 3 elementos.')
        if not data or not data.get("subtopics"):
            return None
        n = 0
        for st in data["subtopics"][:3]:
            if not isinstance(st, dict) or not st.get("topic"):
                continue
            topic = f"{st['topic']} [{self.domain[:20]}]"
            memory.add_task("research", {"topic": topic, "area": self.domain}, self.name, priority=5)
            if st.get("practical"):
                memory.add_task("code", {"topic": topic}, self.name, priority=6)
            n += 1
        return f"{n} subtemas encolados" if n else None


# 11 ----------------------------------------------------------------------
class Trainer(Agent):
    """Entrena velocidad y calidad programando: genera katas con tests reales, las resuelve contra reloj y mide."""
    name = "trainer"
    interval = config.CYCLE_SECONDS * 2

    async def step(self):
        import random
        domain = random.choice(config.EXPERT_DOMAINS)
        recent = memory.rows("SELECT AVG(passed) r FROM (SELECT passed FROM katas ORDER BY id DESC LIMIT 20)")[0]["r"]
        difficulty = 3 if recent is None else min(5, max(1, round(1 + 4 * recent)))
        kata = await llm.ask_json(
            "Diseña un ejercicio de programación en Python (solo librería estándar) con tests unittest "
            "que un experto resolvería en pocos minutos. Los tests deben importar `solution`.",
            f"Dominio: {domain}. Dificultad 1-5: {difficulty}.\n"
            'Devuelve {"title":"...","statement":"enunciado claro con firma de la función","tests":"código unittest completo que importa solution"}',
            max_tokens=1500)
        if not kata or not kata.get("tests") or not kata.get("statement"):
            return None
        kdir = config.KATAS_DIR / f"{int(time.time())}_{_slug(kata.get('title', 'kata'))}"
        kdir.mkdir(parents=True, exist_ok=True)
        (kdir / "test_solution.py").write_text(kata["tests"], encoding="utf-8")
        (kdir / "STATEMENT.md").write_text(kata["statement"], encoding="utf-8")
        t0, passed, feedback = time.time(), False, ""
        for attempt in range(1, 4):
            sol = await llm.ask("Eres un programador experto y rápido. Devuelve SOLO el código Python de solution.py, sin explicaciones ni markdown.",
                                f"{kata['statement']}\n\nTests:\n{kata['tests']}\n{feedback}", temperature=0.2, max_tokens=1500)
            sol = re.sub(r"^```(?:python)?\s*|\s*```$", "", sol.strip(), flags=re.S)
            (kdir / "solution.py").write_text(sol, encoding="utf-8")
            res = await tools.run_python_in(kdir, ["-m", "unittest", "-q", "test_solution"])
            if res["ok"]:
                passed = True
                break
            feedback = f"Fallo del intento {attempt}:\n{res['stderr'][-1500:]}\nCorrígelo."
        secs = time.time() - t0
        memory._q("INSERT INTO katas(domain,title,difficulty,passed,seconds,attempts,path,created) VALUES(?,?,?,?,?,?,?,?)",
                  (domain, kata.get("title", ""), difficulty, int(passed), secs, attempt, str(kdir), time.time()))
        if not passed:
            memory.add_task("research", {"topic": f"{kata.get('title', '')} (kata fallida) [{domain[:20]}]", "area": domain},
                            self.name, priority=3)
        return f"kata {'OK' if passed else 'FALLIDA'} ({domain[:25]}, dif {difficulty}, {secs:.0f}s, {attempt} intento/s)"


# 12 ----------------------------------------------------------------------
class Skillsmith(Agent):
    """Convierte lo aprendido en skills (formato Agent Skills) para tus agentes y los de Claude Code."""
    name = "skillsmith"
    interval = config.CYCLE_SECONDS * 6

    async def step(self):
        topics = memory.rows(
            "SELECT topic, COUNT(*) n FROM knowledge WHERE verified=1 GROUP BY topic HAVING n>=4 ORDER BY MAX(updated) DESC LIMIT 20")
        for t in topics:
            slug = _slug(t["topic"])
            path = config.SKILLS_DIR / slug / "SKILL.md"
            newest = memory.rows("SELECT MAX(updated) u FROM knowledge WHERE topic=?", (t["topic"],))[0]["u"] or 0
            if path.exists() and path.stat().st_mtime >= newest:
                continue
            facts = memory.rows("SELECT * FROM knowledge WHERE topic=? AND verified=1 ORDER BY confidence DESC LIMIT 25", (t["topic"],))
            body = await llm.ask(
                "Escribe un SKILL.md (Agent Skills): frontmatter YAML con `name` (slug dado) y `description` (cuándo usarlo, 1-2 frases), "
                "luego instrucciones accionables, procedimientos paso a paso, errores comunes y ejemplos, SOLO a partir de los hechos dados. "
                "Termina con sección 'Fuentes'.",
                f"name: {slug}\nTema: {t['topic']}\nHechos:\n{_ctx(facts, 25)}\n"
                f"Fuentes: {sorted({f['source'] for f in facts if f['source']})}", max_tokens=2200)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")
            return f"skill escrita: {slug}"
        return None


# 13 ----------------------------------------------------------------------
class Reviewer(Agent):
    """Mejora a los propios agentes: revisa el código de stevecan/ y escribe propuestas con parche en data/proposals/."""
    name = "reviewer"
    interval = config.CYCLE_SECONDS * 12

    async def step(self):
        own = Path(__file__).resolve().parent
        index_dir(own)
        files = sorted(p for p in own.glob("*.py") if p.name != "__init__.py")
        if not files:
            return None
        done = {p.stem for p in config.PROPOSALS_DIR.glob("*.md")}
        pending = [p for p in files if p.stem not in done] or files
        target = min(pending, key=lambda p: (config.PROPOSALS_DIR / f"{p.stem}.md").stat().st_mtime
                     if (config.PROPOSALS_DIR / f"{p.stem}.md").exists() else 0)
        src = target.read_text(encoding="utf-8")
        stats = memory.stats()
        review = await llm.ask(
            "Eres un ingeniero senior revisando el código de un sistema multiagente. Propón mejoras concretas "
            "(robustez, velocidad, calidad de aprendizaje) con un parche en formato diff unificado. Nada especulativo: "
            "cada propuesta debe referirse a líneas reales del fichero.",
            f"Métricas actuales del sistema: {json.dumps(stats, ensure_ascii=False, default=str)[:1500]}\n\n"
            f"Fichero stevecan/{target.name}:\n```python\n{src[:14000]}\n```", max_tokens=2500)
        out = config.PROPOSALS_DIR / f"{target.stem}.md"
        out.write_text(f"# Propuesta de mejora: stevecan/{target.name}\n\n_{time.strftime('%Y-%m-%d %H:%M')}_\n\n{review}\n",
                       encoding="utf-8")
        return f"propuesta escrita: {out.name}"


def build_agents():
    base = [Curriculum(), Researcher(), Critic(), Coder(), Synthesizer(), Examiner(), Curator(), Orchestrator(),
            Librarian(), Trainer(), Skillsmith(), Reviewer()]
    return base + [Expert(d) for d in config.EXPERT_DOMAINS]


ALL_AGENTS = [Curriculum, Researcher, Critic, Coder, Synthesizer, Examiner, Curator, Orchestrator, Librarian,
              Trainer, Skillsmith, Reviewer]
