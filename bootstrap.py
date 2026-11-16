#!/usr/bin/env python3
"""Set up codewalk on this machine and start a walk.

  python3 bootstrap.py check [--json]         what is ready and what is missing (changes nothing)
  python3 bootstrap.py demo [marketstore|ignite|all] [--source auto|git|mirror|archive]
                                              get a pinned, verified example project (default: MarketStore)
  python3 bootstrap.py azure [--test]         prepare the Azure Speech key file; --test speaks one short phrase
  python3 bootstrap.py hook [--claude] [--codex] [--dry-run] [--yes]
                                              register codewalk's MCP server with your coding agent
  python3 bootstrap.py run demo|marketstore|ignite|guide|design [--port N] [--ide] [--no-open] [--background]
  python3 bootstrap.py stop                   stop a player started with --background
  python3 bootstrap.py idea [--save PATH]     find IntelliJ IDEA's launcher (so the IDE can follow the code) and save it
  python3 bootstrap.py all                    check, then ask before each step that changes something

Python 3.10+, standard library only. Nothing here reads, prints or stores your Azure key except the key file
you fill in yourself. Steps that change your machine ask first (or need --yes).
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import codewalk  # noqa: E402

DEMO = {
    "module": "github.com/alpacahq/marketstore/v4",
    "version": "v4.1.23",
    # from the Go checksum database: https://sum.golang.org/lookup/github.com/alpacahq/marketstore/v4@v4.1.23
    "h1": "h1:uU/AUfOw1NkwUg1tTcNebue4Ui1TyZeD6/ipAPVA6kE=",
    # the walks were written on exactly this commit (tag v4.1.23, 2022-11-07); the Go module mirror names it too
    "commit": "007586568aa92a1c83189b3c06843dc27a23e5b3",
    # github.com/alpacahq/marketstore is gone; these public copies of it still serve that commit by its id
    "gitSources": ["https://github.com/FluxAstromeshLabs/marketstore.git",
                   "https://github.com/hickey/marketstore.git",
                   "https://github.com/nightsuns/marketstore.git"],
    "dest": "marketstore-v4.1.23",
    "maxBytes": 20_000_000,
}
PROJECTS = {
    "marketstore": DEMO,  # DEMO and the no-argument helpers remain the MarketStore compatibility interface
    "ignite": {
        "module": "github.com/apache/ignite",
        "version": "2.17.0",
        "commit": "d53d4540b64bb4a25f1a5a1003c4338727628c9f",
        "h1": "h1:jZ4HD/ueGfzzqXXl4Wme/E4rVv1QF4l6AU0jAcUm+Sg=",
        "gitSources": ["https://github.com/apache/ignite.git"],
        "dest": "ignite-2.17.0",
        "maxBytes": 250_000_000,
    },
}
DEMO_DIR = HERE / "demo"
WALKS = {
    "demo": ("walks/marketstore-demo/demo.walk.json", "marketstore", "MarketStore, a short cut in view mode"),
    "marketstore": ("walks/marketstore/marketstore.walk.json", "marketstore", "MarketStore, the full walk with its schemas"),
    "ignite": ("walks/ignite-thin-client/ignite-thin-client.walk.json", "ignite",
               "Apache Ignite 2.17.0: the thin client, from the API to the cache and back"),
    "guide": ("walks/guide/guide.walk.json", None, "interactive guide to the player (plus your tries)"),
    "design": ("walks/codewalk-design/codewalk-design.walk.json", None, "the design of codewalk itself"),
}
AZURE_STEPS = """\
Azure Speech, free tier (F0) - what to do once:
  1. Sign in at https://portal.azure.com. You need an Azure subscription; a free account can be opened at
     https://azure.microsoft.com/free (Microsoft may ask you to verify your identity).
  2. Create a resource: search for "Speech" (Azure AI services, Speech service) and press Create.
  3. Choose a subscription, a resource group, a region (for example westus2 or westeurope), a name,
     and the pricing tier "Free F0". Create it.
  4. Open the resource, then "Keys and Endpoint". Copy KEY 1 and the Location/Region.
  5. Open the key file below in a text editor and fill in the two lines. Do not paste the key into a chat.
  6. Check it:  python3 bootstrap.py azure --test
  With the Azure CLI instead of the portal:
     az cognitiveservices account create -n <name> -g <resource-group> --kind SpeechServices --sku F0 -l <region> --yes
     az cognitiveservices account keys list -n <name> -g <resource-group>
Free tier as published by Microsoft: 0.5 million characters a month for neural voices and 20 requests per
60 seconds; codewalk keeps to that rate. The walks in this repository need about {chars} characters in all.
Terms worth knowing: Microsoft grants use rights for the audio output to paid-tier customers, and the
synthetic voice must be disclosed when you publish it. Keep free-tier audio for your own listening.
"""


# ----------------------------------------------------------------------------- helpers

def say(msg: str = ""):
    print(msg, flush=True)


def ask(question: str, yes: bool) -> bool:
    if yes:
        return True
    try:
        return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:            # no terminal (for example a coding agent): never assume yes
        say("  (no answer possible here: skipped)")
        return False


def which(name: str) -> str | None:
    return shutil.which(name)


def key_state() -> str:
    """ready | template | missing - without reading the key into any output."""
    kf = codewalk.KEY_FILE
    if not kf.exists():
        return "missing"
    vals = {}
    for line in kf.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            vals[k.strip()] = v.strip()
    key = vals.get("SPEECH_KEY", "")
    return "ready" if key and not key.startswith("<") and vals.get("SPEECH_REGION") else "template"


def module_h1(zf: zipfile.ZipFile) -> str:
    """Go's dirhash Hash1 over the files of a module zip (what go.sum and sum.golang.org record)."""
    names = sorted(n for n in zf.namelist() if not n.endswith("/"))
    summary = "".join(f"{hashlib.sha256(zf.read(n)).hexdigest()}  {n}\n" for n in names)
    return "h1:" + base64.b64encode(hashlib.sha256(summary.encode("utf-8")).digest()).decode()


