"""Install the pinned clause Adapter without downloading base weights or loading a GPU."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
from urllib.request import urlopen
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tradepilot.artifacts import ROOT, verify_clause_adapter


def install_bundle(bundle, output, manifest):
    bundle, output = Path(bundle), Path(output)
    if output.exists():
        raise ValueError("Output already exists; choose a new directory, or use --verify-only")
    if bundle.stat().st_size != manifest["bundle_bytes"]:
        raise ValueError("Bundle size mismatch")
    with bundle.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != manifest["bundle_sha256"]:
            raise ValueError("Bundle SHA-256 mismatch")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".adapter-", dir=output.parent) as temp:
        staged = Path(temp) / "adapter"
        staged.mkdir()
        # Select named files only; never extract arbitrary archive paths or scripts.
        with ZipFile(bundle) as archive:
            for name, digest in manifest["portable_files_sha256"].items():
                if Path(name).name != name:
                    raise ValueError("Invalid artifact filename")
                data = archive.read(manifest["bundle_adapter_prefix"] + name)
                if hashlib.sha256(data).hexdigest() != digest:
                    raise ValueError("Adapter file SHA-256 mismatch: " + name)
                (staged / name).write_bytes(data)
            for name in ("MODEL_LICENSE.txt", "NOTICE_MODEL_DATA.md"):
                (staged / name).write_bytes(archive.read(manifest["bundle_root"] + name))
        verify_clause_adapter(staged)
        (staged / "tradepilot-adapter.json").write_text(json.dumps({
            "task": "cuad_clause", "weights_sha256": manifest["adapter_weights_sha256"],
            "bundle_sha256": manifest["bundle_sha256"]}, indent=2) + "\n")
        # Recheck after download/validation to avoid overwriting a new directory.
        if output.exists():
            raise ValueError("Output appeared during installation; refusing to overwrite")
        staged.rename(output)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, default=ROOT / "adapters/cuad-pilot-v1")
    p.add_argument("--bundle", type=Path, help="Use an already downloaded ZIP, with the same hash checks")
    p.add_argument("--verify-only", action="store_true")
    a = p.parse_args()
    if a.verify_only:
        verify_clause_adapter(a.output)
        print("VERIFIED: clause Adapter weights and configuration match")
        return
    manifest = json.loads((ROOT / "configs/cuad-pilot-artifact.json").read_text())
    if a.bundle:
        install_bundle(a.bundle, a.output, manifest)
    else:
        a.output.parent.mkdir(parents=True, exist_ok=True)
        if a.output.exists():
            raise ValueError("Output already exists; use --verify-only")
        if shutil.disk_usage(a.output.parent).free < 100 * 1024**2:
            raise ValueError("At least 100 MiB free storage required")
        with tempfile.TemporaryDirectory(prefix=".download-", dir=a.output.parent) as temp:
            bundle = Path(temp) / "model.zip"
            with urlopen(manifest["download_url"], timeout=60) as response, bundle.open("wb") as target:
                size = 0
                while chunk := response.read(1024**2):
                    size += len(chunk)
                    if size > manifest["bundle_bytes"]:
                        raise ValueError("Download exceeded the pinned bundle size")
                    target.write(chunk)
            install_bundle(bundle, a.output, manifest)
    print("INSTALLED_AND_VERIFIED", a.output)
    print("Run ml/predict_clause.py with your matching local base model; do not use the business --adapter option.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError) as exc:
        raise SystemExit(str(exc)) from exc
