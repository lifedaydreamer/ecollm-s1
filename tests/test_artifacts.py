import hashlib
import importlib.util
import json
from pathlib import Path
from zipfile import ZipFile
import pytest
from tradepilot import artifacts
from tradepilot.clause_task import messages


def downloader():
    spec = importlib.util.spec_from_file_location("download_adapter", Path(__file__).parents[1] / "scripts/download_adapter.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_bundle_installs_only_pinned_files_and_preserves_existing_directory(tmp_path, monkeypatch):
    module = downloader()
    config = {"peft_type": "LORA", "task_type": "CAUSAL_LM", "r": 16, "lora_alpha": 32, "target_modules": ["q_proj", "v_proj"]}
    files = {"adapter_model.safetensors": b"test-weights", "adapter_config.json": json.dumps(config).encode()}
    bundle = tmp_path / "test.zip"
    with ZipFile(bundle, "w") as z:
        for name, data in files.items(): z.writestr("bundle/adapter/" + name, data)
        z.writestr("bundle/MODEL_LICENSE.txt", "license")
        z.writestr("bundle/NOTICE_MODEL_DATA.md", "attribution")
        z.writestr("../../unrelated.txt", "must not extract")
    manifest = {"bundle_bytes": bundle.stat().st_size, "bundle_sha256": hashlib.sha256(bundle.read_bytes()).hexdigest(),
                "adapter_weights_sha256": hashlib.sha256(files["adapter_model.safetensors"]).hexdigest(),
                "portable_files_sha256": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()},
                "bundle_adapter_prefix": "bundle/adapter/", "bundle_root": "bundle/"}
    configs = tmp_path / "configs"; configs.mkdir()
    (configs / "cuad-pilot-artifact.json").write_text(json.dumps(manifest))
    monkeypatch.setattr(artifacts, "ROOT", tmp_path)
    output = tmp_path / "installed"
    module.install_bundle(bundle, output, manifest)
    assert (output / "adapter_model.safetensors").read_bytes() == b"test-weights"
    assert not (tmp_path / "unrelated.txt").exists()
    with pytest.raises(ValueError, match="already exists"):
        module.install_bundle(bundle, output, manifest)
    with pytest.raises(ValueError, match="cannot serve"):
        artifacts.reject_clause_adapter_for_business(output)
    monkeypatch.setenv("TRADEPILOT_MODEL_PATH", str(tmp_path / "unused-base"))
    monkeypatch.setenv("TRADEPILOT_MODEL_TOKEN", "test")
    monkeypatch.setenv("TRADEPILOT_ADAPTER_PATH", str(output))
    from tradepilot.model_server import app_factory
    with pytest.raises(ValueError, match="cannot serve"):
        app_factory()  # Refused before importing Torch or entering GPU lifespan.
    (output / "adapter_model.safetensors").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="mismatch"):
        artifacts.verify_clause_adapter(output)
    with pytest.raises(ValueError, match="Bundle SHA"):
        module.install_bundle(bundle, tmp_path / "other", {**manifest, "bundle_sha256": "0" * 64})
    assert not (tmp_path / "other").exists()


def test_base_and_adapter_config_are_checked_before_gpu_load(tmp_path, monkeypatch):
    configs = tmp_path / "configs"; configs.mkdir()
    manifest = {"adapter_weights_sha256": hashlib.sha256(b"weights").hexdigest()}
    (configs / "cuad-pilot-artifact.json").write_text(json.dumps(manifest))
    (configs / "model-manifest.json").write_text(json.dumps({"sha256": {"config.json": hashlib.sha256(b"base").hexdigest()}}))
    monkeypatch.setattr(artifacts, "ROOT", tmp_path)
    with pytest.raises(ValueError, match="config.json"):
        artifacts.verify_base(tmp_path)
    (tmp_path / "config.json").write_bytes(b"base")
    artifacts.verify_base(tmp_path)
    (tmp_path / "adapter_model.safetensors").write_bytes(b"weights")
    (tmp_path / "adapter_config.json").write_text(json.dumps({"r": 32}))
    with pytest.raises(ValueError, match="configuration"):
        artifacts.verify_clause_adapter(tmp_path)


@pytest.mark.parametrize("body", [{"category": "Insurance"}, {"category": "Insurance", "text": []},
                                  {"category": "Insurance", "text": " "}, {"category": "Insurance", "text": "x", "extra": True}])
def test_invalid_clause_inputs_are_rejected(body):
    with pytest.raises(ValueError): messages({"input": body})
