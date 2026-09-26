"""Cada sesión de tests usa un DATA_DIR temporal y un modelo inalcanzable: nada toca tus datos reales."""
import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="stevecan-tests-")
os.environ["DATA_DIR"] = _TMP
os.environ["WORKSPACE_DIR"] = os.path.join(_TMP, "workspace")
os.environ["LLM_BASE_URL"] = "http://127.0.0.1:9/v1"
os.environ["EMBED_BASE_URL"] = ""
os.environ["CODE_DIRS"] = ""
os.environ["PROJECT_DIRS"] = ""
os.environ["DATASETS"] = ""
os.environ["API_TOKEN"] = "test-token"
os.environ["API_PORT"] = "18765"

import pytest  # noqa: E402


@pytest.fixture
def tmp_project(tmp_path):
    p = tmp_path / "proyecto"
    (p / "src").mkdir(parents=True)
    (p / "src" / "a.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (p / "package.json").write_text('{"name":"proyecto","scripts":{"test":"echo no test specified"}}', encoding="utf-8")
    (p / "node_modules" / "x").mkdir(parents=True)
    (p / "node_modules" / "x" / "big.js").write_text("x", encoding="utf-8")
    return p