def tree_files(root: Path):
    """Walk source files once, without descending into Git metadata or following directory links."""
    for directory, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d != ".git"]
        for name in files:
            if name != ".codewalk-verified":
                p = Path(directory) / name
                if p.is_file():
                    yield p


def tree_h1(root: Path, module: str | None = None, version: str | None = None) -> str:
    """The same Hash1 over a checked-out tree (without .git and the marker), as if it were the module zip."""
    prefix = f"{module or DEMO['module']}@{version or DEMO['version']}/"
    deadline = time.monotonic() + 300
    names = sorted(p.relative_to(root).as_posix() for p in tree_files(root))
    summary = hashlib.sha256()
    for name in names:
        digest = hashlib.sha256()
        with (root / name).open("rb") as f:
            while block := f.read(1024 * 1024):
                if time.monotonic() > deadline:
                    raise TimeoutError("tree verification exceeded five minutes")
                digest.update(block)
        summary.update(f"{digest.hexdigest()}  {prefix}{name}\n".encode("utf-8"))
    return "h1:" + base64.b64encode(summary.digest()).decode()


def demo_info(project: str = "marketstore") -> dict:
    """What bootstrap.py demo recorded about the demo project (commit, how it was obtained), or {}."""
    try:
        info = json.loads((demo_root(project) / ".codewalk-verified").read_text(encoding="utf-8"))
        return info if isinstance(info, dict) else {}
    except (OSError, ValueError):
        return {}


def demo_root(project: str = "marketstore") -> Path:
    return DEMO_DIR / PROJECTS[project]["dest"]


def demo_ready(project: str = "marketstore") -> bool:
    root = demo_root(project)
    info, pinned = demo_info(project), PROJECTS[project]
    # module, version and h1 must match; a marker written by an older bootstrap may lack the commit (absent or equal)
    return ((root / ("go.mod" if project == "marketstore" else "pom.xml")).is_file()
            and all(info.get(k) == pinned[k] for k in ("module", "version", "h1"))
            and info.get("commit", pinned["commit"]) == pinned["commit"])


def free_port(start: int = codewalk.DEFAULT_PORT) -> int:
    for p in range(start, start + 40):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    raise RuntimeError("no free port found")


STATE_DIR = Path(os.environ.get("CODEWALK_STATE_DIR") or HERE / "runs")   # player.json of a background player
CONFIG_FILE = codewalk.CONFIG_FILE


def walk_stats(rel: str) -> dict:
    """Phrases, spoken words, characters, how many phrases already have a clip (default voice), and the minutes:
    from the clips' real lengths once every phrase has one, else estimated (150 words a minute plus the pauses)."""
    s = json.loads(latest_version(rel)[0].read_text(encoding="utf-8"))
    texts = [ph["text"] for ch in s["chapters"] for it in ch["items"] for ph in it["phrases"]]
    words = sum(len(t.split()) for t in texts)
    gap = int(s.get("defaults", {}).get("gapMs", 700))
    secs = []
    for t in texts:
        mp3, meta = codewalk.clip_paths(t, codewalk.VOICES[0])
        try:
            if mp3.exists():
                secs.append(float(json.loads(meta.read_text(encoding="utf-8")).get("durationSec") or 0))
        except (OSError, ValueError):
            pass
    spoken = sum(secs) / 60 if len(secs) == len(texts) and all(secs) else words / 150
    return {"phrases": len(texts), "narrated": len(secs), "words": words, "characters": sum(len(t) for t in texts),
            "minutes": round(spoken + len(texts) * gap / 60000)}


def total_characters() -> int:
    return sum(walk_stats(rel)["characters"] for rel, _, _ in WALKS.values())


def background_player() -> dict | None:
    """The player started with run --background, if it still answers."""
    f = STATE_DIR / "player.json"
    try:
        info = json.loads(f.read_text(encoding="utf-8"))
        with codewalk.player_urlopen(info["url"] + "api/state", timeout=2) as response:
            response.read()
        return info
    except (OSError, ValueError, KeyError):
        return None


