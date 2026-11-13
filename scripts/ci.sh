#!/usr/bin/env bash
# NPOPS CI-style gate: tests, then boot check.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> Running test suite"
python3 -m unittest discover tests -p 'test_*.py'

echo "==> Boot check (in-memory, API smoke)"
python3 - <<'EOF'
import sys, json
sys.path.insert(0, ".")
from npops.api.app import create_app
from npops import seed
from npops.orm import get_db

app = create_app(":memory:")
seed.seed(get_db())

def call(method, path, body=None, cookie=None, csrf=None):
    import io
    env = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": "",
           "SERVER_NAME": "t", "SERVER_PORT": "80", "REMOTE_ADDR": "x",
           "wsgi.input": None, "CONTENT_LENGTH": "0"}
    if body is not None:
        data = json.dumps(body).encode()
        env["wsgi.input"] = io.BytesIO(data)
        env["CONTENT_LENGTH"] = str(len(data))
        env["CONTENT_TYPE"] = "application/json"
    if cookie: env["HTTP_COOKIE"] = f"npops_session={cookie}"
    if csrf: env["HTTP_X_CSRF_TOKEN"] = csrf
    return app.handle(env)

r = call("POST", "/api/auth/login", {"username": "sclaus", "password": "ho-ho-ho"})
assert r.status == 200, r.status
cookie = csrf = None
for k, v in r.headers:
    if k == "Set-Cookie" and "npops_session=" in v: cookie = v.split(";")[0].split("=", 1)[1]
    if k == "X-CSRF-Token": csrf = v
r = call("POST", "/api/plan/compute", {"year": 2026, "iterations": 1500}, cookie, csrf)
d = json.loads(r.body)
assert r.status == 200 and not d["violations"], (r.status, d.get("violations"))
print(f"    plan: {len(d['routes'])} sorties, {d['total_km']} km, feasible")
r = call("GET", "/", cookie=cookie)
assert r.status == 200
print("    UI serves")
print("==> All green")
EOF
