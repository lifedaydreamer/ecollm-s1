import argparse
import importlib.util
import json
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fresh_demo_credentials_do_not_reuse_a_server_secret(tmp_path, monkeypatch):
    for key in ("TRADEPILOT_TOKEN", "TRADEPILOT_MODEL_TOKEN", "TRADEPILOT_PORT"):
        monkeypatch.delenv(key, raising=False)
    demo = load("demo")
    first = demo.credentials(tmp_path)
    assert first == demo.credentials(tmp_path)
    assert len(first["TRADEPILOT_TOKEN"]) >= 32
    assert first["TRADEPILOT_TOKEN"] != first["TRADEPILOT_MODEL_TOKEN"]
    monkeypatch.setenv("TRADEPILOT_PORT", "0")
    with pytest.raises(ValueError, match="PORT"):
        demo.credentials(tmp_path)


def test_model_configuration_requires_explicit_gpu_and_valid_paths(tmp_path):
    demo = load("demo")
    model = tmp_path / "my local weights"
    model.mkdir()
    (model / "config.json").write_text("{}")
    (model / "model.safetensors").write_bytes(b"test fixture, not real weights")
    args = argparse.Namespace(action="start", rules_only=False, model_dir=str(model), gpu="0", adapter=None)
    with pytest.raises(ValueError, match="UUID"):
        demo.model_configuration(args, tmp_path)
    args.gpu = "GPU-00000000-1111-2222-3333-444444444444"
    saved = demo.model_configuration(args, tmp_path)
    assert saved["MODEL_DIR"] == model.as_posix()
    assert saved["ADAPTER_PATH"] == ""
    args.rules_only = True
    assert demo.model_configuration(args, tmp_path) == {}


def test_preview_is_generated_from_rules_and_every_quote_is_real():
    from tradepilot.engine import evidence_valid
    preview = load("build_preview").snapshots()
    for variant, case in preview.items():
        assert case["synthetic"] and case["engine"] == "rules-only"
        assert all(evidence_valid(e, case["documents"]) for f in case["findings"] for e in f["evidence"])
    assert len(preview["conflict"]["findings"]) == 5
    assert not preview["normal"]["findings"]
    assert preview["missing"]["findings"]