def idea_candidates() -> list[str]:
    """Usual places of IntelliJ IDEA's launcher on Windows, WSL, macOS and Linux (first found first)."""
    import glob  # noqa: PLC0415
    pats = []
    for base in ("C:/Program Files/JetBrains", "/mnt/c/Program Files/JetBrains"):
        pats.append(base + "/IntelliJ IDEA*/bin/idea64.exe")
    local = os.environ.get("LOCALAPPDATA")
    if local:
        pats.append(local.replace("\\", "/") + "/Programs/IntelliJ IDEA*/bin/idea64.exe")
        pats.append(local.replace("\\", "/") + "/JetBrains/Toolbox/scripts/idea.cmd")
    pats += ["/mnt/c/Users/*/AppData/Local/Programs/IntelliJ IDEA*/bin/idea64.exe",
             "/Applications/IntelliJ IDEA*.app/Contents/MacOS/idea",
             str(Path.home() / ".local/share/JetBrains/Toolbox/scripts/idea"), "/opt/idea*/bin/idea.sh",
             "/snap/bin/intellij-idea-*"]
    found = []
    for pat in pats:
        found += sorted(glob.glob(pat), reverse=True)
    for name in ("idea64.exe", "idea", "idea.sh"):
        w = which(name)
        if w:
            found.append(w)
    return list(dict.fromkeys(found))


def open_browser(url: str):
    for cmd in (["wslview", url], ["cmd.exe", "/c", "start", "", url], ["xdg-open", url], ["open", url]):
        if which(cmd[0]):
            try:
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 cwd="/mnt/c" if cmd[0] == "cmd.exe" and Path("/mnt/c").exists() else None)
                return True
            except OSError:
                continue
    return False


