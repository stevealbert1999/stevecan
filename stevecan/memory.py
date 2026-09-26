"""Memoria persistente compartida (SQLite + FTS5)."""
import json
import sqlite3
import threading
import time
from . import config

_lock = threading.RLock()
_conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
_conn.row_factory = sqlite3.Row
_conn.executescript("""
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS knowledge(
  id INTEGER PRIMARY KEY, topic TEXT NOT NULL, content TEXT NOT NULL,
  source TEXT, agent TEXT, confidence REAL DEFAULT 0.5,
  verified INTEGER DEFAULT 0, created REAL, updated REAL);
CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
  topic, content, content='knowledge', content_rowid='id');
CREATE TRIGGER IF NOT EXISTS k_ai AFTER INSERT ON knowledge BEGIN
  INSERT INTO knowledge_fts(rowid, topic, content) VALUES (new.id, new.topic, new.content); END;
CREATE TRIGGER IF NOT EXISTS k_ad AFTER DELETE ON knowledge BEGIN
  INSERT INTO knowledge_fts(knowledge_fts, rowid, topic, content) VALUES('delete', old.id, old.topic, old.content); END;
CREATE TRIGGER IF NOT EXISTS k_au AFTER UPDATE ON knowledge BEGIN
  INSERT INTO knowledge_fts(knowledge_fts, rowid, topic, content) VALUES('delete', old.id, old.topic, old.content);
  INSERT INTO knowledge_fts(rowid, topic, content) VALUES (new.id, new.topic, new.content); END;
CREATE TABLE IF NOT EXISTS tasks(
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL,
  priority INTEGER DEFAULT 5, status TEXT DEFAULT 'pending',
  created_by TEXT, taken_by TEXT, result TEXT, created REAL, updated REAL);
CREATE INDEX IF NOT EXISTS tasks_kind_status ON tasks(kind, status, priority);
CREATE TABLE IF NOT EXISTS exams(
  id INTEGER PRIMARY KEY, topic TEXT, question TEXT, expected TEXT,
  answer TEXT, score REAL, created REAL);
CREATE TABLE IF NOT EXISTS code_chunks(
  id INTEGER PRIMARY KEY, repo TEXT NOT NULL, path TEXT NOT NULL, chunk INTEGER NOT NULL,
  start_line INTEGER, end_line INTEGER, content TEXT NOT NULL, sha TEXT, updated REAL);
CREATE UNIQUE INDEX IF NOT EXISTS code_chunks_key ON code_chunks(repo, path, chunk);
CREATE VIRTUAL TABLE IF NOT EXISTS code_fts USING fts5(
  path, content, content='code_chunks', content_rowid='id');
CREATE TRIGGER IF NOT EXISTS c_ai AFTER INSERT ON code_chunks BEGIN
  INSERT INTO code_fts(rowid, path, content) VALUES (new.id, new.path, new.content); END;
CREATE TRIGGER IF NOT EXISTS c_ad AFTER DELETE ON code_chunks BEGIN
  INSERT INTO code_fts(code_fts, rowid, path, content) VALUES('delete', old.id, old.path, old.content); END;
CREATE TABLE IF NOT EXISTS code_files(
  repo TEXT NOT NULL, path TEXT NOT NULL, sha TEXT, summary TEXT, updated REAL, PRIMARY KEY(repo, path));
CREATE TABLE IF NOT EXISTS katas(
  id INTEGER PRIMARY KEY, domain TEXT, title TEXT, difficulty INTEGER, passed INTEGER,
  seconds REAL, attempts INTEGER, path TEXT, created REAL);
CREATE TABLE IF NOT EXISTS skills_lib(
  id INTEGER PRIMARY KEY, key TEXT UNIQUE NOT NULL, name TEXT, source TEXT, path TEXT,
  description TEXT, content TEXT, sha TEXT, updated REAL);
CREATE VIRTUAL TABLE IF NOT EXISTS skills_fts USING fts5(
  name, description, content, content='skills_lib', content_rowid='id');
CREATE TRIGGER IF NOT EXISTS s_ai AFTER INSERT ON skills_lib BEGIN
  INSERT INTO skills_fts(rowid, name, description, content) VALUES (new.id, new.name, new.description, new.content); END;
CREATE TRIGGER IF NOT EXISTS s_ad AFTER DELETE ON skills_lib BEGIN
  INSERT INTO skills_fts(skills_fts, rowid, name, description, content) VALUES('delete', old.id, old.name, old.description, old.content); END;
CREATE TRIGGER IF NOT EXISTS s_au AFTER UPDATE ON skills_lib BEGIN
  INSERT INTO skills_fts(skills_fts, rowid, name, description, content) VALUES('delete', old.id, old.name, old.description, old.content);
  INSERT INTO skills_fts(rowid, name, description, content) VALUES (new.id, new.name, new.description, new.content); END;
CREATE TABLE IF NOT EXISTS lessons(
  id INTEGER PRIMARY KEY, agent TEXT, domain TEXT, lesson TEXT NOT NULL, evidence TEXT, weight REAL DEFAULT 1.0, created REAL);
CREATE VIRTUAL TABLE IF NOT EXISTS lessons_fts USING fts5(domain, lesson, content='lessons', content_rowid='id');
CREATE TRIGGER IF NOT EXISTS l_ai AFTER INSERT ON lessons BEGIN
  INSERT INTO lessons_fts(rowid, domain, lesson) VALUES (new.id, new.domain, new.lesson); END;
CREATE TRIGGER IF NOT EXISTS l_ad AFTER DELETE ON lessons BEGIN
  INSERT INTO lessons_fts(lessons_fts, rowid, domain, lesson) VALUES('delete', old.id, old.domain, old.lesson); END;
CREATE TABLE IF NOT EXISTS embeddings(
  kind TEXT NOT NULL, ref INTEGER NOT NULL, vec BLOB NOT NULL, created REAL, PRIMARY KEY(kind, ref));
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY, agent TEXT, kind TEXT, detail TEXT, created REAL);
""")


