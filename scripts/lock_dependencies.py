import importlib.metadata as metadata
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
import tomllib
import sys
from pathlib import Path

root=Path(__file__).resolve().parents[1]
project=tomllib.loads((root/"pyproject.toml").read_text())["project"]
model="--model" in sys.argv
pending=project["optional-dependencies"]["model"]+["fastapi","uvicorn","httpx"] if model else project["dependencies"]+project["optional-dependencies"]["production"]+project["optional-dependencies"]["test"]
selected={}
seen=set()
while pending:
    req=Requirement(pending.pop())
    if req.marker and not any(req.marker.evaluate({"extra":e}) for e in (req.extras or [""])):continue
    name=canonicalize_name(req.name)
    key=(name,tuple(sorted(req.extras)))
    if key in seen:continue
    seen.add(key)
    dist=metadata.distribution(req.name)
    selected[name]=dist.version
    for child in dist.requires or []:
        child_req=Requirement(child)
        if not child_req.marker or any(child_req.marker.evaluate({"extra":e}) for e in (req.extras or [""])):
            child_req.marker=None
            pending.append(str(child_req))
(root/("model-requirements.lock" if model else "requirements.lock")).write_text("# Resolved runtime, including inherited dependencies\n"+"\n".join(f"{name}=={v}" for name,v in sorted(selected.items()))+"\n")
print("Locked",len(selected),"distributions")