def mcp_registered(tool: str) -> bool | None:
    exe = which(tool)       # the full path: on Windows "claude" is claude.CMD, which cannot be started by its bare name
    if not exe:
        return None
    try:
        r = subprocess.run([exe, "mcp", "get", "codewalk"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.returncode == 0


# ----------------------------------------------------------------------------- check

def cmd_check(a) -> int:
    rows = []
    facts = {"python": {"version": ".".join(map(str, sys.version_info[:3])), "ok": sys.version_info >= (3, 10),
                        "executable": sys.executable},
             "key": {"state": key_state(), "file": str(codewalk.KEY_FILE),
                     "fromEnvironment": bool(os.environ.get("CODEWALK_KEY_FILE"))},
             "demo": {"ready": demo_ready(), "path": str(demo_root()), "version": DEMO["version"],
                      "commit": DEMO["commit"], "obtained": demo_info().get("method")},
             "tools": {t: bool(which(t)) for t in ("claude", "codex", "copilot", "ffmpeg", "ffprobe")},
             "mcp": {}, "idea": {"launcher": codewalk.IDEA_LAUNCHER, "found": Path(codewalk.IDEA_LAUNCHER).exists(),
                                 "configFile": str(CONFIG_FILE)},
             "walks": [], "player": background_player()}
    facts["projects"] = {
        name: {"ready": demo_ready(name), "path": str(demo_root(name)), "version": project["version"],
               "commit": project["commit"], "obtained": demo_info(name).get("method")}
        for name, project in PROJECTS.items()
    }

    def row(item, state, note=""):
        rows.append((item, state, note))

    v = sys.version_info
    row("Python 3.10 or newer", "OK" if v >= (3, 10) else "MISSING", f"{v.major}.{v.minor}.{v.micro}")
    missing = [f for f in ("codewalk.py", "page.html", "mcp_server.py") if not (HERE / f).exists()]
    row("player files", "MISSING" if missing else "OK", ", ".join(missing))
    row("ffprobe / ffmpeg", "OK" if which("ffprobe") and which("ffmpeg") else "OPTIONAL",
        "exact audio lengths and spoken questions; without it typed questions still work")
    ks = key_state()
    row("Azure Speech key file", {"ready": "OK", "template": "TO FILL", "missing": "MISSING"}[ks],
        f"{codewalk.KEY_FILE}  (python3 bootstrap.py azure)")
    row("demo project (MarketStore v4.1.23)", "OK" if demo_ready() else "MISSING",
        f"{demo_root()}  (python3 bootstrap.py demo)")
    row("example project (Apache Ignite 2.17.0)", "OK" if demo_ready("ignite") else "MISSING",
        f"{demo_root('ignite')}  (python3 bootstrap.py demo ignite)")
    row("claude command-line tool", "OK" if which("claude") else "OPTIONAL",
        "answers page questions; can drive the player over MCP")
    row("codex command-line tool", "OK" if which("codex") else "OPTIONAL", "can drive the player over MCP")
    for tool in ("claude", "codex"):
        reg = mcp_registered(tool) if not a.quick else None
        facts["mcp"][tool] = reg
        if reg is not None:
            row(f"MCP server registered with {tool}", "OK" if reg else "NOT YET", "python3 bootstrap.py hook")
    idea = codewalk.IDEA_LAUNCHER
    row("IntelliJ IDEA launcher", "OK" if Path(idea).exists() else "OPTIONAL",
        "the IDE follows the code; without it the page shows the code (CODEWALK_IDEA_LAUNCHER sets the path)")
    for name, (rel, project, title) in WALKS.items():
        p, version = latest_version(rel)
        st = walk_stats(rel)
        w = {"name": name, "title": title, "path": p.relative_to(HERE).as_posix(), "version": version,
             "needsDemo": bool(project), "project": project, **st}
        facts["walks"].append(w)
        if project and not demo_ready(project):
            w["status"] = "waits for the demo project" if project == "marketstore" else "waits for the Ignite project"
            row(f"walk '{name}'", "WAITS", f"needs project {project} (bootstrap.py demo {project})")
            continue
        r = codewalk.validate(codewalk.load_script(p), p.parent)
        w["status"] = "ok" if r["status"] == "PASS" else "fail"
        row(f"walk '{name}'", "OK" if r["status"] == "PASS" else "FAIL",
            f"{r['phrases']} phrases ({st['narrated']} narrated), about {st['minutes']} min" +
            (f", version {version}" if version > 1 else "") + (f", {len(r['findings'])} findings" if r["findings"] else ""))
    must = [r for r in rows if r[1] in ("MISSING", "FAIL") and r[0] in ("Python 3.10 or newer", "player files")]
    if getattr(a, "json", False):
        facts["ready"] = {"toListen": facts["key"]["state"] == "ready" and facts["demo"]["ready"],
                          "problems": [f"{r[0]}: {r[1]}" for r in rows if r[1] in ("MISSING", "FAIL", "TO FILL")]}
        print(json.dumps(facts, indent=1))
        return 1 if must else 0
    w = max(len(r[0]) for r in rows)
    for item, state, note in rows:
        say(f"  {item:<{w}}  {state:<8} {note}")
    say()
    if ks != "ready" or not demo_ready():
        say("Next: python3 bootstrap.py all   (or the single steps named above)")
    else:
        say("Ready: python3 bootstrap.py run demo")
    return 1 if must else 0


# ----------------------------------------------------------------------------- demo

def remove_tree(p: Path):
    base, target = DEMO_DIR.resolve(), p.resolve()
    if target == base or base not in target.parents:
        raise ValueError(f"refusing to remove a path outside the demo project folder: {p}")
    if p.exists():
        for directory, _, files in os.walk(p):
            for name in files:
                f = Path(directory) / name
                if not f.is_symlink():
                    f.chmod(f.stat().st_mode | stat.S_IWUSR)
        shutil.rmtree(p)


def finish_demo(tmp: Path, dest: Path, a, info: dict, project: str = "marketstore") -> int:
    """Mark the verified tree read-only, record what it is, and put it in place."""
    count = 0
    pinned = PROJECTS[project]
    for p in tree_files(tmp):
        count += 1
        if not a.writable and not p.is_symlink():
            p.chmod(p.stat().st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))   # keeps executable bits
    (tmp / ".codewalk-verified").write_text(json.dumps({"module": pinned["module"], "version": pinned["version"],
                                                        "commit": pinned["commit"], "h1": pinned["h1"], "files": count,
                                                        **info}, indent=1) + "\n", encoding="utf-8")
    remove_tree(dest)
    tmp.rename(dest)
    say(f"{count} files in {dest}" + ("" if a.writable else " (read-only)") +
        (", a git checkout of that commit" if info["method"] == "git" else ""))
    return 0


def demo_git(tmp: Path, project: str = "marketstore") -> dict | None:
    """Check out the pinned commit, without line-ending conversion; None if no source works."""
    pinned = PROJECTS[project]
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    # Use Windows' managed certificate store for the new download, without changing global Git settings.
    tls = ["-c", "http.sslBackend=schannel"] if project == "ignite" and os.name == "nt" else []
    git = lambda *args, t=180: subprocess.run(["git", "-C", str(tmp), "-c", "core.autocrlf=false", "-c", "core.eol=lf",
                                               *tls, *args], capture_output=True, text=True, timeout=t, env=env)
    for url in pinned["gitSources"]:
        remove_tree(tmp)
        tmp.mkdir(parents=True)
        try:
            if git("init", "-q").returncode:
                continue
            started = time.monotonic()
            if git("fetch", "-q", "--depth", "1", "--no-tags", url, pinned["commit"],
                   t=300 if project == "ignite" else 180).returncode:
                say(f"  {url}: no answer or no such commit")
                continue
            seconds = time.monotonic() - started
            if git("-c", "advice.detachedHead=false", "checkout", "-q", "FETCH_HEAD").returncode:
                say(f"  {url}: checkout failed")
                continue
        except (OSError, subprocess.TimeoutExpired) as e:
            say(f"  {url}: {e}")
            continue
        head = git("rev-parse", "HEAD").stdout.strip()
        if head != pinned["commit"]:
            say(f"  {url}: gave commit {head}, not {pinned['commit']}")
            continue
        if git("tag", pinned["version"], pinned["commit"]).returncode or git("config", "core.autocrlf", "false").returncode:
            continue
        git("config", "core.eol", "lf")
        with open(tmp / ".git" / "info" / "exclude", "a", encoding="utf-8") as f:
            f.write(".codewalk-verified\n")
        received = 0
        for directory, _, files in os.walk(tmp / ".git" / "objects"):
            for name in files:
                p = Path(directory) / name
                if name.endswith(".pack") or (len(p.parent.name) == 2 and len(name) == 38):
                    received += p.stat().st_size
        say(f"Checked out commit {head} ({pinned['version']}) from {url}")
        say(f"Download: {received:,} bytes of Git object payload in {seconds:.2f} s (excludes protocol overhead)")
        return {"method": "git", "source": url, "downloadBytes": received,
                "downloadSeconds": round(seconds, 3), "sizeKind": "Git object payload; excludes protocol overhead"}
    remove_tree(tmp)
    return None


def cmd_demo(a) -> int:
    project = getattr(a, "project", "marketstore")
    if project == "all":
        if a.source not in ("auto", "git"):
            say("Choose one project for --source mirror or archive; demo all supports auto or git.")
            return 1
        for name in PROJECTS:
            if cmd_demo(argparse.Namespace(**{**vars(a), "project": name})):
                return 1
        return 0
    if (project == "ignite" and a.source == "mirror") or (project == "marketstore" and a.source == "archive"):
        say("--source mirror is for MarketStore; --source archive is for Ignite.")
        return 1
    pinned, dest = PROJECTS[project], demo_root(project)
    if demo_ready(project) and not a.force:
        info = demo_info(project)
        say(f"The demo project is already there and verified: {dest} (commit {info.get('commit', '?')[:12]}, "
            f"{info.get('method', 'module zip')})")
        return 0
    tmp = DEMO_DIR / (pinned["dest"] + ".partial")
    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    use_git = a.source == "git" or (a.source == "auto" and which("git"))
    if use_git:
        label = "Apache Ignite" if project == "ignite" else "MarketStore"
        say(f"Fetching {label} {pinned['version']}, commit {pinned['commit']} (Apache-2.0), with git")
        info = demo_git(tmp, project)
        if info:
            say("Verifying the source tree (one sequential scan, five-minute limit)")
            try:
                got = tree_h1(tmp, pinned["module"], pinned["version"])
            except (OSError, TimeoutError) as e:
                remove_tree(tmp)
                say(f"Refused: tree verification failed: {e}. Nothing was kept.")
                return 1
            if got != pinned["h1"]:
                remove_tree(tmp)
                authority = "pinned tree checksum" if project == "ignite" else "Go checksum database"
                say(f"Refused: checksum {got} does not match the {authority} ({pinned['h1']}). Nothing was kept.")
                return 1
            say(f"Verified against the {'pinned tree checksum' if project == 'ignite' else 'Go checksum database'}: {got}")
            return finish_demo(tmp, dest, a, info, project)
        if a.source == "git":
            say("The download failed: none of the git sources gave that commit. Nothing was kept. Try --source " +
                ("archive." if project == "ignite" else "mirror."))
            return 1
        say("No git source gave the commit; using the " +
            ("GitHub archive instead." if project == "ignite" else "Go module mirror instead."))
    if project == "ignite":
        return demo_archive(tmp, dest, a)
    return demo_mirror(tmp, dest, a)


def demo_archive(tmp: Path, dest: Path, a) -> int:
    """GitHub's single-root source archive, checked against the very same tree pin as git."""
    pinned = PROJECTS["ignite"]
    url = f"https://github.com/apache/ignite/archive/{pinned['commit']}.zip"
    archive = DEMO_DIR / (pinned["dest"] + ".zip.partial")
    started, received = time.monotonic(), 0
    say(f"Downloading Apache Ignite {pinned['version']} (Apache-2.0) from {url}")
    try:
        remove_tree(tmp)
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "codewalk-bootstrap"}),
                                    timeout=120) as response, archive.open("wb") as output:
            while block := response.read(1024 * 1024):
                received += len(block)
                if received > pinned["maxBytes"] or time.monotonic() - started > 300:
                    raise ValueError("archive download exceeds the size or five-minute limit")
                output.write(block)
        seconds = time.monotonic() - started
        say(f"Download: {received:,} archive bytes in {seconds:.2f} s")
        with zipfile.ZipFile(archive) as zf:
            entries, tops, seen, unpacked = [], set(), set(), 0
            for member in zf.infolist():
                parts = member.filename.rstrip("/").split("/")
                if not parts or any(p in ("", ".", "..") or "\\" in p or ":" in p for p in parts):
                    raise ValueError("unsafe archive path")
                tops.add(parts[0])
                if member.is_dir():
                    continue
                if len(parts) < 2 or ".git" in parts[1:] or ".codewalk-verified" in parts[1:]:
                    raise ValueError("unexpected archive path")
                rel = PurePosixPath(*parts[1:])
                if rel in seen or stat.S_ISLNK(member.external_attr >> 16):
                    raise ValueError("duplicate path or symbolic link in archive")
                seen.add(rel); unpacked += member.file_size
                if unpacked > 1_000_000_000:
                    raise ValueError("unpacked archive exceeds one gigabyte")
                entries.append((member, rel))
            if len(tops) != 1 or not entries:
                raise ValueError("expected one top folder containing source files")
            for member, rel in entries:
                output = tmp.joinpath(*rel.parts)
                output.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, output.open("wb") as dst:
                    shutil.copyfileobj(src, dst, 1024 * 1024)
                executable = (member.external_attr >> 16) & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
                if executable:
                    output.chmod(output.stat().st_mode | executable)
        say("Verifying the source tree (one sequential scan, five-minute limit)")
        got = tree_h1(tmp, pinned["module"], pinned["version"])
        if got != pinned["h1"]:
            raise ValueError(f"checksum {got} does not match the pinned tree checksum ({pinned['h1']})")
        say(f"Verified against the pinned tree checksum: {got}")
        say(f"Commit {pinned['commit']} (pinned source tree; archive has no Git metadata)")
        return finish_demo(tmp, dest, a, {"method": "archive", "source": url, "downloadBytes": received,
                           "downloadSeconds": round(seconds, 3), "sizeKind": "archive response bytes"}, "ignite")
    except (OSError, ValueError, zipfile.BadZipFile, TimeoutError) as e:
        remove_tree(tmp)
        say(f"Refused: {e}. Nothing was kept.")
        return 1
    finally:
        archive.unlink(missing_ok=True)


