import importlib.util
from pathlib import Path
import pytest


def test_shared_mode_caps_only_new_usage_and_keeps_default_guard_separate(monkeypatch):
    path = Path(__file__).parents[1] / "scripts/cooperative_gpu_guard.py"
    spec = importlib.util.spec_from_file_location("cooperative_guard", path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    state = {"new": [], "free": "72992", "util": "0"}
    def query(kind, fields):
        return [["GPU-test", "81920", state["free"], state["util"]]] if kind == "gpu" else [["GPU-test", "1351978", "8142"]] + state["new"]
    monkeypatch.setattr(module, "query", query)
    assert module.inspect("GPU-test", {1351978}, startup=True)["new_process_memory_mib"] == 0
    state["util"] = "80"
    with pytest.raises(RuntimeError, match="idle"):
        module.inspect("GPU-test", {1351978}, startup=True)
    assert module.inspect("GPU-test", {1351978}, startup=True, allow_busy=True)["utilization"] == 80
    state["util"] = "0"
    state["new"] = [["GPU-test", "42", "22000"]]; state["free"] = "45000"
    assert module.inspect("GPU-test", {1351978})["new_process_memory_mib"] == 22000
    with pytest.raises(RuntimeError, match="unapproved"):
        module.inspect("GPU-test", {1351978}, startup=True)
    state["new"] = [["GPU-test", "42", "24577"]]
    with pytest.raises(RuntimeError, match="limit"):
        module.inspect("GPU-test", {1351978})
    state["new"] = [["GPU-test", "42", "22000"]]; state["free"] = "16000"
    with pytest.raises(RuntimeError, match="limit"):
        module.inspect("GPU-test", {1351978})
