import time
from stevecan import memory


def test_tasks_dedupe_take_finish_requeue():
    t1 = memory.add_task("kind-test", {"topic": "x"}, "t")
    t2 = memory.add_task("kind-test", {"topic": "x"}, "t")
    assert t1 == t2
    task = memory.take_task("kind-test", "a")
    assert task["id"] == t1 and task["payload"]["topic"] == "x"
    assert memory.take_task("kind-test", "a") is None
    assert memory.requeue_stale(0) >= 1
    task = memory.take_task("kind-test", "b")
    memory.finish_task(task["id"], "ok")
    assert memory.rows("SELECT status FROM tasks WHERE id=?", (t1,))[0]["status"] == "done"


def test_knowledge_fts_update_delete():
    kid = memory.add_knowledge("python", "Python usa indentación para delimitar bloques", "https://docs.python.org", "t", 0.7)
    assert any(r["id"] == kid for r in memory.search("indentación bloques"))
    memory.update_knowledge(kid, content="Python delimita bloques por sangría", confidence=0.9, verified=True)
    assert any(r["id"] == kid for r in memory.search("sangría"))
    assert not any(r["id"] == kid for r in memory.search("indentación"))
    memory.delete_knowledge(kid)
    assert not any(r["id"] == kid for r in memory.search("sangría"))


def test_lessons_weight_and_search():
    a = memory.add_lesson("trainer", "python", "Valida listas vacías antes de indexar.", "ev")
    b = memory.add_lesson("trainer", "python", "Valida listas vacías antes de indexar.", "ev")
    assert a == b
    assert memory.rows("SELECT weight FROM lessons WHERE id=?", (a,))[0]["weight"] == 2.0
    assert any(l["id"] == a for l in memory.top_lessons("indexar listas", 3))


def test_plans_lifecycle():
    memory.plan_add("dominio X", "sub 1", 1, False)
    memory.plan_add("dominio X", "sub 1", 1, False)  # ignorado
    memory.plan_add("dominio X", "sub 2", 2, True)
    assert memory.plan_stats("dominio X")["pending"] == 2
    nxt = memory.plan_next("dominio X", 1)
    assert nxt[0]["subtopic"] == "sub 1" and nxt[0]["attempts"] == 0
    assert memory.plan_stats("dominio X")["in_progress"] == 1
    memory.plan_mark("dominio X", "sub 1", "done")
    assert memory.plan_stats("dominio X")["done"] == 1
    assert memory.plan_subtopics("dominio X") == ["sub 1", "sub 2"]


def test_code_index_and_search():
    memory.replace_code_file("repo", "src/a.py", "sha1", [(1, 2, "def hola():\n    return 'mundo'")])
    assert memory.code_file_sha("repo", "src/a.py") == "sha1"
    assert memory.search_code("hola mundo")[0]["path"] == "src/a.py"
    memory.remove_code_files_not_in("repo", set())
    assert memory.code_file_sha("repo", "src/a.py") is None


def test_skills_lib_and_embeddings_pending():
    memory.upsert_skill("k:1", "mi-skill", "src", "/p", "hace cosas con android", "contenido android gradle", "s1")
    assert memory.search_skills("android gradle")[0]["name"] == "mi-skill"
    pend = memory.embedding_pending(10)
    assert any(p["kind"] == "skill" for p in pend)
    memory.set_embedding("skill", pend[0]["ref"], b"\x00" * 8)
    assert len(memory.embeddings_of("skill")) >= 1


def test_metrics_and_stats():
    memory.metric_add("exam_avg", 0.8)
    assert memory.metric_history("exam_avg")[-1]["value"] == 0.8
    st = memory.stats()
    assert {"knowledge", "verified", "pending", "code", "skills_lib"} <= set(st)