def demo_mirror(tmp: Path, dest: Path, a) -> int:
    """The existing MarketStore Go-module fallback."""
    base = f"{a.proxy.rstrip('/')}/{DEMO['module']}/@v/{DEMO['version']}"
    url = base + ".zip"
    say(f"Downloading {DEMO['module']} {DEMO['version']} (Apache-2.0) from {url}")
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "codewalk-bootstrap"}),
                                    timeout=120) as r:
            data = r.read(DEMO["maxBytes"] + 1)
    except OSError as e:
        say(f"The download failed: {getattr(e, 'reason', e)}. Nothing was written. Check the network or use --proxy.")
        return 1
    if len(data) > DEMO["maxBytes"]:
        say("Refused: the download is larger than expected.")
        return 1
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        say("Refused: the download is not a zip archive. Nothing was written.")
        return 1
    got = module_h1(zf)
    if got != DEMO["h1"]:
        say(f"Refused: checksum {got} does not match the Go checksum database ({DEMO['h1']}). Nothing was written.")
        return 1
    say(f"Verified against the Go checksum database: {got}")
    try:   # the mirror also says which commit the version is; refuse a different one, accept a mirror that does not say
        with urllib.request.urlopen(urllib.request.Request(base + ".info", headers={"User-Agent": "codewalk-bootstrap"}),
                                    timeout=30) as r:
            named = (json.loads(r.read(100_000)).get("Origin") or {}).get("Hash")
    except (OSError, ValueError):
        named = None
    if named and named != DEMO["commit"]:
        say(f"Refused: the mirror says {DEMO['version']} is commit {named}, not {DEMO['commit']}. Nothing was written.")
        return 1
    say(f"Commit {DEMO['commit']}" + (" (named by the mirror)" if named else " (the mirror does not name it)"))
    prefix = f"{DEMO['module']}@{DEMO['version']}/"
    remove_tree(tmp)
    for name in zf.namelist():
        if name.endswith("/"):
            continue
        rel = name[len(prefix):] if name.startswith(prefix) else None
        if not rel or rel.startswith("/") or ".." in Path(rel).parts:
            remove_tree(tmp)
            say(f"Refused: unexpected path in the archive: {name}")
            return 1
        out = tmp / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(zf.read(name))
    return finish_demo(tmp, dest, a, {"method": "module zip", "source": url})


