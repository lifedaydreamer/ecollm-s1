"""Portable Docker demo. No dependency on the developer's infrastructure."""
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def credentials(root=ROOT):
    path = root / ".env"
    if not path.exists():
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write("# Generated locally. Never commit this file.\n")
            stream.write(f"TRADEPILOT_TOKEN={secrets.token_urlsafe(32)}\n")
            stream.write(f"TRADEPILOT_MODEL_TOKEN={secrets.token_urlsafe(32)}\n")
            stream.write("TRADEPILOT_PORT=3100\n")
    values = {}
    for line in path.read_text().splitlines():
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip("\"'")
    for key in ("TRADEPILOT_TOKEN", "TRADEPILOT_MODEL_TOKEN", "TRADEPILOT_PORT"):
        values[key] = os.environ.get(key, values.get(key, ""))
    for key in ("TRADEPILOT_TOKEN", "TRADEPILOT_MODEL_TOKEN"):
        if not re.fullmatch(r"[A-Za-z0-9_-]{24,}", values[key]):
            raise ValueError(f"{key} must contain at least 24 URL-safe characters; use the generated value")
    if not values["TRADEPILOT_PORT"].isdigit() or not 1024 <= int(values["TRADEPILOT_PORT"]) <= 65535:
        raise ValueError("TRADEPILOT_PORT must be a port between 1024 and 65535")
    return values


def model_configuration(args, root=ROOT):
    path = root / ".runtime/demo-model.json"
    saved = json.loads(path.read_text()) if path.exists() else {}
    if args.rules_only:
        saved = {}
    elif args.model_dir:
        if not args.gpu or not re.fullmatch(r"GPU-[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", args.gpu):
            raise ValueError("Model mode requires --gpu with the complete NVIDIA GPU UUID")
        model = Path(args.model_dir).expanduser().resolve()
        if not (model / "config.json").is_file() or not any(model.glob("*.safetensors")):
            raise ValueError("--model-dir must contain config.json and local safetensors weights")
        adapter = Path(args.adapter).expanduser().resolve() if args.adapter else model
        if args.adapter and not (adapter / "adapter_config.json").is_file():
            raise ValueError("--adapter must contain adapter_config.json")
        saved = {"MODEL_DIR": model.as_posix(), "GPU_UUID": args.gpu,
                 "ADAPTER_DIR": adapter.as_posix(), "ADAPTER_PATH": "/models/adapter" if args.adapter else ""}
    elif args.gpu or args.adapter:
        raise ValueError("--gpu and --adapter require --model-dir")
    if args.action == "start":
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(saved, indent=2))
    return saved


def main():
    parser = argparse.ArgumentParser(description="Start your own TradePilot demo with Docker Compose")
    parser.add_argument("action", choices=["start", "stop", "status", "logs", "password"], nargs="?", default="start")
    parser.add_argument("--model-dir", help="Directory of local Qwen weights; never downloaded implicitly")
    parser.add_argument("--gpu", help="An explicitly allocated NVIDIA GPU UUID")
    parser.add_argument("--adapter", help="Optional locally trained PEFT Adapter directory")
    parser.add_argument("--rules-only", action="store_true", help="Switch back to the no-GPU rules baseline")
    args = parser.parse_args()
    try:
        values = credentials()
        if args.action == "password":
            print("Username: tradepilot\nPassword: " + values["TRADEPILOT_TOKEN"])
            return
        if not shutil.which("docker"):
            raise ValueError("Install and start Docker Desktop (or Docker Engine + Compose v2), then retry")
        subprocess.run(["docker", "compose", "version"], check=True, capture_output=True)
        model = model_configuration(args)
        command = ["docker", "compose", "-p", "tradepilot-demo", "-f", str(ROOT / "compose.yaml")]
        if model:
            command += ["-f", str(ROOT / "compose.model.yaml")]
        action = {"start": ["up", "--build", "--detach", "--remove-orphans", "--wait", "--wait-timeout", "600"],
                  "stop": ["down"], "status": ["ps"], "logs": ["logs", "--tail", "80"]}[args.action]
        env = {**os.environ, **values, **model, "LANGSMITH_TRACING": "false", "LANGCHAIN_TRACING_V2": "false"}
        subprocess.run(command + action, cwd=ROOT, env=env, check=True)
        if args.action == "start":
            print(f"\nOpen http://localhost:{values['TRADEPILOT_PORT']}")
            print("Username: tradepilot\nPassword: " + values["TRADEPILOT_TOKEN"])
            print("Mode: " + ("local model + rules" if model else "rules baseline (no GPU or AI inference)"))
            print("Data stays in Docker volumes. Stop with: python scripts/demo.py stop")
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"Demo could not start: {exc}\nCheck Docker, ports and: python scripts/demo.py logs\n")


if __name__ == "__main__":
    main()
