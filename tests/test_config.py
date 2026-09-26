import os
from stevecan import config


def test_env_sanitizes_comments_and_blanks(monkeypatch):
    monkeypatch.setenv("X_A", "valor # comentario")
    monkeypatch.setenv("X_B", "   ")
    monkeypatch.setenv("X_C", "# solo comentario")
    assert config._env("X_A") == "valor"
    assert config._env("X_B", "def") == "def"
    assert config._env("X_C", "def") == "def"
    assert config._env("X_NOPE", "d") == "d"


def test_defaults_loaded():
    assert config.LLM_PARALLEL >= 1
    assert len(config.EXPERT_DOMAINS) >= 20
    assert config.DATA_DIR.exists()
