#!/usr/bin/env python3
"""Smoke test: the walks validate, the player starts in view mode and serves its state, the MCP server lists its
tools, and bootstrap check runs. Uses a free port and temporary folders; never touches a running player.
Run from the repository root: python3 tests/smoke_test.py"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import bootstrap  # noqa: E402
import codewalk  # noqa: E402

results = []
TEST_DIR = ROOT / "runs" / "smoke-test"
TEST_DIR.mkdir(parents=True, exist_ok=True)


def check(name, ok, detail=""):
    results.append((name, "PASS" if ok is True else ("SKIP" if ok is None else "FAIL"), detail))


def test_port():
    requested = int(os.environ.get("CODEWALK_TEST_PORT", "0"))
    if 60777 <= requested <= 60781:
        raise ValueError("CODEWALK_TEST_PORT must not use ports 60777-60781")
    # The preferred test port can belong to another worker, or remain in TIME_WAIT.
    # Stay within the task's authorized test range; never stop an existing listener.
    candidates = range(requested, 60921) if 60900 <= requested <= 60920 else [requested]
    for candidate in candidates:
        with socket.socket() as s:
            if os.name != "nt":   # a fixed port in TIME_WAIT after the first player is still free for the next one
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", candidate))
            except OSError:
                if requested not in range(60900, 60921):
                    raise
                continue
            port = s.getsockname()[1]
        if not 60777 <= port <= 60781:
            return port
    raise OSError("No free smoke-test port in the authorized 60900-60920 range")


# the player's focus helper must ship with it: without it IDEA never follows the walk (found 2026-11-16)
check("focus helper script present", codewalk.FOCUS_SCRIPT.is_file(), str(codewalk.FOCUS_SCRIPT.relative_to(ROOT)))

for name, (rel, project, _) in bootstrap.WALKS.items():
    if project and not bootstrap.demo_ready(project):
        check(f"validate {name}", None, f"project not downloaded (python3 bootstrap.py demo {project})")
        continue
    p = ROOT / rel
    r = codewalk.validate(codewalk.load_script(p), p.parent)
    check(f"validate {name}", r["status"] == "PASS", f"{r['phrases']} phrases, {len(r['findings'])} findings")

for name, project in bootstrap.PROJECTS.items():
    folder = bootstrap.demo_root(name)
    if not folder.exists():
        check(f"{name} project is the pinned commit", None, "project not downloaded")
        continue
    got, info = bootstrap.tree_h1(folder, project["module"], project["version"]), bootstrap.demo_info(name)
    ok = bootstrap.demo_ready(name) and got == project["h1"] and info.get("commit", project["commit"]) == project["commit"]
    if (folder / ".git").exists():
        refs = [subprocess.run(["git", "-C", str(folder), "rev-parse", ref], capture_output=True, text=True, timeout=20)
                for ref in ("HEAD", project["version"] + "^{commit}")]
        ok = ok and all(r.returncode == 0 and r.stdout.strip() == project["commit"] for r in refs)
    check(f"{name} project is the pinned commit", ok,
          f"{project['commit'][:12]}, {info.get('method', 'module zip')}, {got[:16]}...")

port = test_port()
walk = "guide" if not bootstrap.demo_ready() else "demo"
with tempfile.TemporaryDirectory(dir=TEST_DIR) as tmp:
    env = {**os.environ, "CODEWALK_CACHE_DIR": str(Path(tmp) / "cache")}
    proc = subprocess.Popen([sys.executable, str(ROOT / "codewalk.py"), "serve", "--script",
                             str(ROOT / bootstrap.WALKS[walk][0]), "--port", str(port), "--view", "--answerer", "off",
                             "--positions", str(Path(tmp) / "pos"), "--run-dir", str(Path(tmp) / "run")],
                            cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        state = None
        for _ in range(40):
            try:
                with codewalk.player_urlopen(f"http://127.0.0.1:{port}/api/state", timeout=2) as response:
                    state = json.loads(response.read())
                break
            except OSError:
                time.sleep(0.25)
        ok = bool(state) and state["state"]["status"] == "idle" and state["state"]["total"] > 0
        check(f"player serves '{walk}' in view mode", ok, f"port {port}, {state and state['state']['total']} phrases")
    finally:
        proc.terminate()
        proc.wait(timeout=10)

msgs = "\n".join(json.dumps(m) for m in [
    {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                                                    "clientInfo": {"name": "smoke", "version": "1"}}},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}]) + "\n"
r = subprocess.run([sys.executable, str(ROOT / "mcp_server.py")], input=msgs, capture_output=True, text=True, timeout=30)
tools, server_version = [], None
for line in r.stdout.splitlines():
    try:
        m = json.loads(line)
    except ValueError:
        continue
    if m.get("id") == 1:
        server_version = m["result"]["serverInfo"]["version"]
    elif m.get("id") == 2:
        tools = [t["name"] for t in m["result"]["tools"]]
check("MCP server lists its tools", "codewalk_wait" in tools and "codewalk_reload" in tools
      and server_version == codewalk.VERSION, f"{len(tools)} tools, version {server_version}")

r = subprocess.run([sys.executable, str(ROOT / "bootstrap.py"), "check", "--quick"], capture_output=True, text=True,
                   timeout=120, cwd=ROOT)
check("bootstrap check runs", r.returncode in (0, 1) and "Azure Speech key file" in r.stdout, f"exit {r.returncode}")

r = subprocess.run([sys.executable, str(ROOT / "bootstrap.py"), "check", "--json", "--quick"], capture_output=True,
                   text=True, timeout=120, cwd=ROOT)
try:
    facts = json.loads(r.stdout)
    ok = ({"python", "key", "demo", "projects", "tools", "walks", "ready"} <= set(facts)
          and len(facts["walks"]) == len(bootstrap.WALKS)
          and set(facts["projects"]) == set(bootstrap.PROJECTS)
          and facts["demo"] == facts["projects"]["marketstore"]
          and all(w.get("project") == bootstrap.WALKS[w["name"]][1] for w in facts["walks"]))
except ValueError:
    facts, ok = {}, False
check("bootstrap check --json gives the facts", ok, f"{len(facts.get('walks', []))} walks")

with tempfile.TemporaryDirectory(dir=TEST_DIR) as state:
    env = {**os.environ, "CODEWALK_STATE_DIR": state}
    bport = test_port()
    r = subprocess.run([sys.executable, str(ROOT / "bootstrap.py"), "run", "guide", "--background", "--no-open",
                        "--port", str(bport)], capture_output=True, text=True, timeout=90, cwd=ROOT, env=env)
    up = "PLAYER RUNNING" in r.stdout
    r2 = subprocess.run([sys.executable, str(ROOT / "bootstrap.py"), "stop"], capture_output=True, text=True,
                        timeout=60, cwd=ROOT, env=env)
    time.sleep(1)
    try:
        with codewalk.player_urlopen(f"http://127.0.0.1:{bport}/api/state", timeout=2) as response:
            response.read()
        gone = False
    except OSError:
        gone = True
    check("background player starts and stops", up and gone and "Stopped" in r2.stdout, f"port {bport}")

for name, st, detail in results:
    print(f"{st:5} {name}  {detail}")
fails = [r for r in results if r[1] == "FAIL"]
skips = [r for r in results if r[1] == "SKIP"]
passed = sum(r[1] == "PASS" for r in results)
skip_reason = " (example projects not downloaded)" if skips else ""
print(f"{passed} passed, {len(skips)} skipped{skip_reason}, {len(fails)} failed")
sys.exit(1 if fails else 0)
