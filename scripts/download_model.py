"""Download public weights to a user-selected directory, or verify existing files."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
REPO = "Qwen/Qwen3-4B-Instruct-2507"


def verify(path, manifest):
    errors = []
    for name, expected in manifest["sha256"].items():
        file = path / name
        if not file.is_file():
            errors.append(name + ": missing")
            continue
        digest = hashlib.sha256()
        with file.open("rb") as stream:
            for chunk in iter(lambda: stream.read(8 * 1024**2), b""):
                digest.update(chunk)
        if digest.hexdigest() != expected:
            errors.append(name + ": SHA-256 mismatch")
    if errors:
        raise ValueError("Weights differ from the recorded baseline:\n" + "\n".join(errors))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=["huggingface", "modelscope"], default="huggingface")
    parser.add_argument("--output", type=Path, default=ROOT / "models/Qwen3-4B-Instruct-2507")
    parser.add_argument("--revision", help="Optional upstream revision; downloaded files must still match the manifest")
    parser.add_argument("--verify-only", action="store_true", help="Hash existing files without any network access")
    args = parser.parse_args()
    path = args.output.expanduser().resolve()
    manifest = json.loads((ROOT / "configs/model-manifest.json").read_text())
    if args.verify_only:
        verify(path, manifest)
        print("VERIFIED: all recorded baseline model files match")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(path.parent).free < 50 * 1024**3:
        raise SystemExit("At least 50GiB free storage is required for weights, build cache and runtime")
    patterns = ["*.json", "*.safetensors", "*.txt", "*.model", "LICENSE*", "README.md"]
    if args.source == "modelscope":
        from modelscope.hub.api import HubApi
        from modelscope import snapshot_download
        kwargs = {"revision": args.revision} if args.revision else {}
        files = HubApi().get_model_files(REPO, recursive=True, **kwargs)
        size = sum(f.get("Size", 0) for f in files)
        if size > 12 * 1024**3:
            raise SystemExit("Model exceeds the 12GiB download budget")
        snapshot_download(REPO, local_dir=str(path), allow_file_pattern=patterns, max_workers=2, **kwargs)
        provenance = {"source": "modelscope", "repo": REPO, "requested_revision": args.revision}
    else:
        from huggingface_hub import HfApi, snapshot_download
        info = HfApi().model_info(REPO, revision=args.revision, files_metadata=True)
        size = sum(s.size or 0 for s in info.siblings if s.rfilename.endswith((".safetensors", ".json", ".txt")))
        if size > 12 * 1024**3:
            raise SystemExit("Model exceeds the 12GiB download budget")
        snapshot_download(REPO, revision=info.sha, local_dir=path, allow_patterns=patterns, max_workers=2)
        provenance = {"source": "huggingface", "repo": REPO, "revision": info.sha}
    verify(path, manifest)
    provenance["verified_sha256"] = manifest["sha256"]
    (path / "tradepilot-provenance.json").write_text(json.dumps(provenance, indent=2))
    print("DOWNLOAD_COMPLETE_AND_VERIFIED", path)


if __name__ == "__main__":
    main()