def _q(sql, args=()):
    with _lock:
        cur = _conn.execute(sql, args)
        _conn.commit()
        return cur


def log_event(agent, kind, detail=""):
    _q("INSERT INTO events(agent,kind,detail,created) VALUES(?,?,?,?)",
       (agent, kind, detail[:2000], time.time()))


# ---- tareas -------------------------------------------------------------
def add_task(kind, payload: dict, created_by, priority=5):
    key = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    dup = _q("SELECT id FROM tasks WHERE kind=? AND payload=? AND status IN ('pending','running')",
             (kind, key)).fetchone()
    if dup:
        return dup["id"]
    return _q("INSERT INTO tasks(kind,payload,priority,created_by,created,updated) VALUES(?,?,?,?,?,?)",
              (kind, key, priority, created_by, time.time(), time.time())).lastrowid


def take_task(kind, agent):
    with _lock:
        row = _q("SELECT * FROM tasks WHERE kind=? AND status='pending' ORDER BY priority, id LIMIT 1",
                 (kind,)).fetchone()
        if not row:
            return None
        _q("UPDATE tasks SET status='running', taken_by=?, updated=? WHERE id=?",
           (agent, time.time(), row["id"]))
        return {"id": row["id"], "kind": kind, "payload": json.loads(row["payload"])}


def finish_task(task_id, result="", status="done"):
    _q("UPDATE tasks SET status=?, result=?, updated=? WHERE id=?",
       (status, str(result)[:4000], time.time(), task_id))


def requeue_stale(max_age=1800):
    return _q("UPDATE tasks SET status='pending' WHERE status='running' AND updated<?",
              (time.time() - max_age,)).rowcount


def pending_counts():
    return {r["kind"]: r["n"] for r in
            _q("SELECT kind, COUNT(*) n FROM tasks WHERE status='pending' GROUP BY kind")}


# ---- conocimiento -------------------------------------------------------
def add_knowledge(topic, content, source, agent, confidence=0.5):
    now = time.time()
    return _q("INSERT INTO knowledge(topic,content,source,agent,confidence,created,updated) VALUES(?,?,?,?,?,?,?)",
              (topic.strip(), content.strip(), source, agent, confidence, now, now)).lastrowid


def update_knowledge(kid, content=None, confidence=None, verified=None):
    sets, args = ["updated=?"], [time.time()]
    if content is not None:
        sets.append("content=?"); args.append(content)
    if confidence is not None:
        sets.append("confidence=?"); args.append(confidence)
    if verified is not None:
        sets.append("verified=?"); args.append(int(verified))
    args.append(kid)
    _q(f"UPDATE knowledge SET {', '.join(sets)} WHERE id=?", args)


def delete_knowledge(kid):
    _q("DELETE FROM knowledge WHERE id=?", (kid,))