# ----------------------------------------------------------------------------- azure

def cmd_azure(a) -> int:
    kf = codewalk.KEY_FILE
    st = key_state()
    if st == "missing":
        kf.parent.mkdir(parents=True, exist_ok=True)
        kf.write_text("# Azure AI Speech - fill in both lines; this file stays on your machine\n"
                      "SPEECH_KEY=<paste KEY 1 here>\nSPEECH_REGION=<region, for example westus2>\n", encoding="utf-8")
        kf.chmod(stat.S_IRUSR | stat.S_IWUSR)
        say(f"Created the key file (readable by you only): {kf}")
        st = "template"
    if st == "template":
        say(AZURE_STEPS.replace("{chars}", f"{total_characters():,}"))
        say(f"Key file: {kf}")
        say("Another location: set CODEWALK_KEY_FILE to the path of your own file.")
        return 0 if not a.test else 1
    say(f"The key file is filled in: {kf}")
    if not a.test:
        return 0
    try:
        mp3, meta = codewalk.tts("codewalk is ready.", codewalk.VOICES[0])
    except Exception as e:  # noqa: BLE001 - the message names the problem, never the key
        say(f"The test failed: {e}")
        return 1
    say(f"The test worked: {meta.get('durationSec')} s of speech in {mp3}")
    return 0


# ----------------------------------------------------------------------------- hook

def cmd_hook(a) -> int:
    server = [sys.executable, str(HERE / "mcp_server.py")]
    plans = {"claude": ["claude", "mcp", "add", "codewalk", "-s", "user", "--", *server],
             "codex": ["codex", "mcp", "add", "codewalk", "--", *server]}
    wanted = [t for t in ("claude", "codex") if getattr(a, t)] or [t for t in plans if which(t)]
    if not wanted:
        say("Neither claude nor codex was found. The player works without them; questions then go unanswered")
        say("unless a session answers with: python3 codewalk.py ctl answer ...")
        return 0
    for tool in wanted:
        if not which(tool):
            say(f"{tool}: not installed - skipped")
            continue
        if mcp_registered(tool):
            say(f"{tool}: codewalk is already registered")
            continue
        say(f"{tool}: " + " ".join(plans[tool]))
        if a.dry_run:
            continue
        if not ask(f"Register codewalk's MCP server with {tool}?", a.yes):
            continue
        r = subprocess.run(plans[tool], capture_output=True, text=True, timeout=120)
        say(f"  {'done' if r.returncode == 0 else 'failed'}: {(r.stdout or r.stderr).strip()[:300]}")
    say("Page questions are answered by a short headless Claude call when the claude tool is installed")
    say("(codewalk.py serve --answerer claude, the default then). The MCP server reaches the player at")
    say(f"CODEWALK_URL (default http://127.0.0.1:{codewalk.DEFAULT_PORT}/).")
    return 0


