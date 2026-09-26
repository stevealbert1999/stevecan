import time
from stevecan import config, evaluate, memory, roles


def test_build_agents_and_helpers():
    ags = roles.build_agents()
    assert len(ags) == 14 + len(config.EXPERT_DOMAINS)
    assert all(hasattr(a, "skills") and hasattr(a, "lessons") for a in ags)
    memory.add_lesson("t", "d", "Lección de prueba única.", "")
    assert "Lección de prueba única" in ags[0].lessons("Lección de prueba única")


def test_evaluate_alerts_on_low_scores():
    now = time.time()
    for i in range(6):
        memory._q("INSERT INTO exams(topic,question,expected,answer,score,created) VALUES(?,?,?,?,?,?)",
                  ("t", "q", "e", "a", 0.2, now - 60))
        memory._q("INSERT INTO katas(domain,title,difficulty,passed,seconds,attempts,path,created) VALUES(?,?,?,?,?,?,?,?)",
                  ("d", "k", 1, 0, 1.0, 1, "/x", now - 60))
    q = evaluate.evaluate(now)
    assert q["window_24h"]["exams"] >= 6 and q["window_24h"]["exam_avg"] < 0.6
    assert any("exam_avg" in a for a in q["alerts"]) and any("kata_pass_rate" in a for a in q["alerts"])
    assert (config.DATA_DIR / "alerts.log").exists()
    assert memory.metric_history("exam_avg")
