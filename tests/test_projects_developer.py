from pathlib import Path
from stevecan import config, developer, projects


def test_backup_restore_roundtrip(tmp_project):
    a1 = projects.backup(tmp_project, "test")
    a2 = projects.backup(tmp_project, "test")
    assert a1 != a2 and a1.exists() and a2.exists()
    (tmp_project / "src" / "a.py").write_text("def f():\n    return 2\n")
    (tmp_project / "package.json").unlink()
    projects.restore(a1)
    assert (tmp_project / "src" / "a.py").read_text() == "def f():\n    return 1\n"
    assert (tmp_project / "package.json").exists()
    listed = projects.list_backups(tmp_project)
    assert len(listed) >= 3  # 2 manuales + pre-restore
    assert all(Path(b["archive"]).exists() for b in listed)
    import tarfile
    with tarfile.open(a1) as tar:
        assert not any("node_modules" in m.name for m in tar.getmembers())


def test_detect_tests_and_syntax(tmp_project):
    assert projects.detect_test_cmd(tmp_project) is None  # "no test specified"
    (tmp_project / "tests").mkdir()
    assert "pytest" in projects.detect_test_cmd(tmp_project)
    (tmp_project / "src" / "bad.py").write_text("def (:\n")
    errs = projects.syntax_check(tmp_project, ["src/bad.py", "src/a.py"])
    assert len(errs) == 1 and errs[0].startswith("src/bad.py")


def test_developer_git_plumbing(tmp_project):
    branch = developer.ensure_git(tmp_project)
    assert projects.is_git(tmp_project) and branch
    wt = config.WORKTREES_DIR / "t-test"
    code, _, err = developer._git(tmp_project, "worktree", "add", "-q", "-b", "stevecan/test", str(wt), "HEAD")
    assert code == 0, err
    rep = developer._finish({"project": str(tmp_project), "instruction": "prueba", "ts": "t", "ok": False, "reason": "x"},
                            tmp_project, wt, "stevecan/test", keep_branch=False)
    assert rep["ok"] is False and not wt.exists()
    assert developer._git(tmp_project, "rev-parse", "--verify", "stevecan/test")[0] != 0
    assert (config.IMPROVEMENTS_DIR / "proyecto-t.md").exists()