def search(query, limit=8):
    q = " OR ".join(f'"{w}"' for w in query.replace('"', " ").split()[:12])
    if not q:
        return []
    return [dict(r) for r in _q(
        "SELECT k.* FROM knowledge_fts f JOIN knowledge k ON k.id=f.rowid WHERE knowledge_fts MATCH ? "
        "ORDER BY bm25(knowledge_fts) LIMIT ?", (q, limit))]


# ---- código propio -------------------------------------------------------
def code_file_sha(repo, path):
    r = _q("SELECT sha FROM code_files WHERE repo=? AND path=?", (repo, path)).fetchone()
    return r["sha"] if r else None


def replace_code_file(repo, path, sha, chunks):
    """chunks: lista de (start_line, end_line, content). Sustituye el fichero completo."""
    with _lock:
        _q("DELETE FROM code_chunks WHERE repo=? AND path=?", (repo, path))
        for i, (a, b, content) in enumerate(chunks):
            _q("INSERT INTO code_chunks(repo,path,chunk,start_line,end_line,content,sha,updated) VALUES(?,?,?,?,?,?,?,?)",
               (repo, path, i, a, b, content, sha, time.time()))
        _q("INSERT INTO code_files(repo,path,sha,summary,updated) VALUES(?,?,?,NULL,?) "
           "ON CONFLICT(repo,path) DO UPDATE SET sha=excluded.sha, summary=NULL, updated=excluded.updated",
           (repo, path, sha, time.time()))


def remove_code_files_not_in(repo, keep_paths):
    with _lock:
        for r in _q("SELECT path FROM code_files WHERE repo=?", (repo,)).fetchall():
            if r["path"] not in keep_paths:
                _q("DELETE FROM code_chunks WHERE repo=? AND path=?", (repo, r["path"]))
                _q("DELETE FROM code_files WHERE repo=? AND path=?", (repo, r["path"]))


def set_code_summary(repo, path, summary):
    _q("UPDATE code_files SET summary=? WHERE repo=? AND path=?", (summary, repo, path))


def code_files_without_summary(limit=5):
    return [dict(r) for r in _q("SELECT repo, path FROM code_files WHERE summary IS NULL ORDER BY updated LIMIT ?", (limit,))]


def code_file_text(repo, path):
    return "\n".join(r["content"] for r in
                     _q("SELECT content FROM code_chunks WHERE repo=? AND path=? ORDER BY chunk", (repo, path)))


def search_code(query, limit=8):
    q = " OR ".join(f'"{w}"' for w in query.replace('"', " ").split()[:12])
    if not q:
        return []
    return [dict(r) for r in _q(
        "SELECT c.* FROM code_fts f JOIN code_chunks c ON c.id=f.rowid WHERE code_fts MATCH ? "
        "ORDER BY bm25(code_fts) LIMIT ?", (q, limit))]


def code_stats():
    return {r["repo"]: {"files": r["files"], "summarized": r["summarized"]} for r in _q(
        "SELECT repo, COUNT(*) files, SUM(summary IS NOT NULL) summarized FROM code_files GROUP BY repo")}


# ---- biblioteca de skills ------------------------------------------------
def skill_sha(key):
    r = _q("SELECT sha FROM skills_lib WHERE key=?", (key,)).fetchone()
    return r["sha"] if r else None


def upsert_skill(key, name, source, path, description, content, sha):
    _q("INSERT INTO skills_lib(key,name,source,path,description,content,sha,updated) VALUES(?,?,?,?,?,?,?,?) "
       "ON CONFLICT(key) DO UPDATE SET name=excluded.name, source=excluded.source, path=excluded.path, "
       "description=excluded.description, content=excluded.content, sha=excluded.sha, updated=excluded.updated",
       (key, name, source, path, description, content, sha, time.time()))


def remove_skills_not_in(keys):
    for r in _q("SELECT key FROM skills_lib").fetchall():
        if r["key"] not in keys:
            _q("DELETE FROM skills_lib WHERE key=?", (r["key"],))


def search_skills(query, limit=8):
    q = " OR ".join(f'"{w}"' for w in query.replace('"', " ").split()[:12])
    if not q:
        return []
    return [dict(r) for r in _q(
        "SELECT s.id, s.key, s.name, s.source, s.path, s.description, substr(s.content,1,4000) content "
        "FROM skills_fts f JOIN skills_lib s ON s.id=f.rowid WHERE skills_fts MATCH ? "
        "ORDER BY bm25(skills_fts, 5.0, 3.0, 1.0) LIMIT ?", (q, limit))]


