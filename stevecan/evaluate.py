"""Evaluación de calidad: métricas por ventana, comparación con la ventana anterior y alertas si el sistema empeora.
  python -m stevecan.evaluate          # imprime métricas y alertas
Umbrales en EVAL_* del .env. El orchestrator lo ejecuta en cada ciclo y escribe data/status.json y data/alerts.log."""
import json
import sys
import time
from . import config, memory

WINDOW = 24 * 3600


def _avg(sql, args):
    r = memory._q(sql, args).fetchone()
    return None if r is None or r[0] is None else float(r[0])


def _count(sql, args):
    return int(memory._q(sql, args).fetchone()[0] or 0)


def window_metrics(t_from: float, t_to: float) -> dict:
    a = (t_from, t_to)
    return {
        "exam_avg": _avg("SELECT AVG(score) FROM exams WHERE created>=? AND created<?", a),
        "exams": _count("SELECT COUNT(*) FROM exams WHERE created>=? AND created<?", a),
        "kata_pass_rate": _avg("SELECT AVG(passed) FROM katas WHERE created>=? AND created<?", a),
        "kata_avg_seconds": _avg("SELECT AVG(seconds) FROM katas WHERE passed=1 AND created>=? AND created<?", a),
        "katas": _count("SELECT COUNT(*) FROM katas WHERE created>=? AND created<?", a),
        "facts_added": _count("SELECT COUNT(*) FROM knowledge WHERE created>=? AND created<?", a),
        "facts_verified": _count("SELECT COUNT(*) FROM knowledge WHERE verified=1 AND updated>=? AND updated<?", a),
        "critic_deletes": _count("SELECT COUNT(*) FROM events WHERE agent='critic' AND kind='step' AND detail LIKE '%: delete%' AND created>=? AND created<?", a),
        "critic_verdicts": _count("SELECT COUNT(*) FROM events WHERE agent='critic' AND kind='step' AND created>=? AND created<?", a),
        "improvements_ok": _count("SELECT COUNT(*) FROM events WHERE agent='developer' AND kind='improve' AND detail LIKE '%\"ok\": true%' AND created>=? AND created<?", a),
        "improvements_total": _count("SELECT COUNT(*) FROM events WHERE agent='developer' AND kind='improve' AND created>=? AND created<?", a),
        "errors": _count("SELECT COUNT(*) FROM events WHERE kind='error' AND created>=? AND created<?", a),
        "steps": _count("SELECT COUNT(*) FROM events WHERE kind='step' AND created>=? AND created<?", a),
        "lessons": _count("SELECT COUNT(*) FROM lessons WHERE created>=? AND created<?", a),
    }


def evaluate(now: float | None = None) -> dict:
    now = now or time.time()
    cur = window_metrics(now - WINDOW, now)
    prev = window_metrics(now - 8 * WINDOW, now - WINDOW)  # 7 días anteriores
    cur["critic_delete_rate"] = (cur["critic_deletes"] / cur["critic_verdicts"]) if cur["critic_verdicts"] else None
    prev["critic_delete_rate"] = (prev["critic_deletes"] / prev["critic_verdicts"]) if prev["critic_verdicts"] else None
    cur["improvement_rate"] = (cur["improvements_ok"] / cur["improvements_total"]) if cur["improvements_total"] else None
    prev["improvement_rate"] = (prev["improvements_ok"] / prev["improvements_total"]) if prev["improvements_total"] else None
    cur["error_rate"] = (cur["errors"] / (cur["steps"] + cur["errors"])) if (cur["steps"] + cur["errors"]) else None
    alerts = []

    def worse(name, minimum=None, drop=None, higher_is_bad=False, min_samples=5, samples_key=None):
        v, p = cur.get(name), prev.get(name)
        n = cur.get(samples_key, min_samples) if samples_key else min_samples
        if v is None or n < min_samples:
            return
        if minimum is not None and ((v > minimum) if higher_is_bad else (v < minimum)):
            alerts.append(f"{name}={v:.2f} {'supera' if higher_is_bad else 'por debajo de'} el umbral {minimum}")
        if drop is not None and p is not None:
            delta = (v - p) if higher_is_bad else (p - v)
            if delta > drop:
                alerts.append(f"{name} {'sube' if higher_is_bad else 'cae'} de {p:.2f} a {v:.2f} (>{drop})")

    worse("exam_avg", minimum=config.EVAL_MIN_EXAM, drop=config.EVAL_MAX_DROP, samples_key="exams")
    worse("kata_pass_rate", minimum=config.EVAL_MIN_KATA, drop=config.EVAL_MAX_DROP, samples_key="katas")
    worse("critic_delete_rate", minimum=config.EVAL_MAX_DELETE_RATE, higher_is_bad=True, samples_key="critic_verdicts")
    worse("error_rate", minimum=config.EVAL_MAX_ERROR_RATE, higher_is_bad=True, min_samples=20, samples_key="steps")
    if cur["steps"] == 0 and prev["steps"] > 0:
        alerts.append("sin actividad de agentes en las últimas 24 h")
    for k in ("exam_avg", "kata_pass_rate", "kata_avg_seconds", "critic_delete_rate", "improvement_rate", "error_rate"):
        if cur.get(k) is not None:
            memory.metric_add(k, cur[k])
    if alerts:
        with (config.DATA_DIR / "alerts.log").open("a", encoding="utf-8") as fh:
            for a in alerts:
                fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {a}\n")
        memory.log_event("evaluate", "alert", " | ".join(alerts))
    return {"window_24h": cur, "previous_7d": prev, "alerts": alerts, "ok": not alerts}


if __name__ == "__main__":
    print(json.dumps(evaluate(), ensure_ascii=False, indent=2))
    sys.exit(0)