# ----------------------------------------------------------------------------- run

def latest_version(rel: str) -> tuple[Path, int]:
    """Find the highest version, including legacy nested names such as demo.v2.v3.walk.json."""
    p = HERE / rel
    best, n = p, 1
    stem = p.name.removesuffix(".walk.json")
    pattern = re.compile(re.escape(stem) + r"(?:\.v\d+)*\.v(\d+)\.walk\.json$")
    for q in p.parent.glob("*.walk.json"):
        match = pattern.fullmatch(q.name)
        if not match and stem == "v1":  # old standalone v2.walk.json, v3.walk.json, ...
            match = re.fullmatch(r"v(\d+)\.walk\.json", q.name)
        if match:
            version = int(match.group(1))
            canonical = q.name == f"{stem}.v{version}.walk.json"
            if version > n or (version == n and canonical):
                best, n = q, version
    return best, n


def cmd_run(a) -> int:
    bundle = getattr(a, "bundle", None)
    local_root = getattr(a, "project_root", None)
    if bundle:
        from bundles import prepare_bundle
        if a.walk or a.original:
            say("Choose --bundle or a built-in walk; --original applies only to built-in walks.")
            return 1
        if a.ide and not local_root:
            say("Bundle IDEA follow needs --project-root pointing at the matching local project.")
            return 1
        try:
            prepared = prepare_bundle(bundle, local_root)
        except (ValueError, OSError) as error:
            say(f"Bundle refused: {error}")
            return 1
        script = prepared["script"]
        local_root = str(prepared["root"])
        version, title = prepared["manifest"]["walk"]["version"], prepared["manifest"]["walk"]["title"]
        rel = str(script)
    else:
        if not a.walk or local_root:
            say("Choose a walk, or use --bundle <zip> [--project-root <project>].")
            return 1
        rel, project, title = WALKS[a.walk]
        script, version = (HERE / rel, 1) if a.original else latest_version(rel)
        if project and not demo_ready(project):
            say("This walk needs the demo project first: python3 bootstrap.py demo" if project == "marketstore" else
                "This walk needs Apache Ignite 2.17.0 first: python3 bootstrap.py demo ignite")
            return 1
    if key_state() != "ready":
        say("Note: no Azure key yet, so the walk can be read but not heard (python3 bootstrap.py azure).")
    running = background_player()
    if a.background and running:
        say(f"A player is already running in the background ({running['walk']}): {running['url']}")
        say("Stop it first with: bootstrap.py stop")
        return 1
    port = a.port or free_port()
    with socket.socket() as probe:
        if os.name != "nt":   # like the player (allow_reuse_address); on Windows this flag would allow a real clash
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            say(f"Cannot start the player: port {port} is already in use. Choose another --port.")
            return 1
    if version > 1:
        say(f"Using the amended version {version}: {script.name}" + ("" if bundle else " (--original starts version 1)"))
    cmd = [sys.executable, str(HERE / "codewalk.py"), "serve", "--script", str(script), "--port", str(port)]
    if local_root:
        cmd.extend(["--project-root", local_root])
    if bundle:
        cmd.extend(["--voice", prepared["manifest"]["voice"]])
    if a.walk == "demo":
        cmd.append("--view")
        if a.ide:
            say("The demo runs in view mode; --ide is ignored and the page shows the code.")
    elif not a.ide:
        cmd.append("--no-ide")
    say(f"Starting: {title} (about {walk_stats(rel)['minutes']} min)")
    log_path = STATE_DIR / "player.log" if a.background else None
    log = None
    diagnostic = f"See the log: {log_path}" if log_path else "See the terminal output above."
    try:
        if a.background:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            log = open(log_path, "a", encoding="utf-8")
            kw = {"cwd": HERE, "stdin": subprocess.DEVNULL, "stdout": log, "stderr": subprocess.STDOUT}
            if os.name == "nt":
                kw["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                kw["start_new_session"] = True
            proc = subprocess.Popen(cmd, **kw)
        else:
            proc = subprocess.Popen(cmd, cwd=HERE)
    except OSError as e:
        say(f"The player could not start: {e}. {diagnostic}")
        return 1
    finally:
        if log:
            log.close()  # the child has its own handle
    url = f"http://127.0.0.1:{port}/"
    ready, deadline = False, time.monotonic() + 30
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            say(f"The player exited before answering at {url}. {diagnostic}")
            return 1
        try:
            with codewalk.player_urlopen(url + "api/state", timeout=2) as response:
                response.read()
            ready = proc.poll() is None
            break
        except OSError:
            time.sleep(0.5)
    if not ready:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        say(f"The player did not answer at {url} within 30 seconds. {diagnostic}")
        return 1
    say(f"Open {url} and press Play." + ("" if a.no_open or not open_browser(url) else " (opened in your browser)"))
    if a.background:
        info = {"pid": proc.pid, "url": url, "walk": a.walk or f"bundle:{prepared['manifest']['walk']['id']}", "port": port, "log": str(STATE_DIR / "player.log"),
                "startedAt": time.strftime("%Y-%m-%dT%H:%M:%S")}
        (STATE_DIR / "player.json").write_text(json.dumps(info, indent=1) + "\n", encoding="utf-8")
        say(f"PLAYER RUNNING: {url} (in the background, pid {proc.pid}). Stop it with: bootstrap.py stop")
        return 0
    say("Stop the player with Ctrl+C.")
    try:
        return proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        return 0


def cmd_stop(a) -> int:
    f = STATE_DIR / "player.json"
    try:
        info = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        say("No background player was started from this folder.")
        return 0
    pid = int(info["pid"])
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    else:
        import signal  # noqa: PLC0415
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    f.unlink(missing_ok=True)
    say(f"Stopped the background player (pid {pid}, {info.get('url')}).")
    return 0


# ----------------------------------------------------------------------------- idea

def cmd_idea(a) -> int:
    if a.save:
        path = a.save
        if not Path(path).exists():
            say(f"Not found: {path}")
            return 1
        cfg = codewalk.read_config()
        cfg["ideaLauncher"] = path
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(cfg, indent=1) + "\n", encoding="utf-8")
        say(f"Saved the IDEA launcher in {CONFIG_FILE}: {path}")
        say("Use it with: bootstrap.py run <walk> --ide")
        return 0
    say(f"Launcher in use now: {codewalk.IDEA_LAUNCHER} ({'found' if Path(codewalk.IDEA_LAUNCHER).exists() else 'not found'})")
    found = idea_candidates()
    if not found:
        say("No IntelliJ IDEA launcher found in the usual places. Without it the page shows the code itself.")
        return 0
    say("Launchers found (save one with: bootstrap.py idea --save <path>):")
    for f in found:
        say(f"  {f}")
    return 0


