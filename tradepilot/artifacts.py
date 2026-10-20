"""CPU-only identity checks before loading local model artifacts."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def file_sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_files(directory, expected):
    directory = Path(directory)
    for name, digest in expected.items():
        path = directory / name
        if not path.is_file() or file_sha256(path) != digest:
            raise ValueError(f"Artifact missing or SHA-256 mismatch: {name}")


def verify_base(directory):
    verify_files(directory, json.loads((ROOT / "configs/model-manifest.json").read_text())["sha256"])


def verify_clause_adapter(directory):
    manifest = json.loads((ROOT / "configs/cuad-pilot-artifact.json").read_text())
    verify_files(directory, {"adapter_model.safetensors": manifest["adapter_weights_sha256"]})
    config = json.loads((Path(directory) / "adapter_config.json").read_text())
    if (config.get("peft_type") != "LORA" or config.get("task_type") != "CAUSAL_LM"
            or config.get("r") != 16 or config.get("lora_alpha") != 32
            or set(config.get("target_modules", [])) != {"q_proj", "v_proj"}
            or config.get("modules_to_save") or config.get("rank_pattern") or config.get("alpha_pattern")
            or config.get("use_dora") or config.get("use_rslora")):
        raise ValueError("Adapter configuration differs from the recorded clause experiment")


def reject_clause_adapter_for_business(directory):
    """The pilot has a different prompt/schema from the generic business API."""
    path = Path(directory)
    manifest = json.loads((ROOT / "configs/cuad-pilot-artifact.json").read_text())
    weights = path / "adapter_model.safetensors"
    marker = path / "tradepilot-adapter.json"
    if (marker.is_file() and json.loads(marker.read_text()).get("task") == "cuad_clause") or (
            weights.is_file() and file_sha256(weights) == manifest["adapter_weights_sha256"]):
        raise ValueError("CUAD clause Adapter requires ml/predict_clause.py; it cannot serve extract/review/compare")
