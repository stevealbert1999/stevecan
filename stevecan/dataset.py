"""Construye el dataset de entrenamiento SOLO con datos reales producidos y verificados por el sistema
(exámenes sobre hechos verificados, katas superadas, mejoras aprobadas por tests, notas) más los datasets
externos que indiques en DATASETS (jsonl con {"prompt","response"} o {"messages"}, csv prompt,response, txt).
  python -m stevecan.dataset build   -> data/datasets/train-<ts>.jsonl (formato chat)
  python -m stevecan.dataset stats
"""
import csv
import json
import logging
import sys
import time
from pathlib import Path
from . import config, memory

log = logging.getLogger("dataset")
SYSTEM = "Eres un ingeniero experto, preciso y conciso. Respondes solo con hechos verificados y código correcto."


def _ex(prompt: str, response: str, source: str) -> dict:
    return {"messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": prompt.strip()},
                         {"role": "assistant", "content": response.strip()}], "source": source}


def _from_memory():
    out = []
    # Exámenes: pregunta -> respuesta esperada (derivada de hechos verificados), solo si el modelo acertó >= 0.8
    for r in memory.rows("SELECT question, expected, topic FROM exams WHERE score >= 0.8"):
        out.append(_ex(r["question"], r["expected"], f"exam:{r['topic']}"))
    # Hechos verificados con confianza alta: "explica X" -> hecho con fuente
    for r in memory.rows("SELECT topic, content, source FROM knowledge WHERE verified=1 AND confidence >= 0.8"):
        out.append(_ex(f"¿Qué sabes con certeza sobre: {r['topic']}?", f"{r['content']}\n\nFuente: {r['source']}", "knowledge"))
    # Katas superadas: enunciado -> solución que pasó los tests
    for r in memory.rows("SELECT title, domain, path FROM katas WHERE passed=1"):
        p = Path(r["path"])
        st, sol = p / "STATEMENT.md", p / "solution.py"
        if st.exists() and sol.exists():
            out.append(_ex(st.read_text(encoding="utf-8"), "```python\n" + sol.read_text(encoding="utf-8") + "\n```", f"kata:{r['domain']}"))
    # Mejoras aprobadas por tests: instrucción -> resumen + ficheros
    for ev in memory.rows("SELECT detail FROM events WHERE agent='developer' AND kind='improve'"):
        try:
            d = json.loads(ev["detail"])
        except json.JSONDecodeError:
            continue
        if d.get("ok") and d.get("summary"):
            out.append(_ex(f"Proyecto {Path(d['project']).name}: {d['instruction']}",
                           f"{d['summary']}\n\nFicheros modificados: {', '.join(d.get('files', []))}", "improvement"))
    # Notas de estudio
    for note in config.NOTES_DIR.glob("*.md"):
        text = note.read_text(encoding="utf-8")
        if len(text) > 400:
            out.append(_ex(f"Escribe una nota de estudio sobre: {note.stem.replace('_', ' ')}", text[:6000], "note"))
    return out


def _from_external():
    out = []
    for p in config.DATASETS:
        if not p.exists():
            log.warning("DATASETS: %s no existe", p)
            continue
        files = [p] if p.is_file() else [f for f in p.rglob("*") if f.suffix in (".jsonl", ".json", ".csv", ".txt", ".md")]
        for f in files:
            try:
                if f.suffix == ".jsonl":
                    for line in f.read_text(encoding="utf-8").splitlines():
                        if not line.strip():
                            continue
                        d = json.loads(line)
                        if "messages" in d:
                            out.append({"messages": d["messages"], "source": f"ext:{f.name}"})
                        elif "prompt" in d and "response" in d:
                            out.append(_ex(d["prompt"], d["response"], f"ext:{f.name}"))
                elif f.suffix == ".json":
                    for d in json.loads(f.read_text(encoding="utf-8")):
                        if "prompt" in d and "response" in d:
                            out.append(_ex(d["prompt"], d["response"], f"ext:{f.name}"))
                elif f.suffix == ".csv":
                    with f.open(encoding="utf-8", newline="") as fh:
                        for row in csv.DictReader(fh):
                            if row.get("prompt") and row.get("response"):
                                out.append(_ex(row["prompt"], row["response"], f"ext:{f.name}"))
                else:  # txt/md: continuación de texto (pretraining ligero)
                    text = f.read_text(encoding="utf-8")
                    for i in range(0, len(text), 3000):
                        chunk = text[i:i + 3000]
                        if len(chunk) > 500:
                            out.append(_ex(f"Reproduce el contenido de {f.name} (parte {i // 3000 + 1}).", chunk, f"ext:{f.name}"))
            except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
                log.warning("dataset %s: %s", f, e)
    return out


def build() -> Path:
    rows = _from_memory() + _from_external()
    seen, unique = set(), []
    for r in rows:
        key = json.dumps(r["messages"], ensure_ascii=False, sort_keys=True)
        if key not in seen:
            seen.add(key); unique.append(r)
    config.DATASETS_DIR.mkdir(parents=True, exist_ok=True)
    out = config.DATASETS_DIR / f"train-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
    with out.open("w", encoding="utf-8") as fh:
        for r in unique:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    by_src = {}
    for r in unique:
        k = r["source"].split(":")[0]; by_src[k] = by_src.get(k, 0) + 1
    log.info("dataset %s: %d ejemplos %s", out.name, len(unique), by_src)
    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
    a = sys.argv[1:]
    if a and a[0] == "build":
        print(build())
    elif a and a[0] == "stats":
        rows = _from_memory() + _from_external()
        by = {}
        for r in rows:
            k = r["source"].split(":")[0]; by[k] = by.get(k, 0) + 1
        print({"total": len(rows), **by})
    else:
        sys.exit(__doc__)
