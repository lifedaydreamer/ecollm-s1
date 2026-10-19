"""CPU-only HTTP smoke check against the user's self-hosted Docker demo."""
import argparse
import base64
import json
import os
import time
import urllib.error
import urllib.request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:3100")
    args = parser.parse_args()
    token = os.environ["TRADEPILOT_TOKEN"]
    auth = "Basic " + base64.b64encode(("tradepilot:" + token).encode()).decode()

    def request(path, method="GET", body=None, expected=200, authenticated=True):
        headers = {"Authorization": auth} if authenticated else {}
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode()
        req = urllib.request.Request(args.url.rstrip("/") + path, data=data, headers=headers, method=method)
        try:
            response = urllib.request.urlopen(req, timeout=30)
        except urllib.error.HTTPError as exc:
            response = exc
        assert response.code == expected, (path, response.code, response.read()[:200])
        raw = response.read()
        return json.loads(raw) if "application/json" in response.headers.get("Content-Type", "") else raw

    request("/", authenticated=False, expected=401)
    request("/api/cases", authenticated=False, expected=401)
    request("/")
    health = request("/api/health")
    assert health["model_configured"] is False, "CPU smoke must not call a model endpoint"
    for variant, differences, risks in [("normal", 0, 0), ("conflict", 3, 2), ("missing", 0, 0)]:
        case = request("/api/demo?variant=" + variant, "POST")
        run = request(f"/api/cases/{case['id']}/runs", "POST", expected=202)
        path = f"/api/cases/{case['id']}/runs/{run['id']}"
        for _ in range(30):
            run = request(path)
            if run["status"] not in {"queued", "running"}:
                break
            time.sleep(.5)
        assert run["status"] == "awaiting_review", run
        findings = run["findings"]
        assert sum(f["kind"] == "difference" for f in findings) == differences
        assert sum(f["kind"] == "business_risk" for f in findings) == risks
        if variant == "missing":
            assert any(f["kind"] == "missing_info" for f in findings)
        request(path + "/approve", "POST", {}, expected=409)
        for finding in findings:
            request(path + "/decisions/" + finding["id"], "POST",
                    {"action": "accept", "reason": "Synthetic smoke test only"})
        approved = request(path + "/approve", "POST", {"acknowledge_limitations": True,
                           "reason": "Synthetic deployment smoke; not a business or accuracy evaluation"})
        assert approved["status"] == "approved"
        assert request(path + "/export/pdf").startswith(b"%PDF")
        assert request(path + "/export/docx").startswith(b"PK")
        assert request(path + "/export/json")["run"]["id"] == run["id"]
        assert request(path + "/export/txt")
    print("PASS: auth, three cases, rule findings, approval gate, archive and four exports; no GPU/server dependency")


if __name__ == "__main__":
    main()