# ---- lecciones (aprender de los errores) ----------------------------------
def add_lesson(agent, domain, lesson, evidence=""):
    dup = _q("SELECT id FROM lessons WHERE lesson=?", (lesson.strip(),)).fetchone()
    if dup:
        _q("UPDATE lessons SET weight=weight+1 WHERE id=?", (dup["id"],))
        return dup["id"]
    return _q("INSERT INTO lessons(agent,domain,lesson,evidence,created) VALUES(?,?,?,?,?)",
              (agent, domain, lesson.strip(), evidence[:2000], time.time())).lastrowid


def top_lessons(query, limit=5):
    q = " OR ".join(f'"{w}"' for w in query.replace('"', " ").split()[:12])
    rows_ = []
    if q:
        rows_ = [dict(r) for r in _q(
            "SELECT l.* FROM lessons_fts f JOIN lessons l ON l.id=f.rowid WHERE lessons_fts MATCH ? "
            "ORDER BY bm25(lessons_fts) LIMIT ?", (q, limit))]
    if len(rows_) < limit:
        seen = {r["id"] for r in rows_}
        rows_ += [dict(r) for r in _q("SELECT * FROM lessons ORDER BY weight DESC, id DESC LIMIT ?", (limit,)) if r["id"] not in seen][:limit - len(rows_)]
    return rows_


# ---- embeddings -------------------------------------------------------------
def embedding_pending(limit=200):
    out = []
    for r in _q("SELECT k.id, k.topic, k.content FROM knowledge k LEFT JOIN embeddings e ON e.kind='knowledge' AND e.ref=k.id "
                "WHERE e.ref IS NULL LIMIT ?", (limit,)):
        out.append({"kind": "knowledge", "ref": r["id"], "text": f"{r['topic']}\n{r['content']}"})
    for r in _q("SELECT c.id, c.path, c.content FROM code_chunks c LEFT JOIN embeddings e ON e.kind='code' AND e.ref=c.id "
                "WHERE e.ref IS NULL LIMIT ?", (max(0, limit - len(out)),)):
        out.append({"kind": "code", "ref": r["id"], "text": f"{r['path']}\n{r['content']}"})
    for r in _q("SELECT s.id, s.name, s.description, s.content FROM skills_lib s LEFT JOIN embeddings e ON e.kind='skill' AND e.ref=s.id "
                "WHERE e.ref IS NULL LIMIT ?", (max(0, limit - len(out)),)):
        out.append({"kind": "skill", "ref": r["id"], "text": f"{r['name']}\n{r['description']}\n{r['content'][:3000]}"})
    return out


def set_embedding(kind, ref, vec):
    _q("INSERT OR REPLACE INTO embeddings(kind,ref,vec,created) VALUES(?,?,?,?)", (kind, ref, vec, time.time()))


def embeddings_of(kind):
    return _q("SELECT ref, vec FROM embeddings WHERE kind=?", (kind,)).fetchall()


def by_ids(table, ids):
    if not ids:
        return []
    marks = ",".join("?" * len(ids))
    rows_ = {r["id"]: dict(r) for r in _q(f"SELECT * FROM {table} WHERE id IN ({marks})", tuple(ids))}
    return [rows_[i] for i in ids if i in rows_]


def rows(sql, args=()):
    return [dict(r) for r in _q(sql, args)]


def stats():
    return {
        "knowledge": _q("SELECT COUNT(*) n FROM knowledge").fetchone()["n"],
        "verified": _q("SELECT COUNT(*) n FROM knowledge WHERE verified=1").fetchone()["n"],
        "topics": _q("SELECT COUNT(DISTINCT topic) n FROM knowledge").fetchone()["n"],
        "exams": _q("SELECT COUNT(*) n, AVG(score) avg FROM exams").fetchone()["n"],
        "exam_avg": _q("SELECT AVG(score) avg FROM exams").fetchone()["avg"],
        "pending": pending_counts(),
        "code": code_stats(),
        "skills_lib": _q("SELECT COUNT(*) n FROM skills_lib").fetchone()["n"],
        "katas": _q("SELECT COUNT(*) n, AVG(passed) pass_rate, AVG(seconds) avg_s FROM katas").fetchone()["n"],
        "kata_pass_rate": _q("SELECT AVG(passed) r FROM katas").fetchone()["r"],
        "kata_avg_seconds": _q("SELECT AVG(seconds) s FROM katas WHERE passed=1").fetchone()["s"],
    }