# ----------------------------------------------------------------------------- all

def cmd_all(a) -> int:
    cmd_check(argparse.Namespace(quick=False, json=False))
    say()
    if not demo_ready() and ask("Fetch the demo project (MarketStore v4.1.23, about 1 MB, verified)?", a.yes):
        if cmd_demo(argparse.Namespace(force=False, writable=False, proxy=a.proxy, source="auto")):
            return 1
    if key_state() != "ready" and ask("Prepare the Azure Speech key file and show the free-tier steps?", a.yes):
        cmd_azure(argparse.Namespace(test=False))
    if (which("claude") or which("codex")) and ask("Register codewalk's MCP server with your coding agent?", a.yes):
        cmd_hook(argparse.Namespace(claude=False, codex=False, dry_run=False, yes=a.yes))
    say()
    say("Then: python3 bootstrap.py run demo   (also: run guide, run design, run marketstore, run ignite)")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="sub", required=True)
    c = sub.add_parser("check"); c.add_argument("--quick", action="store_true", help="skip the MCP registry checks")
    c.add_argument("--json", action="store_true", help="machine-readable facts for a coding agent")
    c.set_defaults(fn=cmd_check)
    d = sub.add_parser("demo"); d.add_argument("--force", action="store_true")
    d.add_argument("project", nargs="?", choices=[*PROJECTS, "all"], default="marketstore")
    d.add_argument("--writable", action="store_true", help="leave the demo files writable")
    d.add_argument("--proxy", default=os.environ.get("CODEWALK_GOPROXY", "https://proxy.golang.org"))
    d.add_argument("--source", choices=["auto", "git", "mirror", "archive"], default="auto",
                   help="auto: pinned git checkout, then MarketStore's Go mirror or Ignite's GitHub archive; "
                        "git forces git, mirror is MarketStore-only, archive is Ignite-only")
    d.set_defaults(fn=cmd_demo)
    z = sub.add_parser("azure"); z.add_argument("--test", action="store_true"); z.set_defaults(fn=cmd_azure)
    h = sub.add_parser("hook"); h.add_argument("--claude", action="store_true"); h.add_argument("--codex", action="store_true")
    h.add_argument("--dry-run", action="store_true"); h.add_argument("--yes", action="store_true")
    h.set_defaults(fn=cmd_hook)
    r = sub.add_parser("run"); r.add_argument("walk", choices=list(WALKS), nargs="?"); r.add_argument("--port", type=int)
    r.add_argument("--bundle", help="play an exported .codewalk.zip bundle")
    r.add_argument("--project-root", help="matching local project for a bundle; required for bundle IDEA follow")
    r.add_argument("--original", action="store_true", help="start version 1 even if the walk was amended")
    r.add_argument("--ide", action="store_true", help="let IntelliJ IDEA follow the code")
    r.add_argument("--no-open", action="store_true", help="do not open the browser")
    r.add_argument("--background", action="store_true", help="start the player detached and return its address")
    r.set_defaults(fn=cmd_run)
    sub.add_parser("stop").set_defaults(fn=cmd_stop)
    i = sub.add_parser("idea"); i.add_argument("--save", metavar="PATH"); i.set_defaults(fn=cmd_idea)
    al = sub.add_parser("all"); al.add_argument("--yes", action="store_true")
    al.add_argument("--proxy", default=os.environ.get("CODEWALK_GOPROXY", "https://proxy.golang.org"))
    al.set_defaults(fn=cmd_all)
    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
