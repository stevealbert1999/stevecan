import json
from stevecan import config, dataset, docs, ingest, memory, skills


def test_ingest_incremental(tmp_project):
    r1 = ingest.index_dir(tmp_project)
    assert r1["indexed"] >= 2 and r1["repo"] == "proyecto"
    r2 = ingest.index_dir(tmp_project)
    assert r2["indexed"] == 0 and r2["unchanged"] == r1["files"]
    assert not any("node_modules" in c["path"] for c in memory.rows("SELECT path FROM code_chunks WHERE repo='proyecto'"))
    r3 = ingest.index_dir(tmp_project, repo_name="docs:x")
    assert r3["repo"] == "docs:x"


def test_skills_index_search_enable(tmp_path, monkeypatch):
    lib = tmp_path / "lib" / "owner__repo" / "skills" / "mi-skill"
    lib.mkdir(parents=True)
    (lib / "SKILL.md").write_text("---\nname: mi-skill\ndescription: >-\n  hace cosas\n  con android\n---\n# cuerpo gradle apk\n")
    monkeypatch.setattr(config, "SKILLS_LIB_DIR", tmp_path / "lib")
    r = skills.index()
    assert r["skills"] == 1 and r["reindexed"] == 1
    assert skills.index()["reindexed"] == 0
    hit = skills.search("android gradle")[0]
    assert hit["name"] == "mi-skill" and hit["description"] == "hace cosas con android"
    monkeypatch.setattr(skills, "ROOT", tmp_path)
    dst = skills.enable("mi-skill")
    assert (dst / "SKILL.md").exists()


def test_docs_sources_parse():
    src = docs._sources()
    assert len(src) >= 20
    assert all(len(s) == 3 and "/" in s[1] for s in src)


def test_dataset_build_from_external(tmp_path, monkeypatch):
    ext = tmp_path / "ext"; ext.mkdir()
    (ext / "a.jsonl").write_text(json.dumps({"prompt": "¿Qué es un mutex?", "response": "Exclusión mutua."}) + "\n")
    (ext / "b.csv").write_text("prompt,response\n¿Qué es un hilo?,Unidad de ejecución.\n")
    monkeypatch.setattr(config, "DATASETS", [ext])
    out = dataset.build()
    rows = [json.loads(l) for l in out.read_text().splitlines()]
    assert len(rows) == 2 and all(r["messages"][2]["role"] == "assistant" for r in rows)
