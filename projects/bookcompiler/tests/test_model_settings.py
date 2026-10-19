import os
import json
from pathlib import Path

from bookcompiler import model_settings


def test_update_env_file_preserves_comments_and_applies(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("# keep me\nA=1\nBOOKCOMPILER_JUDGE_MODEL=old\n", encoding="utf-8")
    monkeypatch.delenv("BOOKCOMPILER_JUDGE_MODEL", raising=False)
    model_settings.update_env_file({"BOOKCOMPILER_JUDGE_MODEL": "qwen2.5:14b"}, path)
    text = path.read_text(encoding="utf-8")
    assert "# keep me" in text
    assert "A=1" in text
    assert "BOOKCOMPILER_JUDGE_MODEL=qwen2.5:14b" in text
    assert os.environ["BOOKCOMPILER_JUDGE_MODEL"] == "qwen2.5:14b"


def test_set_judge_default_writes_three_keys(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    monkeypatch.setattr(model_settings, "env_file_path", lambda: path)
    result = model_settings.set_judge_default("local", "qwen2.5:7b", "http://127.0.0.1:11434/")
    assert result["provider"] == "ollama"
    assert result["base_url"] == "http://127.0.0.1:11434"
    text = path.read_text(encoding="utf-8")
    assert "BOOKCOMPILER_JUDGE_PROVIDER=ollama" in text
    assert "BOOKCOMPILER_JUDGE_MODEL=qwen2.5:7b" in text


def test_set_judge_default_rejects_unknown_provider(tmp_path, monkeypatch):
    monkeypatch.setattr(model_settings, "env_file_path", lambda: tmp_path / ".env")
    try:
        model_settings.set_judge_default("magic", "x")
    except ValueError as exc:
        assert "provider" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_hermes_status_reads_model_block_and_redacts_secrets(tmp_path, monkeypatch):
    home = tmp_path / "hermes"
    home.mkdir()
    (home / "config.yaml").write_text(
        "model:\n"
        "  default: \"qwen2.5:7b\"\n"
        "  provider: \"ollama\"\n"
        "  base_url: \"http://127.0.0.1:11434/v1\"\n"
        "  api_key: \"TOP-SECRET\"\n"
        "other:\n"
        "  model: \"not-this-one\"\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("BOOKCOMPILER_HERMES_HOME", str(home))
    monkeypatch.delenv("HERMES_HOME", raising=False)
    status = model_settings.hermes_status()
    assert status["model"] == "qwen2.5:7b"
    assert status["provider"] == "ollama"
    assert status["base_url"] == "http://127.0.0.1:11434/v1"
    assert "TOP-SECRET" not in json.dumps(status, ensure_ascii=False)


def test_ollama_listing_is_soft_when_server_is_down():
    result = model_settings.list_ollama_models("http://127.0.0.1:1", timeout=0.2)
    assert result["available"] is False
    assert result["models"] == []
    assert result["error"]


def test_set_hindsight_default_writes_hindsight_env(tmp_path, monkeypatch):
    env_path = tmp_path / "hindsight.env"
    monkeypatch.setattr(model_settings, "hindsight_env_path", lambda: env_path)
    result = model_settings.set_hindsight_default("ollama", "qwen2.5:7b", "http://127.0.0.1:11434/v1")
    assert result["model"] == "qwen2.5:7b"
    text = env_path.read_text(encoding="utf-8")
    assert "HINDSIGHT_API_LLM_PROVIDER=ollama" in text
    assert "HINDSIGHT_API_LLM_MODEL=qwen2.5:7b" in text


def test_set_hermes_default_updates_only_model_block(tmp_path, monkeypatch):
    home = tmp_path / "hermes"
    home.mkdir()
    config = home / "config.yaml"
    config.write_text(
        "model:\n"
        "  default: \"old-model\"\n"
        "  provider: \"custom\"  # keep comment\n"
        "  base_url: \"https://old.example/v1\"\n"
        "other:\n"
        "  default: \"do-not-touch\"\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("BOOKCOMPILER_HERMES_HOME", str(home))
    monkeypatch.delenv("HERMES_HOME", raising=False)
    result = model_settings.set_hermes_default("new-model", "ollama", "http://127.0.0.1:11434/v1")
    text = config.read_text(encoding="utf-8")
    assert result["model"] == "new-model"
    assert 'default: "new-model"' in text
    assert 'provider: "ollama"  # keep comment' in text
    assert 'default: "do-not-touch"' in text
    assert result["backup"]


def test_switch_presets_are_isolated(tmp_path, monkeypatch):
    from bookcompiler import switch_models

    monkeypatch.setattr(switch_models, "PRESET_PATH", tmp_path / "presets.json")
    monkeypatch.setattr(switch_models, "load_presets", lambda: {
        "cloud": {
            "hermes": {"model": "cloud", "provider": "custom", "base_url": "https://api.example/v1"},
            "bookcompiler": {"model": "cloud", "provider": "openai-compatible", "base_url": "https://api.example/v1"},
            "hindsight": {"model": "local", "provider": "ollama", "base_url": "http://127.0.0.1:11434/v1"},
        }
    })
    calls = []
    monkeypatch.setattr(switch_models, "set_hermes_default", lambda **kw: calls.append(("hermes", kw)) or {"model": kw["model"]})
    monkeypatch.setattr(switch_models, "set_judge_default", lambda **kw: calls.append(("judge", kw)) or {"model": kw["model"]})
    monkeypatch.setattr(switch_models, "set_hindsight_default", lambda **kw: calls.append(("hindsight", kw)) or {"model": kw["model"]})
    monkeypatch.setattr(switch_models, "_judge_key_available", lambda provider, base_url: True)
    results = switch_models.apply_preset_data("cloud")
    assert [target for target, _ in results] == ["Hermes", "BookCompiler 盲评", "Hindsight"]
    assert calls[0][1]["model"] == "cloud"
    assert calls[2][1]["model"] == "local"
