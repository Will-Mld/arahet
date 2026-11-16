#!/usr/bin/env python3
"""codewalk - narrated, interruptible walks through code and diagrams.

Subcommands
  validate --script S [--project-root P]   check the script and every code pointer against the project
  outline  --script S [--out F]             readable text of a walk
  tts      --script S [--voices]            pre-synthesise phrase audio with Azure Speech (cached)
  serve    --script S [--port] [--view]     run the player server + page (127.0.0.1 only)
  amend    --script S --patch P             apply a patch -> next version of the script + change log
  ctl      CMD [...]                        control a running player from the command line (source "cli")

Python 3.10+ standard library only. ffprobe (ffmpeg) is used when present: for exact audio durations and to
convert spoken questions. The Azure key is read from KEY_FILE at use time and is never printed, logged or
written anywhere else. Set up with bootstrap.py.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import re
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from xml.sax.saxutils import escape

VERSION = "1.1.0"   # 1.1.0: public layout - key file and project root not tied to one machine, --view mode, pauseAfter
HERE = Path(__file__).resolve().parent
CACHE = Path(os.environ["CODEWALK_CACHE_DIR"]) if os.environ.get("CODEWALK_CACHE_DIR") else HERE / "cache" / "tts"
RUNS = HERE / "runs"
PAGE = Path(os.environ["CODEWALK_PAGE"]) if os.environ.get("CODEWALK_PAGE") else HERE / "page.html"   # tests may serve a variant
POSITIONS = RUNS / "positions"   # last position per walk script id, so a restarted server continues where you were
def claude_command() -> str:
    """The Claude command line as a path that can be started without a shell. On Windows, npm installs claude.CMD, which
    Python cannot start by its bare name; the .exe it calls is used when it is there."""
    exe = shutil.which("claude") or "claude"
    if os.name == "nt" and exe.lower().endswith((".cmd", ".bat")):
        direct = Path(exe).parent / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
        if direct.exists():
            return str(direct)
    return exe


ANSWER_SYSTEM = (
    "You answer a listener's question during a narrated walk through a software project (code and diagrams). "
    "Your answer is spoken aloud by a text-to-speech voice and also shown as text. Use plain spoken English: no markdown, "
    "no lists, no code blocks, no URLs. Usually 1 to 4 short sentences; more only if the question needs it. Answer from "
    "the context given (the current phrase, nearby phrases, the diagram source, the code). If the context does not "
    "say, give your best general answer and say that it is general knowledge, not from this project. "
    "Reply with JSON only: {\"text\": \"...\"} and, only when the code context shows exactly where, also "
    "\"file\" (path relative to the project root), \"line\" and \"endLine\".")
# SPEECH_KEY=... and SPEECH_REGION=... ; bootstrap.py azure writes a template here
KEY_FILE = Path(os.environ.get("CODEWALK_KEY_FILE") or Path.home() / ".config" / "codewalk" / "azure-speech.env")
CONFIG_FILE = Path.home() / ".config" / "codewalk" / "config.json"   # written by bootstrap.py idea --save


def read_config() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


IDEA_LAUNCHER = (os.environ.get("CODEWALK_IDEA_LAUNCHER") or read_config().get("ideaLauncher")
                 or "/mnt/c/Program Files/JetBrains/IntelliJ IDEA 2025.2/bin/idea64.exe")
VOICES = ["en-US-AndrewNeural", "en-US-AvaNeural", "en-GB-RyanNeural"]
WINDOWS_CWD = None if os.name == "nt" else "/mnt/c"
DEFAULT_PORT = 60777
CTRL_HEADER = "X-Codewalk"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def win_to_wsl(p: str) -> Path:
    """Use native drive paths on Windows; translate them for Linux/WSL filesystem access."""
    if os.name == "nt":
        return Path(p)
    p = p.replace("\\", "/")
    if len(p) > 1 and p[1] == ":":
        return Path("/mnt/" + p[0].lower() + p[2:])
    return Path(p)


def to_windows_path(p: str) -> str:
    """A path IDEA on Windows can open: drive paths stay, /mnt/x/... becomes X:\\..., other WSL paths go through wslpath."""
    if re.match(r"^[A-Za-z]:[\\/]", p):
        return p
    m = re.match(r"^/mnt/([a-zA-Z])(/.*)?$", p)
    if m:
        return m.group(1).upper() + ":" + (m.group(2) or "/").replace("/", "\\")
    if os.name != "nt" and shutil.which("wslpath"):
        r = subprocess.run(["wslpath", "-w", p], capture_output=True, text=True, timeout=10)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    return p


def to_win(root_win: str, rel: str) -> str:
    return root_win.replace("/", "\\").rstrip("\\") + "\\" + rel.replace("/", "\\")


IDEA_LAUNCHER = to_windows_path(IDEA_LAUNCHER) if os.name == "nt" else str(win_to_wsl(IDEA_LAUNCHER))


# ----------------------------------------------------------------------------- script

def load_script(path: str | Path, project_root: str | None = None) -> dict:
    s = json.loads(Path(path).read_text(encoding="utf-8"))
    # the project root may be relative to the walk file (repository walks) or given at run time
    root = project_root or s["project"]["root"]
    if not re.match(r"^[A-Za-z]:[\\/]", root) and not root.startswith("/"):
        root = str((Path(path).resolve().parent / root).resolve())
    s["project"] = {**s["project"], "root": root}
    flat = []
    for ci, ch in enumerate(s["chapters"]):
        for it in ch["items"]:
            for ph in it["phrases"]:
                flat.append({"chapterIndex": ci, "chapterId": ch["id"], "chapterTitle": ch["title"],
                             "itemId": it["id"], "itemTitle": it["title"], **ph})
    s["_flat"] = flat
    return s


def read_lines(root: Path, rel: str) -> list[str]:
    p = (root / rel).resolve()
    if root.resolve() not in p.parents:
        raise ValueError(f"pointer escapes the project root: {rel}")
    return p.read_text(encoding="utf-8").splitlines()


def validate(script: dict, script_dir: Path | None = None) -> dict:
    root = win_to_wsl(script["project"]["root"])
    findings, ids, pointers = [], set(), 0
    if script.get("schema") != "codewalk-script-v1":
        findings.append({"code": "SCHEMA", "detail": f"schema is {script.get('schema')!r}"})
    diagrams = script.get("diagrams") or {}
    for did, d in diagrams.items():
        for key in ("source", "svg"):
            if script_dir and d.get(key) and not (script_dir / d[key]).exists():
                findings.append({"code": "DIAGRAM_FILE", "diagram": did, "detail": f"{key} {d[key]} missing"})
    for ph in script["_flat"]:
        pid = ph.get("id")
        if not pid or pid in ids:
            findings.append({"code": "PHRASE_ID", "phrase": pid, "detail": "missing or duplicate id"})
        ids.add(pid)
        if not (ph.get("text") or "").strip():
            findings.append({"code": "TEXT", "phrase": pid, "detail": "empty text"})
        if ph.get("diagram") and ph["diagram"] not in diagrams:
            findings.append({"code": "DIAGRAM_REF", "phrase": pid, "detail": f"unknown diagram {ph['diagram']}"})
        if ph.get("diagramFocus") and script_dir is not None:
            texts = diagram_texts(diagrams.get(ph.get("diagram")), script_dir)
            if texts is None:
                findings.append({"code": "DIAGRAM_FOCUS", "phrase": pid, "detail": "focus given but no readable diagram SVG"})
            else:
                for f in ph["diagramFocus"]:
                    if not any(f in t for t in texts):
                        findings.append({"code": "DIAGRAM_FOCUS", "phrase": pid,
                                         "detail": f"{f!r} is not a text in {ph.get('diagram')}"})
        if ph.get("diagramComponents") and script_dir is not None:
            comps = diagram_components(diagrams.get(ph.get("diagram")), script_dir)
            for ref in ph["diagramComponents"]:
                full, err = resolve_component(ref, comps)
                if err:
                    findings.append({"code": "DIAGRAM_COMPONENT", "phrase": pid, "detail": f"{ref!r}: {err} in {ph.get('diagram')}"})
        if ph.get("action") and ph["action"].get("status") not in ("planned", "needs-approval", "done"):
            findings.append({"code": "ACTION", "phrase": pid, "detail": "action status must be planned|needs-approval|done"})
        c = ph.get("code")
        if not c:
            continue
        pointers += 1
        try:
            lines = read_lines(root, c["file"])
        except (OSError, ValueError) as e:
            findings.append({"code": "FILE", "phrase": pid, "detail": str(e)})
            continue
        s, e = int(c["start"]), int(c.get("end", c["start"]))
        if not (1 <= s <= e <= len(lines)):
            findings.append({"code": "RANGE", "phrase": pid, "detail": f"{c['file']}:{s}-{e} outside 1-{len(lines)}"})
            continue
        anchor = c.get("anchor")
        if anchor and anchor not in "\n".join(lines[s - 1:e]):
            findings.append({"code": "ANCHOR", "phrase": pid,
                             "detail": f"{anchor!r} not found in {c['file']}:{s}-{e}"})
    return {"status": "PASS" if not findings else "FAIL", "phrases": len(script["_flat"]),
            "codePointers": pointers, "chapters": len(script["chapters"]),
            "diagrams": len(diagrams), "diagramUses": sum(1 for p in script["_flat"] if p.get("diagram")),
            "diagramFocus": sum(len(p.get("diagramFocus") or []) for p in script["_flat"]),
            "diagramComponents": sum(len(p.get("diagramComponents") or []) for p in script["_flat"]),
            "actions": sum(1 for p in script["_flat"] if p.get("action")),
            "words": sum(len(p["text"].split()) for p in script["_flat"]), "findings": findings}


_SVG_TEXT_CACHE: dict = {}


def diagram_svg_path(d: dict | None, script_dir: Path | None) -> Path | None:
    if not d or not d.get("svg") or script_dir is None:
        return None
    return (script_dir / d["svg"]).resolve()


def diagram_texts(d: dict | None, script_dir: Path | None) -> list[str] | None:
    """Text nodes of a rendered PlantUML SVG (used to check diagramFocus strings)."""
    import html as _html
    p = diagram_svg_path(d, script_dir)
    if p is None or not p.exists():
        return None
    if p not in _SVG_TEXT_CACHE:
        s = p.read_text(encoding="utf-8")
        _SVG_TEXT_CACHE[p] = [_html.unescape(t) for t in re.findall(r"<text[^>]*>([^<]*)</text>", s)]
    return _SVG_TEXT_CACHE[p]


_SVG_COMP_CACHE: dict = {}


def diagram_components(d: dict | None, script_dir: Path | None) -> dict[str, str] | None:
    """Named components of a rendered PlantUML SVG: data-qualified-name -> kind (entity, cluster, participant).
    PlantUML writes the qualified name (the .puml alias, prefixed by enclosing packages) on each element group."""
    import html as _html
    p = diagram_svg_path(d, script_dir)
    if p is None or not p.exists():
        return None
    if p not in _SVG_COMP_CACHE:
        comps: dict[str, str] = {}
        for tag in re.findall(r"<g\b[^>]*>", p.read_text(encoding="utf-8")):
            q = re.search(r'data-qualified-name="([^"]*)"', tag)
            c = re.search(r'class="([^"]*)"', tag)
            if not q or not c:
                continue
            cls = c.group(1)
            kind = "participant" if "participant" in cls else "cluster" if cls == "cluster" else \
                "entity" if cls == "entity" else None
            if kind:
                comps.setdefault(_html.unescape(q.group(1)), kind)
        _SVG_COMP_CACHE[p] = comps
    return _SVG_COMP_CACHE[p]


def resolve_component(ref: str, comps: dict[str, str] | None) -> tuple[str | None, str | None]:
    """A component reference is the full qualified name or, when unique, its last part (the .puml alias)."""
    if comps is None:
        return None, "no readable diagram SVG"
    if ref in comps:
        return ref, None
    hits = [q for q in comps if q.split(".")[-1] == ref]
    if len(hits) == 1:
        return hits[0], None
    return None, ("ambiguous: " + ", ".join(hits)) if hits else "no such component"


def outline(script: dict) -> str:
    """Readable review text of a walk script: chapters, items, phrases, pointers, diagrams, actions."""
    out = [f"{script['title']}", f"Script {script['id']}  |  project root {script['project']['root']}", ""]
    op = script.get("operator") or {}
    for k in ("task", "guidance", "audience"):
        if op.get(k):
            out.append(f"{k.capitalize()}: {op[k]}")
    words = sum(len(p["text"].split()) for p in script["_flat"])
    out += ["", f"{len(script['chapters'])} chapters, {len(script['_flat'])} phrases, {words} words "
                f"(~{round(words / 150)} min of speech at 150 words per minute, before pauses and questions)", ""]
    diagrams = script.get("diagrams") or {}
    if diagrams:
        out.append("Diagrams: " + "; ".join(f"{k} = {v.get('title')}" for k, v in diagrams.items()))
        out.append("")
    for ci, ch in enumerate(script["chapters"], 1):
        out.append(f"{ci}. {ch['title'].upper()}")
        for it in ch["items"]:
            out.append(f"   {it['title']}")
            for ph in it["phrases"]:
                out.append(f"     [{ph['id']}] {ph['text']}")
                extras = []
                if ph.get("code"):
                    c = ph["code"]
                    rng = f"{c['start']}" if c["start"] == c.get("end", c["start"]) else f"{c['start']}-{c['end']}"
                    extras.append(f"code {c['file']}:{rng}")
                if ph.get("diagram"):
                    extras.append(f"diagram {ph['diagram']}" +
                                  (f" components {', '.join(ph['diagramComponents'])}" if ph.get("diagramComponents") else "") +
                                  (f" focus {', '.join(ph['diagramFocus'])}" if ph.get("diagramFocus") else ""))
                if ph.get("action"):
                    a = ph["action"]
                    extras.append(f"ACTION {a['kind']} ({a['status']}): {a['do']}")
                if extras:
                    out.append("            -> " + "  |  ".join(extras))
        out.append("")
    return "\n".join(out)


def snippet(root: Path, code: dict, context: int = 2) -> dict:
    lines = read_lines(root, code["file"])
    s, e = int(code["start"]), int(code.get("end", code["start"]))
    a, b = max(1, s - context), min(len(lines), e + context)
    return {"file": code["file"], "start": s, "end": e,
            "lines": [{"n": n, "text": lines[n - 1], "hit": s <= n <= e} for n in range(a, b + 1)]}


# ----------------------------------------------------------------------------- Azure Speech

def speech_creds() -> tuple[str, str]:
    if not KEY_FILE.exists():
        raise RuntimeError(f"no Azure Speech key file at {KEY_FILE}; run: python3 bootstrap.py azure")
    vals = {}
    for line in KEY_FILE.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            vals[k.strip()] = v.strip()
    if not vals.get("SPEECH_KEY") or vals["SPEECH_KEY"].startswith("<"):
        raise RuntimeError(f"the key file {KEY_FILE} has no SPEECH_KEY yet; run: python3 bootstrap.py azure")
    return vals["SPEECH_KEY"], vals.get("SPEECH_REGION") or "westus2"


class Throttle:
    """F0 allows 20 TTS transactions per 60 s; stay at 18."""

    def __init__(self, limit=18, window=60.0):
        self.limit, self.window, self.times, self.lock = limit, window, deque(), threading.Lock()

    def acquire(self):
        with self.lock:
            while True:
                t = time.time()
                while self.times and t - self.times[0] > self.window:
                    self.times.popleft()
                if len(self.times) < self.limit:
                    self.times.append(t)
                    return
                time.sleep(self.window - (t - self.times[0]) + 0.1)


THROTTLE = Throttle()
TTS_LOCK = threading.Lock()


def audio_duration(path: Path) -> float:
    if shutil.which("ffprobe"):
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                           capture_output=True, text=True, timeout=30)
        try:
            return round(float(r.stdout.strip()), 3)
        except ValueError:
            pass
    # the requested format is a constant 48 kbit/s MP3: 6000 bytes per second
    return round(path.stat().st_size / 6000, 3)


def clip_paths(text: str, voice: str) -> tuple[Path, Path]:
    """Where the clip of this text in this voice is kept (mp3, meta). The same text and voice reuse one clip."""
    key = hashlib.sha256(f"{voice}\n{text}".encode("utf-8")).hexdigest()[:24]
    return CACHE / f"{key}.mp3", CACHE / f"{key}.json"


def tts(text: str, voice: str) -> tuple[Path, dict]:
    """Return (mp3 path, meta). Cached by voice+text."""
    mp3, meta_p = clip_paths(text, voice)
    with TTS_LOCK:
        if mp3.exists() and meta_p.exists():
            return mp3, {**json.loads(meta_p.read_text(encoding="utf-8")), "cached": True}
        CACHE.mkdir(parents=True, exist_ok=True)
        skey, region = speech_creds()
        lang = "-".join(voice.split("-")[:2])
        ssml = (f"<speak version='1.0' xml:lang='{lang}'><voice name='{voice}'>"
                f"{escape(text)}</voice></speak>").encode("utf-8")
        last = None
        for attempt in range(1, 5):
            THROTTLE.acquire()
            req = urllib.request.Request(
                f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1", data=ssml, method="POST",
                headers={"Ocp-Apim-Subscription-Key": skey, "Content-Type": "application/ssml+xml",
                         "X-Microsoft-OutputFormat": "audio-24khz-48kbitrate-mono-mp3",
                         "User-Agent": "codewalk"})
            t0 = time.time()
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    data = r.read()
                break
            except urllib.error.HTTPError as e:
                last = f"HTTP {e.code}"
                if e.code in (429, 500, 502, 503, 504):
                    time.sleep(5 * attempt)
                    continue
                raise RuntimeError(f"Azure TTS failed: {last}") from None
            except urllib.error.URLError as e:
                last = str(e.reason)
                time.sleep(3 * attempt)
        else:
            raise RuntimeError(f"Azure TTS failed after retries: {last}")
        tmp = mp3.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(mp3)
        meta = {"voice": voice, "text": text, "chars": len(text), "bytes": len(data),
                "synthMs": round((time.time() - t0) * 1000), "durationSec": audio_duration(mp3),
                "createdAt": now_iso()}
        meta_p.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        return mp3, {**meta, "cached": False}


def stt(audio: bytes) -> dict:
    """Azure fast transcription of any ffmpeg-readable audio; returns text, locale, confidence."""
    conv = subprocess.run(["ffmpeg", "-v", "error", "-i", "pipe:0", "-ac", "1", "-ar", "16000", "-f", "wav", "pipe:1"],
                          input=audio, capture_output=True, timeout=60)
    if conv.returncode != 0 or len(conv.stdout) < 1000:
        raise RuntimeError("audio conversion failed: " + conv.stderr.decode("utf-8", "replace")[:200])
    skey, region = speech_creds()
    boundary = uuid.uuid4().hex
    definition = json.dumps({"locales": ["en-US", "ru-RU"], "profanityFilterMode": "None"})
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"audio\"; filename=\"q.wav\"\r\n"
            f"Content-Type: audio/wav\r\n\r\n").encode() + conv.stdout + (
        f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"definition\"\r\n\r\n{definition}\r\n"
        f"--{boundary}--\r\n").encode()
    req = urllib.request.Request(
        f"https://{region}.api.cognitive.microsoft.com/speechtotext/transcriptions:transcribe?api-version=2024-11-15",
        data=body, method="POST",
        headers={"Ocp-Apim-Subscription-Key": skey, "Content-Type": f"multipart/form-data; boundary={boundary}"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            d = json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Azure speech-to-text failed: HTTP {e.code}") from None
    phrases = d.get("phrases", [])
    text = " ".join(p.get("text", "") for p in phrases).strip()
    conf = [p["confidence"] for p in phrases if "confidence" in p]
    return {"text": text, "locale": phrases[0].get("locale") if phrases else None,
            "confidence": round(sum(conf) / len(conf), 3) if conf else None,
            "audioMs": d.get("durationMilliseconds"), "sttMs": round((time.time() - t0) * 1000)}


# ----------------------------------------------------------------------------- IDE navigation

FOCUS_SCRIPT = HERE / "win" / "focus-watch.ps1.txt"
IDE_PROCS = ("idea64", "idea")


class FocusWatcher:
    """Reads the resident Windows focus helper (win/focus-watch.ps1.txt): one JSON line per foreground change,
    plus a heartbeat every 10 s. Read-only: it never changes focus. Used so the walk never pulls IDEA to the front
    while the user works in another window (2026-11-13 incident: typed text landed in source files)."""

    def __init__(self, on_change=None):
        self.on_change, self.current, self.proc, self.error = on_change, None, None, None
        self.lock = threading.Lock()

    def start(self) -> bool:
        try:
            self.proc = subprocess.Popen(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                                          FOCUS_SCRIPT.read_text(encoding="utf-8")],
                                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                         cwd=WINDOWS_CWD, bufsize=1)
        except (OSError, ValueError) as e:
            self.error = str(e)
            return False
        threading.Thread(target=self._read, daemon=True).start()
        end = time.time() + 15
        while time.time() < end and self.current is None and self.proc.poll() is None:
            time.sleep(0.1)
        if self.current is None:
            self.error = "focus helper gave no answer"
        return self.current is not None

    def _read(self):
        for line in self.proc.stdout:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            with self.lock:
                prev, self.current = self.current, {"proc": d.get("proc") or "?", "pid": d.get("pid"),
                                                    "at": time.time()}
            if self.on_change and (prev is None or prev["pid"] != self.current["pid"]):
                try:
                    self.on_change(prev, self.current)
                except Exception:  # noqa: BLE001 - a callback error must not stop the watcher
                    pass
        self.current = None

    def foreground(self) -> dict | None:
        with self.lock:
            if self.current and self.proc and self.proc.poll() is None and time.time() - self.current["at"] < 25:
                return dict(self.current)
        return None

    def ide_in_front(self) -> bool | None:
        fg = self.foreground()
        return None if fg is None else fg["proc"].lower() in IDE_PROCS

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()


def free_memory_gb() -> float | None:
    """Free physical memory on Windows (GB), or None if it cannot be read."""
    try:
        r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                            "(Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory"],
                           capture_output=True, text=True, timeout=30, cwd=WINDOWS_CWD)
        return round(int(r.stdout.strip()) / 1024 / 1024, 2)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def launch_ide_process(root_win: str):
    """Open the project in IDEA (starts IDEA if needed). Returns at once; IDEA keeps running on its own."""
    return subprocess.Popen([IDEA_LAUNCHER, root_win.replace("/", "\\")], cwd=WINDOWS_CWD,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def ide_helper_available() -> bool:
    tools = HERE.parent / "tools"
    return (tools / "ij_mcp.py").is_file() or (tools / "ij_mcp" / "__init__.py").is_file()


def ide_project_ready(root_win: str) -> bool:
    """Check this project through the optional helper, or just IDEA's web server without it."""
    if not ide_helper_available():
        return ide_running()
    try:
        tools = str(HERE.parent / "tools")
        if tools not in sys.path:
            sys.path.insert(0, tools)
        import ij_mcp  # noqa: PLC0415 - optional helper next to codewalk
        r = ij_mcp.run(["get_project_modules"], project=root_win, timeout=15)[0]
        return not r["isError"]
    except Exception:  # noqa: BLE001 - not ready (IDEA starting, MCP not up, project not open)
        return False


def ide_running() -> bool:
    """IDEA's built-in web server (127.0.0.1:63342) answers only while IDEA runs. Used so that the launcher
    never starts IDEA again after it was closed (for example by the user's low-memory rule)."""
    import socket
    try:
        with socket.create_connection(("127.0.0.1", 63342), timeout=0.3):
            return True
    except OSError:
        return False


def navigate_ide(root_win: str, rel: str, line: int) -> dict:
    t0 = time.time()
    if not Path(IDEA_LAUNCHER).exists():
        return {"ok": False, "method": "idea-launcher", "error": "launcher not found"}
    if not ide_running():
        return {"ok": False, "method": "idea-launcher", "error": "IDEA is not running; navigation skipped",
                "file": rel, "line": line, "ms": round((time.time() - t0) * 1000)}
    try:
        r = subprocess.run([IDEA_LAUNCHER, "--line", str(line), "--column", "1", to_win(root_win, rel)],
                           capture_output=True, timeout=20, cwd=WINDOWS_CWD)
        return {"ok": r.returncode == 0, "method": "idea-launcher", "rc": r.returncode,
                "ms": round((time.time() - t0) * 1000), "file": rel, "line": line}
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"ok": False, "method": "idea-launcher", "error": str(e)[:200], "ms": round((time.time() - t0) * 1000)}


# ----------------------------------------------------------------------------- player

class Player:
    """Playback state owner. v2 adds: discussing state, bookmark, session inbox, versioned reload with
    bookmark mapping, corrections queue, IDEA re-anchoring on continue (DESIGN-stop-discuss-amend-resume.txt)."""

    def __init__(self, script: dict, run_dir: Path, voice: str, rate: float, ide: bool,
                 script_path: Path | None = None, ide_follow: str = "safe", root_override: str | None = None,
                 auto_continue: bool = False):
        self.root_override = root_override  # --project-root: where the walked project is on this machine
        self.auto_continue = auto_continue  # --view: skip planned pauses and chapter ends
        self.cur_role = "walk"
        self.ide_follow = ide_follow        # safe: move IDEA only while IDEA is in front; always: old behaviour
        self.focus: FocusWatcher | None = None
        self.pending_nav: dict | None = None
        self.ide_start = "ask"              # if IDEA is closed: ask (button) | auto (start once when first needed) | never
        self.ide_min_free_gb = 5.0          # user's rule: below 5 GB free, IDEA should not be running
        self.ide_state = "unknown"          # unknown | running | down | starting | failed
        self.ide_auto_tried = False
        self.lock = threading.RLock()
        self.inbox_cv = threading.Condition(self.lock)
        self.run_dir, self.ide = run_dir, ide
        self.subs: list[queue.Queue] = []
        self.sub_pages: dict[int, str] = {}   # id(queue) -> page id of that open page
        self.sound_page: str | None = None    # the one page that plays the sound: where the user clicked last
        self.trace_f = open(run_dir / "trace.jsonl", "a", encoding="utf-8")
        self.set_script(script, script_path)
        self.idx, self.status, self.token = 0, "idle", 0
        self.voice, self.rate = voice, rate
        self.audio_done = False
        self.questions: list[dict] = []
        self.answer_token: str | None = None
        self.resume_status: str | None = None
        self.inbox: list[dict] = []
        self.bookmark: dict | None = None
        self.resume: dict | None = None        # {"index", "mode": start|offset, "offset"} after a reload
        self.corrections: list[int] = []       # offered after a reload
        self.queue: list[int] = []             # accepted corrections still to play
        self.queue_return: dict | None = None  # where to go after the queue
        self.discuss_note: str | None = None
        self.last_phrase: dict | None = None   # last phrase event, so a (re)connecting page can show it at once
        self.restored: dict | None = None      # position restored at start-up (from runs/positions), until Play
        self.positions_dir = POSITIONS         # tests use their own folder, so they never move the user's position
        self.answerer, self.answer_model = "off", "sonnet"   # answer helper for page questions: claude | off
        self.waiters, self.last_wait_end = 0, 0.0             # session long-polls (/api/wait) in progress
        self.listening_reported: bool | None = None

    def set_script(self, script: dict, script_path: Path | None):
        self.script, self.flat = script, script["_flat"]
        self.script_path = script_path
        self.version = int(script.get("version", 1))
        self.sha = hashlib.sha256(script_path.read_bytes()).hexdigest()[:16] if script_path else None
        root = self.root_override or script["project"]["root"]
        self.root_win = to_windows_path(root)
        self.root = win_to_wsl(root)
        self.gap_ms = int(script.get("defaults", {}).get("gapMs", 700))
        # first phrase of every topic (item), across chapters: for topic forward/back
        self.item_starts = [i for i, p in enumerate(self.flat)
                            if i == 0 or (p["chapterIndex"], p["itemId"]) != (self.flat[i - 1]["chapterIndex"],
                                                                             self.flat[i - 1]["itemId"])]

    # -- IDEA navigation without stealing focus
    def start_focus(self) -> dict:
        if not self.ide or self.ide_follow != "safe":
            return {"focusWatcher": "off", "ideFollow": self.ide_follow}
        self.focus = FocusWatcher(self.on_focus_change)
        ok = self.focus.start()
        fg = self.focus.foreground()
        info = {"focusWatcher": "on" if ok else f"failed: {self.focus.error}", "ideFollow": self.ide_follow,
                "foreground": fg and fg["proc"]}
        self.trace("focus-watcher", **info)
        return info

    def nav_to(self, code: dict | None, explicit: bool = False) -> dict | None:
        """Move IDEA to the code - but in 'safe' mode only while IDEA is already in front, so a jump never pulls
        IDEA over the window the user is typing in. Otherwise the jump is remembered and done when IDEA comes to
        the front. An explicit request (Show in IDEA now) always jumps."""
        if not code or not self.ide:
            return None
        rel, line = code["file"], int(code["start"])
        if self.ide_state == "starting" or not ide_running():
            with self.lock:
                self.pending_nav = {"file": rel, "line": line}
                if self.ide_state != "starting":
                    self.ide_state = "down"
                auto = self.ide_start == "auto" and not self.ide_auto_tried and self.ide_state == "down"
                if auto:
                    self.ide_auto_tried = True
            if auto:
                threading.Thread(target=self.start_ide, args=("auto",), daemon=True).start()
            starting = self.ide_state == "starting" or auto
            return {"ok": False, "pending": True, "ideDown": True, "file": rel, "line": line, "method": "deferred",
                    "skipped": "IDEA is starting; it will show this code when the project is open" if starting else
                    "IDEA is not running", "ideStart": self.ide_start}
        self.ide_state = "running"
        if self.ide_follow == "safe" and not explicit:
            in_front = self.focus.ide_in_front() if self.focus else None
            if not in_front:
                fg = self.focus.foreground() if self.focus else None
                with self.lock:
                    self.pending_nav = {"file": rel, "line": line}
                why = (f"{fg['proc']} is in front" if fg else "focus helper unavailable")
                return {"ok": False, "pending": True, "skipped": f"{why}; IDEA follows when you switch to it",
                        "foreground": fg and fg["proc"], "file": rel, "line": line, "method": "deferred"}
        with self.lock:
            self.pending_nav = None
        return {**navigate_ide(self.root_win, rel, line), **({"explicit": True} if explicit else {})}

    def start_ide(self, source: str) -> dict:
        """Open the walk's project in IDEA (starting IDEA if needed), then catch up to the current phrase."""
        if not self.ide:
            return {"ok": False, "error": "IDEA is off for this player (--no-ide)"}
        with self.lock:
            if self.ide_state == "starting":
                return {"ok": True, "state": "starting"}
        if ide_helper_available() and ide_running() and ide_project_ready(self.root_win):
            self.ide_state = "running"
            self.emit({"type": "ide", "ide": {"state": "running", "note": "IDEA already has the project open"},
                       "source": source})
            return {"ok": True, "state": "running"}
        free = free_memory_gb()
        if free is not None and free < self.ide_min_free_gb:
            info = {"state": "refused", "freeGb": free,
                    "note": f"only {free} GB free; IDEA is not started below {self.ide_min_free_gb} GB"}
            self.trace("ide-start", source=source, **info)
            self.emit({"type": "ide", "ide": info, "source": source})
            return {"ok": False, **info}
        with self.lock:
            self.ide_state = "starting"
        t0 = time.time()
        launch_ide_process(self.root_win)
        info = {"state": "starting", "freeGb": free, "note": "IDEA may ask whether to trust the project"}
        self.trace("ide-start", source=source, **info)
        self.emit({"type": "ide", "ide": info, "source": source})
        threading.Thread(target=self._wait_ide_ready, args=(t0, source), daemon=True).start()
        return {"ok": True, **info}

    def _wait_ide_ready(self, t0: float, source: str, timeout: float = 300):
        project_check = ide_helper_available()
        if not project_check:
            timeout = min(timeout, 120)   # without the helper: ready as soon as IDEA answers, never a five-minute wait
        while time.time() - t0 < timeout:
            if ide_running() and ide_project_ready(self.root_win):
                with self.lock:
                    self.ide_state = "running"
                    pend, self.pending_nav = self.pending_nav, None
                info = {"state": "running", "startSec": round(time.time() - t0, 1),
                        "readiness": "project-mcp" if project_check else "web-server"}
                if not project_check:
                    info["note"] = "IDEA web server is ready; project loading was not verified"
                self.trace("ide-ready", **info)
                self.emit({"type": "ide", "ide": info, "source": source})
                if pend:
                    # the freshly opened IDEA window is in front, so this jump takes no focus from anything else
                    nav = {**navigate_ide(self.root_win, pend["file"], pend["line"]), "catchUp": True}
                    self.trace("ide-catch-up", **nav)
                    self.emit({"type": "nav", "nav": nav, "source": "ide-start"})
                return
            time.sleep(3)
        with self.lock:
            self.ide_state = "failed"
        target = "the project was not open in IDEA" if project_check else "IDEA web server did not answer"
        info = {"state": "failed", "note": f"{target} after {round(time.time() - t0)} s"}
        self.trace("ide-ready", **info)
        self.emit({"type": "ide", "ide": info, "source": source})

    def on_focus_change(self, prev: dict | None, cur: dict):
        self.trace("focus", proc=cur["proc"], previous=prev and prev["proc"])
        if self.ide_state == "starting":
            return      # the start-up waiter catches up once the project is loaded
        with self.lock:
            pend = self.pending_nav if cur["proc"].lower() in IDE_PROCS else None
            self.pending_nav = None if pend else self.pending_nav
        if pend:
            nav = {**navigate_ide(self.root_win, pend["file"], pend["line"]), "catchUp": True}
            self.trace("ide-catch-up", **nav)
            self.emit({"type": "nav", "nav": nav, "source": "focus"})

    # -- recording
    def trace(self, kind: str, **kw):
        rec = {"ts": now_iso(), "kind": kind, **kw}
        with self.lock:
            self.trace_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            self.trace_f.flush()

    def snapshot(self) -> dict:
        ph = self.flat[self.idx]
        res = self.resume
        return {"status": self.status, "index": self.idx, "total": len(self.flat), "phraseId": ph["id"],
                "chapterIndex": ph["chapterIndex"], "chapters": len(self.script["chapters"]),
                "itemIndex": self.item_index(self.idx), "items": len(self.item_starts),
                "chapterTitle": ph["chapterTitle"], "itemTitle": ph["itemTitle"], "token": self.token,
                "voice": self.voice, "rate": self.rate, "gapMs": self.gap_ms, "audioDone": self.audio_done,
                "openQuestions": sum(1 for q in self.questions if not q.get("answer")),
                "pages": len(self.subs), "soundPage": self.sound_page, "scriptId": self.script.get("id"), "version": self.version,
                "bookmark": self.bookmark.get("phraseId") if self.bookmark else None,
                "resumeAt": self.flat[res["index"]]["id"] if res and res.get("index") is not None else None,
                "resumeMode": res.get("mode") if res else None,
                "corrections": [self.flat[i]["id"] for i in self.corrections],
                "queued": [self.flat[i]["id"] for i in self.queue],
                "discussNote": self.discuss_note, "inboxSeq": len(self.inbox),
                "answerHelper": self.answerer if self.answerer == "off" else f"{self.answerer} ({self.answer_model})",
                "sessionListening": self.waiters > 0 or time.time() - self.last_wait_end < 5.0,
                "restored": self.restored,
                "ideFollow": self.ide_follow if self.ide else "off",
                "ideStart": self.ide_start if self.ide else "off", "ideState": self.ide_state if self.ide else "off",
                "idePending": f"{self.pending_nav['file']}:{self.pending_nav['line']}" if self.pending_nav else None,
                "foreground": (self.focus.foreground() or {}).get("proc") if self.focus else None}

    def emit(self, ev: dict):
        with self.lock:
            ev = {**ev, "ts": now_iso(), "state": self.snapshot()}
            for q in list(self.subs):
                q.put(ev)
            self.trace("event", type=ev["type"], status=self.status, phraseId=ev["state"]["phraseId"],
                       token=self.token, version=self.version,
                       **{k: v for k, v in ev.items()
                          if k in ("source", "nav", "audio", "audioDurationSec", "question", "answerId", "error",
                                   "startAt", "mapping", "role", "bookmark", "note", "diagram", "stopped")})

    def outline(self) -> dict:
        """Title, settings and the table of contents: chapters -> items -> phrases (with their walk position)."""
        pos = {p["id"]: i for i, p in enumerate(self.flat)}
        chapters = []
        for ci, c in enumerate(self.script["chapters"]):
            items = []
            for it in c["items"]:
                phs = it.get("phrases") or []
                if not phs:
                    continue
                items.append({"id": it["id"], "title": it["title"], "firstPhrase": phs[0]["id"],
                              "diagram": next((p["diagram"] for p in phs if p.get("diagram")), None),
                              "code": any(p.get("code") for p in phs),
                              "phrases": [{"id": p["id"], "n": pos[p["id"]] + 1, "text": p["text"]} for p in phs]})
            chapters.append({"id": c["id"], "title": c["title"], "first": self.chapter_first(ci),
                             "firstPhrase": self.flat[self.chapter_first(ci)]["id"], "items": items})
        return {"title": self.script["title"], "voices": VOICES, "operator": self.script.get("operator"),
                "version": self.version, "codePointers": sum(1 for p in self.flat if p.get("code")),
                "phrases": len(self.flat), "chapters": chapters}

    # -- bookmark and session inbox
    def save_bookmark(self, offset: float | None = None):
        with self.lock:
            ph = self.flat[self.idx]
            bm = {"scriptId": self.script.get("id"), "version": self.version, "scriptSha": self.sha,
                  "phraseId": ph["id"], "index": self.idx, "chapterId": ph["chapterId"],
                  "audioOffsetSec": round(offset, 3) if offset is not None else
                  (self.bookmark or {}).get("audioOffsetSec", 0.0) if self.bookmark and
                  self.bookmark.get("phraseId") == ph["id"] else 0.0,
                  "audioDone": self.audio_done, "at": now_iso()}
            self.bookmark = bm
        (self.run_dir / "bookmark.json").write_text(json.dumps(bm, indent=1), encoding="utf-8")
        self.save_position(bm["audioOffsetSec"])
        self.trace("bookmark", **bm)
        return bm

    def add_inbox(self, rec: dict) -> dict:
        with self.inbox_cv:
            rec = {"seq": len(self.inbox) + 1, "at": now_iso(), **rec}
            self.inbox.append(rec)
            self.inbox_cv.notify_all()
        with open(self.run_dir / "inbox.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self.trace("inbox", seq=rec["seq"], type=rec["type"])
        return rec

    def wait_inbox(self, after: int, timeout: float) -> dict | None:
        end = time.time() + timeout
        with self.inbox_cv:
            self.waiters += 1
        self.report_listening()
        try:
            with self.inbox_cv:
                while len(self.inbox) <= after:
                    rest = end - time.time()
                    if rest <= 0:
                        return None
                    self.inbox_cv.wait(rest)
                return self.inbox[after]
        finally:
            with self.inbox_cv:
                self.waiters -= 1
                self.last_wait_end = time.time()
            # a session's wait loop re-polls at once; report "not listening" only if no new wait comes within 5 s
            threading.Timer(5.0, self.report_listening).start()

    def session_listening(self) -> bool:
        with self.lock:
            return self.waiters > 0 or time.time() - self.last_wait_end < 5.0

    def report_listening(self):
        now = self.session_listening()
        if now != self.listening_reported:
            self.listening_reported = now
            self.trace("listeners", sessionListening=now, answerHelper=self.answerer)
            self.emit({"type": "listeners", "source": "server"})

    def context(self) -> dict:
        ph = self.flat[self.idx]
        return {"phraseId": ph["id"], "chapterTitle": ph["chapterTitle"], "itemTitle": ph["itemTitle"],
                "phraseText": ph["text"], "code": ph.get("code"), "version": self.version}

    # -- phrase lifecycle
    def phrase_pub(self, ph: dict) -> tuple[dict, str | None, dict | None]:
        """What the page gets for a phrase: text, place, code snippet, diagram with focus texts and components."""
        pub = {k: ph[k] for k in ("id", "text", "chapterId", "chapterTitle", "itemId", "itemTitle")}
        if ph.get("action"):
            pub["action"] = copy.deepcopy(ph["action"])
        if ph.get("code"):
            pub["code"] = snippet(self.root, ph["code"])
        did = ph.get("diagram")
        dg = (self.script.get("diagrams") or {}).get(did) if did else None
        if dg:
            comps = diagram_components(dg, self.script_path.parent if self.script_path else None)
            pub["diagram"] = {"id": did, "title": dg.get("title", did), "url": f"/diagram/{did}.svg",
                              "focus": list(ph.get("diagramFocus") or []),
                              "components": [f for f in (resolve_component(r, comps)[0]
                                                         for r in ph.get("diagramComponents") or []) if f]}
        return pub, did, dg

    # -- position across server restarts
    def position_file(self) -> Path:
        sid = re.sub(r"[^A-Za-z0-9._-]+", "_", str(self.script.get("id") or "walk"))
        return self.positions_dir / f"{sid}.json"

    def save_position(self, offset: float):
        with self.lock:
            ph = self.flat[self.idx]
            pos = {"scriptId": self.script.get("id"), "version": self.version, "phraseId": ph["id"],
                   "index": self.idx, "audioOffsetSec": round(float(offset or 0.0), 3), "at": now_iso()}
        try:
            self.positions_dir.mkdir(parents=True, exist_ok=True)
            tmp = self.position_file().with_suffix(".tmp")
            tmp.write_text(json.dumps(pos, indent=1), encoding="utf-8")
            os.replace(tmp, self.position_file())
        except OSError as e:
            self.trace("position-save-failed", error=str(e)[:200])

    def restore_position(self, start_at: str | None = None) -> dict | None:
        """Start where the listener was: the saved position of this walk (or --start-at). The page shows that
        phrase at once; Play continues from it (from the saved offset). Nothing plays by itself."""
        pid, offset, src = None, 0.0, None
        if start_at:
            pid, src = start_at, "start-at"
        else:
            try:
                pos = json.loads(self.position_file().read_text(encoding="utf-8"))
                pid, offset, src = pos.get("phraseId"), float(pos.get("audioOffsetSec") or 0.0), "saved position"
            except (OSError, ValueError):
                return None
        hit = next((i for i, p in enumerate(self.flat) if p["id"] == pid), None)
        if hit is None:
            self.trace("position-not-restored", phraseId=pid, reason="phrase not in this script version")
            return None
        with self.lock:
            self.idx = hit
            pub, did, dg = self.phrase_pub(self.flat[hit])
            self.last_phrase = {"type": "phrase", "phrase": pub, "nav": None, "source": "restored", "role": "restored",
                                "diagram": did if dg else None}
            self.restored = {"phraseId": pid, "offset": round(offset, 3), "from": src}
        self.trace("position-restored", **self.restored)
        return self.restored

    def item_index(self, idx: int) -> int:
        return max(k for k, start in enumerate(self.item_starts) if start <= idx)

    def chapter_first(self, ci: int) -> int:
        return next(i for i, p in enumerate(self.flat) if p["chapterIndex"] == ci)

    def start_phrase(self, idx: int, source: str, nav: dict | None = None, start_at: float = 0.0,
                     role: str = "walk"):
        with self.lock:
            self.idx = max(0, min(idx, len(self.flat) - 1))
            self.token += 1
            tok, self.status, self.audio_done = self.token, "playing", False
            self.cur_role = role
            ph = self.flat[self.idx]
        if nav is None and ph.get("code") and self.ide:
            nav = self.nav_to(ph["code"])
        try:
            mp3, meta = tts(ph["text"], self.voice)
        except Exception as e:  # noqa: BLE001 - reported to the page and the trace
            with self.lock:
                self.status = "paused"
            self.emit({"type": "error", "error": str(e)[:300], "source": source})
            return
        with self.lock:
            if tok != self.token:
                return
            pub, did, dg = self.phrase_pub(ph)
            ev = {"type": "phrase", "token": tok, "phrase": pub, "audio": f"/audio/{mp3.stem}.mp3",
                  "audioDurationSec": meta.get("durationSec"), "nav": nav, "source": source,
                  "startAt": round(start_at, 3), "role": role, "diagram": did if dg else None}
            self.last_phrase = ev
            self.restored = None
            self.emit(ev)
        self.save_position(0.0)

    def advance(self, tok: int, wait_gap: bool = False):
        """Move on after a phrase. IDEA navigation for the next phrase overlaps the gap.
        While accepted corrections are queued, they play first, then the walk returns to its resume point."""
        t0 = time.time()
        with self.lock:
            if tok != self.token or self.status != "playing":
                return
            target, start_at, role = None, 0.0, "walk"
            if self.queue:
                target, role = self.queue.pop(0), "correction"
            elif self.queue_return is not None:
                target, start_at = self.queue_return["index"], self.queue_return.get("offset", 0.0)
                self.queue_return, role = None, "return"
            if target is not None:
                last = boundary = False
                nxt = target
            else:
                nxt = self.idx + 1
                last = nxt >= len(self.flat)
                boundary = not last and self.flat[nxt]["chapterIndex"] != self.flat[self.idx]["chapterIndex"]
        nav = None
        if not last and not boundary and self.flat[nxt].get("code") and self.ide:
            nav = {**self.nav_to(self.flat[nxt]["code"]), "duringGap": True}
        if wait_gap:
            rest = self.gap_ms / 1000 - (time.time() - t0)
            if rest > 0:
                time.sleep(rest)
        with self.lock:
            if tok != self.token or self.status != "playing":
                return
            if last:
                self.status = "finished"
                self.emit({"type": "finished", "source": "auto"})
                return
            # view mode never stops at a chapter end; after a pauseAfter phrase the listener has already said go on
            if boundary and not self.auto_continue and not self.flat[self.idx].get("pauseAfter"):
                self.status = "chapter-end"
                self.emit({"type": "chapter-end", "source": "auto"})
                return
        self.start_phrase(nxt, "auto", nav=nav, start_at=start_at, role=role)

    def claim_sound(self, page_id, why: str):
        """Only one open page plays the sound, else two pages speak at once. A click in a page (any of its commands)
        moves the sound there; a page that starts a phrase while no page has it takes it."""
        if not isinstance(page_id, str) or not re.fullmatch(r"[A-Za-z0-9]{1,40}", page_id):
            return
        with self.lock:
            if page_id == self.sound_page or (why == "audio-started" and self.sound_page in self.sub_pages.values()):
                return
            self.sound_page = page_id
        self.emit({"type": "sound-page", "source": why})

    def page_event(self, d: dict):
        self.trace("page", **{k: v for k, v in d.items() if k != "kind"}, audioKind=d.get("kind"))
        ev = d.get("event")
        if ev == "page-closing":   # the page that has the sound is closing: free it now, not at the next keep-alive
            with self.lock:
                freed = d.get("pageId") is not None and d.get("pageId") == self.sound_page
                if freed:
                    self.sound_page = None
            if freed:
                self.emit({"type": "sound-page", "source": "page-closed"})
            return
        with self.lock:
            if d.get("kind") == "answer":
                if ev in ("audio-ended", "audio-error") and d.get("token") == self.answer_token:
                    self.answer_token, self.status = None, self.resume_status or "paused"
                    self.emit({"type": "answer-done", "source": "page"})
                return
            if d.get("token") != self.token:
                return
            if ev == "audio-started" and d.get("kind") == "phrase" and self.sound_page is None:
                self.claim_sound(d.get("pageId"), "audio-started")
            if ev == "audio-paused" and self.status in ("paused", "discussing"):
                pos = d.get("currentTime")
            else:
                pos = None
            if ev != "audio-ended":
                if pos is not None:
                    self.save_bookmark(float(pos))
                return
            self.audio_done = True
            if self.status != "playing":
                if self.status in ("paused", "discussing"):
                    self.save_bookmark()
                return
            if (not self.auto_continue and self.flat[self.idx].get("pauseAfter")
                    and getattr(self, "cur_role", "walk") in ("walk", "resume")
                    and not self.queue and self.queue_return is None):
                self.status = "paused"
                self.emit({"type": "pause", "source": "script", "reason": "pauseAfter"})
                return
            tok = self.token
        threading.Thread(target=self.advance, args=(tok, True), daemon=True).start()

    # -- commands
    def command(self, cmd: str, args: dict, source: str) -> dict:
        self.trace("command", cmd=cmd, args={k: v for k, v in args.items() if k != "audio"}, source=source)
        with self.lock:
            st, idx, ci = self.status, self.idx, self.flat[self.idx]["chapterIndex"]
        if cmd == "state":
            return {"ok": True, "state": self.snapshot(), "questions": self.questions[-20:],
                    "bookmark": self.bookmark, "inbox": self.inbox[-5:]}
        if cmd == "discuss":
            return self.discuss((args.get("note") or "").strip(), source)
        if cmd == "show-in-ide":
            # explicit request: jump now even if another window is in front (IDEA comes to the front on purpose)
            code = self.flat[idx].get("code")
            if not code or not self.ide:
                return {"ok": False, "error": "this phrase has no code pointer" if self.ide else "IDEA is off (--no-ide)"}
            nav = self.nav_to(code, explicit=True)
            self.emit({"type": "nav", "nav": nav, "source": source})
            return {"ok": bool(nav and nav.get("ok")), "nav": nav}
        if cmd == "start-ide":
            return self.start_ide(source)
        if cmd == "ide-start-mode":
            v = args.get("value")
            if v not in ("ask", "auto", "never"):
                return {"ok": False, "error": "ide-start-mode must be ask, auto or never"}
            with self.lock:
                self.ide_start, self.ide_auto_tried = v, False
            self.emit({"type": "settings", "source": source})
            return {"ok": True, "ideStart": v}
        if cmd == "ide-follow":
            v = args.get("value")
            if v not in ("safe", "always"):
                return {"ok": False, "error": "ide-follow must be safe or always"}
            with self.lock:
                self.ide_follow = v
            if v == "safe" and self.ide and not self.focus:
                self.start_focus()
            self.emit({"type": "settings", "source": source})
            return {"ok": True, "ideFollow": v}
        if cmd == "reload":
            return self.reload(args.get("script"), source)
        if cmd == "corrections":
            accept = str(args.get("accept", "true")).lower() in ("1", "true", "yes")
            with self.lock:
                self.queue = list(self.corrections) if accept else []
                offered, self.corrections = self.corrections, []
            self.emit({"type": "settings", "source": source})
            return {"ok": True, "queued": [self.flat[i]["id"] for i in self.queue],
                    "skipped": [] if accept else [self.flat[i]["id"] for i in offered]}
        if cmd in ("play", "continue") and (st == "discussing" or (st == "paused" and self.resume)):
            return self.continue_after_discussion(source)
        if cmd == "play":
            if st == "idle" and self.restored and self.flat[idx]["id"] == self.restored["phraseId"]:
                self.async_start(idx, source, self.restored["offset"], "resume")
            elif st in ("idle", "finished"):
                self.async_start(0 if st == "finished" else idx, source)
            elif st == "paused":
                with self.lock:
                    self.status = "playing"
                self.emit({"type": "resume", "source": source})
                if self.audio_done:
                    threading.Thread(target=self.advance, args=(self.token,), daemon=True).start()
            elif st == "chapter-end":
                return self.command("continue", args, source)
            return {"ok": True}
        if cmd == "stop-answer" or (cmd == "pause" and st == "answering"):
            # stop the spoken answer (button "Stop answer", Space, Esc); the walk returns to where it was
            with self.lock:
                if self.status != "answering":
                    return {"ok": False, "error": "no answer is being spoken"}
                self.answer_token, self.status = None, self.resume_status or "paused"
            self.emit({"type": "answer-done", "source": source, "stopped": True})
            return {"ok": True}
        if cmd == "pause":
            if st == "playing":
                with self.lock:
                    self.status = "paused"
                self.emit({"type": "pause", "source": source})
            return {"ok": True}
        if cmd == "continue":
            if st == "chapter-end" and ci + 1 < len(self.script["chapters"]):
                self.async_start(self.chapter_first(ci + 1), source)
            return {"ok": True}
        if cmd in ("next", "prev"):
            self.async_start(idx + (1 if cmd == "next" else -1), source)
            return {"ok": True}
        if cmd in ("next-chapter", "prev-chapter", "restart-chapter"):
            target = {"next-chapter": ci + 1, "prev-chapter": ci - 1, "restart-chapter": ci}[cmd]
            if cmd == "next-chapter" and target >= len(self.script["chapters"]):
                # forward must never rewind (it used to restart the last chapter)
                return {"ok": False, "error": "already in the last chapter"}
            target = max(0, min(target, len(self.script["chapters"]) - 1))
            self.async_start(self.chapter_first(target), source)
            return {"ok": True}
        if cmd in ("next-item", "prev-item"):
            k = self.item_index(idx) + (1 if cmd == "next-item" else -1)
            if k >= len(self.item_starts):
                return {"ok": False, "error": "already in the last topic"}
            self.async_start(self.item_starts[max(0, k)], source)
            return {"ok": True}
        if cmd == "goto":
            pid = args.get("phrase")
            hit = next((i for i, p in enumerate(self.flat) if p["id"] == pid), None)
            if hit is None:
                return {"ok": False, "error": f"unknown phrase {pid}"}
            self.async_start(hit, source)
            return {"ok": True}
        if cmd == "speed":
            with self.lock:
                self.rate = max(0.5, min(2.0, float(args.get("value", 1.0))))
            self.emit({"type": "settings", "source": source})
            return {"ok": True, "rate": self.rate}
        if cmd == "voice":
            v = args.get("value")
            if v not in VOICES:
                return {"ok": False, "error": f"voice must be one of {VOICES}"}
            with self.lock:
                self.voice = v
            self.emit({"type": "settings", "source": source})
            if st == "playing":
                self.async_start(idx, source)
            return {"ok": True, "voice": v}
        if cmd == "ask":
            return self.ask((args.get("text") or "").strip(), source, args.get("stt"))
        if cmd == "answer":
            return self.answer(args, source)
        if cmd == "stop":
            with self.lock:
                self.status, self.token = "idle", self.token + 1
            self.emit({"type": "stop", "source": source})
            return {"ok": True}
        return {"ok": False, "error": f"unknown command {cmd}"}

    def async_start(self, idx: int, source: str, start_at: float = 0.0, role: str = "walk"):
        threading.Thread(target=self.start_phrase, args=(idx, source, None, start_at, role), daemon=True).start()

    def discuss(self, note: str, source: str) -> dict:
        with self.lock:
            if self.status not in ("playing", "paused", "chapter-end", "discussing", "finished"):
                return {"ok": False, "error": f"cannot discuss while {self.status}"}
            self.resume_status = self.status if self.status != "discussing" else self.resume_status
            self.status, self.discuss_note = "discussing", note or None
        bm = self.save_bookmark()
        rec = self.add_inbox({"type": "discussion", "note": note, "source": source, "bookmark": bm,
                              "context": self.context()})
        self.emit({"type": "discussion", "source": source, "note": note, "bookmark": bm})
        return {"ok": True, "inbox": rec["seq"], "bookmark": bm}

    def reload(self, path: str | None, source: str) -> dict:
        """Load a new script version and map the bookmark onto it (rules a-e of the design)."""
        p = Path(path) if path else self.script_path
        if p is None or not p.exists():
            return {"ok": False, "error": f"script not found: {path}"}
        try:
            new = load_script(p, self.root_override)
        except (OSError, ValueError, KeyError) as e:
            return {"ok": False, "error": f"cannot read script: {e}"}
        v = validate(new, p.resolve().parent)
        if v["status"] != "PASS":
            self.trace("reload-rejected", script=str(p), findings=v["findings"][:5])
            return {"ok": False, "error": "new version failed validation; old version kept", "findings": v["findings"]}
        with self.lock:
            if self.status == "playing":
                self.status = "discussing"
            if self.status == "answering":
                return {"ok": False, "error": "wait until the answer has finished"}
            bm = self.bookmark if self.bookmark and self.bookmark.get("phraseId") else None
        if bm is None or bm.get("index") != self.idx or bm.get("version") != self.version:
            bm = self.save_bookmark()
        old_flat, old_version = self.flat, self.version
        old = {ph["id"]: ph for ph in old_flat}
        old_order = [ph["id"] for ph in old_flat]

        def changed(ph):
            o = old.get(ph["id"])
            return o is not None and (o["text"] != ph["text"] or o.get("code") != ph.get("code"))

        nf = new["_flat"]
        nidx = {ph["id"]: i for i, ph in enumerate(nf)}
        bid = bm["phraseId"]
        rule, offset = None, 0.0
        if bid in nidx:
            i = nidx[bid]
            j = i
            while j - 1 >= 0 and nf[j - 1]["id"] not in old:
                j -= 1
            if j < i:
                resume, mode, rule = j, "start", "d-inserted-before"
            elif changed(nf[i]):
                resume, mode, rule = i, "start", "b-changed"
            elif bm.get("audioDone"):
                resume, mode, rule = min(i + 1, len(nf) - 1), "start", "a-unchanged-finished"
            else:
                resume, mode, rule = i, "offset", "a-unchanged"
                offset = float(bm.get("audioOffsetSec") or 0.0)
        else:
            pos = old_order.index(bid) if bid in old_order else -1
            resume = next((nidx[x] for x in old_order[pos + 1:] if x in nidx), len(nf) - 1)
            mode, rule = "start", "c-deleted"
        inserted_block = set(range(resume, nidx[bid])) if rule == "d-inserted-before" else set()
        corrections = [k for k in range(resume) if k not in inserted_block
                       and (nf[k]["id"] not in old or changed(nf[k]))]
        summary = {"from": old_version, "to": int(new.get("version", old_version + 1)),
                   "changed": [ph["id"] for ph in nf if changed(ph)],
                   "inserted": [ph["id"] for ph in nf if ph["id"] not in old],
                   "deleted": [x for x in old_order if x not in nidx],
                   "bookmark": bid, "rule": rule, "resumeAt": nf[resume]["id"], "mode": mode,
                   "offset": round(offset, 3), "corrections": [nf[k]["id"] for k in corrections],
                   "script": str(p)}
        with self.lock:
            self.set_script(new, p)
            self.idx = resume
            self.token += 1            # silence anything still playing from the old version
            self.audio_done = False
            self.resume = {"index": resume, "mode": mode, "offset": offset}
            self.corrections, self.queue, self.queue_return = corrections, [], None
            if self.status not in ("discussing", "paused", "chapter-end"):
                self.status = "discussing"
        self.save_bookmark(offset)
        self.trace("reload", **summary)
        self.emit({"type": "reloaded", "source": source, "mapping": summary, "outline": self.outline()})
        return {"ok": True, "mapping": summary}

    def continue_after_discussion(self, source: str) -> dict:
        with self.lock:
            res = self.resume or {"index": self.idx, "mode": "offset",
                                  "offset": (self.bookmark or {}).get("audioOffsetSec", 0.0)}
            if (self.bookmark or {}).get("audioDone") and not self.resume:
                res = {"index": min(self.idx + 1, len(self.flat) - 1), "mode": "start", "offset": 0.0}
            target_offset = res["offset"] if res["mode"] == "offset" else 0.0
            self.resume, self.discuss_note, self.corrections = None, None, []
            if self.queue:
                first = self.queue.pop(0)
                self.queue_return = {"index": res["index"], "offset": target_offset}
                start, start_at, role = first, 0.0, "correction"
            else:
                start, start_at, role = res["index"], target_offset, "resume"
        # start_phrase moves IDEA to the phrase's code first: the re-anchor after a discussion
        self.async_start(start, source, start_at, role)
        return {"ok": True, "resumeAt": self.flat[res["index"]]["id"], "startAt": target_offset, "first": role}

    def ask(self, text: str, source: str, stt_meta: dict | None = None) -> dict:
        if not text:
            return {"ok": False, "error": "empty question"}
        with self.lock:
            ph = self.flat[self.idx]
            q = {"id": f"q{len(self.questions) + 1}", "text": text, "source": source, "askedAt": now_iso(),
                 "context": {"phraseId": ph["id"], "chapterTitle": ph["chapterTitle"], "phraseText": ph["text"],
                             "code": ph.get("code"), "version": self.version}, "stt": stt_meta}
            self.questions.append(q)
            if self.status == "playing":
                self.status = "paused"
        bm = self.save_bookmark()
        with open(self.run_dir / "questions.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(q, ensure_ascii=False) + "\n")
        self.add_inbox({"type": "question", "question": q, "bookmark": bm, "context": self.context()})
        if self.answerer != "off":
            q["helper"] = {"state": "working", "startedAt": now_iso(), "model": self.answer_model}
            threading.Thread(target=self.run_helper, args=(q,), daemon=True).start()
        self.emit({"type": "question", "question": q, "source": source})
        return {"ok": True, "question": q}

    # -- answer helper: a short headless Claude call with the walk's context, answers through answer()
    def helper_context(self, q: dict) -> str:
        pid = (q.get("context") or {}).get("phraseId")
        idx = next((i for i, p in enumerate(self.flat) if p["id"] == pid), self.idx)
        ph, sd = self.flat[idx], (self.script_path.parent if self.script_path else None)
        op = self.script.get("operator") or {}
        out = [f"WALK: {self.script.get('title')} (project root {self.root_win})"]
        if op.get("task"):
            out.append(f"WALK PURPOSE: {op['task']}")
        if op.get("audience"):
            out.append(f"AUDIENCE: {op['audience']}")
        out.append(f"POSITION: chapter {ph['chapterIndex'] + 1} '{ph['chapterTitle']}', topic '{ph['itemTitle']}', "
                   f"phrase {idx + 1} of {len(self.flat)}")
        for j in range(max(0, idx - 2), idx):
            out.append(f"EARLIER PHRASE: {self.flat[j]['text']}")
        out.append(f"CURRENT PHRASE (just spoken): {ph['text']}")
        if idx + 1 < len(self.flat):
            out.append(f"NEXT PHRASE: {self.flat[idx + 1]['text']}")
        # the diagram on screen: this phrase's, or the one kept from an earlier phrase of the same chapter
        k = next((j for j in range(idx, -1, -1) if self.flat[j].get("diagram")
                  and self.flat[j]["chapterIndex"] == ph["chapterIndex"]), None)
        if k is not None:
            dp = self.flat[k]
            dg = (self.script.get("diagrams") or {}).get(dp["diagram"]) or {}
            out.append(f"DIAGRAM ON SCREEN: {dg.get('title', dp['diagram'])}")
            if k == idx and (ph.get("diagramComponents") or ph.get("diagramFocus")):
                out.append(f"HIGHLIGHTED NOW: components {ph.get('diagramComponents') or []}, "
                           f"texts {ph.get('diagramFocus') or []}")
            src = (sd / dg["source"]) if sd and dg.get("source") else None
            if src and src.exists():
                out.append("DIAGRAM SOURCE (PlantUML):\n" + src.read_text(encoding="utf-8")[:8000])
        if ph.get("code"):
            c = ph["code"]
            try:
                lines = read_lines(self.root, c["file"])
                a, b = max(1, int(c["start"]) - 12), min(len(lines), int(c.get("end", c["start"])) + 12)
                body = "\n".join(f"{n:5} {lines[n - 1]}" for n in range(a, b + 1))
                out.append(f"CODE ON SCREEN: {c['file']} lines {c['start']}-{c.get('end', c['start'])} "
                           f"(shown with context {a}-{b}):\n{body}")
            except (OSError, ValueError):
                pass
        done = [x for x in self.questions if x.get("answer") and x is not q][-4:]
        for x in done:
            out.append(f"EARLIER QUESTION: {x['text']}\nEARLIER ANSWER: {x['answer']['text']}")
        out.append(f"QUESTION FROM THE LISTENER: {q['text']}")
        return "\n\n".join(out)

    def run_helper(self, q: dict):
        t0 = time.time()
        work = self.run_dir / "answer-helper"
        work.mkdir(exist_ok=True)
        prompt = self.helper_context(q)
        (work / f"{q['id']}-prompt.txt").write_text(prompt, encoding="utf-8")
        system_file = work / "answer-system.txt"
        system_file.write_text(ANSWER_SYSTEM, encoding="utf-8")
        cmd = [claude_command(), "-p", "--model", self.answer_model, "--effort", "low", "--tools", "",
               "--strict-mcp-config", "--no-session-persistence", "--setting-sources", "",
               "--system-prompt-file", str(system_file), "--output-format", "json"]
        self.trace("helper-start", qid=q["id"], model=self.answer_model, promptChars=len(prompt))
        err, text, args = None, None, {}
        try:
            r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=120, cwd=work)
            (work / f"{q['id']}-reply.json").write_text(r.stdout, encoding="utf-8")
            d = json.loads(r.stdout or "{}")
            if r.returncode != 0 or d.get("is_error"):
                raise RuntimeError((d.get("result") or r.stderr or f"exit {r.returncode}")[:300])
            model = next(iter(d.get("modelUsage") or {}), self.answer_model)
            raw = (d.get("result") or "").strip()
            m = re.search(r"\{.*\}", raw, re.S)
            try:
                j = json.loads(m.group(0)) if m else {}
            except ValueError:
                j = {}
            text = (j.get("text") or raw).strip()
            args = {"qid": q["id"], "text": text, "by": f"answer helper ({model})"}
            if j.get("file") and j.get("line"):
                args.update(file=j["file"], line=int(j["line"]), end=int(j.get("endLine") or j["line"]))
        except Exception as e:  # noqa: BLE001 - reported on the page; the session can still answer
            err = str(e)[:300]
        with self.lock:
            answered = bool(q.get("answer"))
        if err or not text:
            q["helper"] = {**q.get("helper", {}), "state": "failed", "error": err or "empty reply"}
            self.trace("helper-failed", qid=q["id"], error=q["helper"]["error"], sec=round(time.time() - t0, 1))
            self.emit({"type": "question-update", "question": q, "source": "answer-helper"})
            return
        if answered:   # the session was quicker
            q["helper"] = {**q.get("helper", {}), "state": "skipped", "note": "already answered"}
            self.trace("helper-skipped", qid=q["id"], sec=round(time.time() - t0, 1))
            return
        res = self.answer(args, "answer-helper")
        if not res.get("ok") and "file" in args:   # a code pointer that does not resolve: answer without it
            res = self.answer({k: v for k, v in args.items() if k not in ("file", "line", "end")}, "answer-helper")
        q["helper"] = {**q.get("helper", {}), "state": "done" if res.get("ok") else "failed",
                       "sec": round(time.time() - t0, 1), **({} if res.get("ok") else {"error": res.get("error")})}
        self.trace("helper-done", qid=q["id"], ok=res.get("ok"), sec=round(time.time() - t0, 1))

    def answer(self, args: dict, source: str) -> dict:
        qid, text = args.get("qid"), (args.get("text") or "").strip()
        q = next((x for x in self.questions if x["id"] == qid), None)
        if not q or not text:
            return {"ok": False, "error": "unknown question id or empty answer"}
        code = None
        if args.get("file"):
            code = {"file": args["file"], "start": int(args.get("line") or 1),
                    "end": int(args.get("end") or args.get("line") or 1)}
            try:
                code = snippet(self.root, code)
            except (OSError, ValueError) as e:
                return {"ok": False, "error": f"bad code pointer: {e}"}
        try:
            mp3, meta = tts(text, self.voice)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)[:300]}
        nav = self.nav_to(code) if code and self.ide else None
        with self.lock:
            q["answer"] = {"text": text, "by": args.get("by") or source, "answeredAt": now_iso(), "code": code}
            if self.status != "answering":
                self.resume_status = self.status if self.status != "playing" else "paused"
            self.status, self.answer_token = "answering", uuid.uuid4().hex[:12]
            tok = self.answer_token
        with open(self.run_dir / "questions.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"answerTo": qid, **q["answer"]}, ensure_ascii=False) + "\n")
        self.emit({"type": "answer", "answerId": tok, "token": tok, "questionId": qid, "question": q,
                   "audio": f"/audio/{mp3.stem}.mp3", "audioDurationSec": meta.get("durationSec"),
                   "nav": nav, "source": source})
        return {"ok": True, "answerId": tok}


# ----------------------------------------------------------------------------- HTTP

def page_version() -> str:
    """Hash of the control page; an open page compares it with the server's at (re)connect and reloads if newer."""
    return hashlib.sha256(PAGE.read_bytes()).hexdigest()[:12]


def make_handler(player: Player):
    class H(BaseHTTPRequestHandler):
        server_version = f"codewalk/{VERSION}"
        disable_nagle_algorithm = True

        def log_message(self, *a):
            pass

        def headers_and_body(self, data):
            # One socket write for finite responses: avoid a headers/body delayed-ACK round trip.
            headers = getattr(self, "_headers_buffer", [])
            if self.request_version != "HTTP/0.9":
                headers.append(b"\r\n")
            self._headers_buffer = []
            self.wfile.write(b"".join(headers) + data)

        def send_json(self, obj, code=200):
            data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.headers_and_body(data)

        def do_GET(self):  # noqa: N802
            path = self.path.split("?")[0]
            if path == "/":
                raw = PAGE.read_bytes()
                ver = hashlib.sha256(raw).hexdigest()[:12]
                data = raw.replace(b"<head>", f'<head>\n<meta name="codewalk-page" content="{ver}">'.encode(), 1)
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.headers_and_body(data)
            elif path == "/api/state":
                self.send_json({"state": player.snapshot(), "outline": player.outline(),
                                "questions": player.questions[-20:], "current": player.last_phrase,
                                "pageVersion": page_version()})
            elif path == "/api/events":
                self.sse()
            elif path.startswith("/diagram/") and path.endswith(".svg"):
                # only diagrams declared by the loaded walk script are served
                did = path[len("/diagram/"):-4]
                f = diagram_svg_path((player.script.get("diagrams") or {}).get(did),
                                     player.script_path.parent if player.script_path else None)
                if f is None or f.suffix != ".svg" or not f.exists():
                    self.send_error(404)
                    return
                data = f.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "image/svg+xml")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; img-src data:")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.headers_and_body(data)
            elif path == "/api/wait":
                # long-poll for the session: next inbox record after seq 'after' (discussion or question)
                qs = dict(kv.split("=", 1) for kv in (self.path.split("?", 1) + [""])[1].split("&") if "=" in kv)
                rec = player.wait_inbox(int(qs.get("after", 0)), min(float(qs.get("timeout", 30)), 600))
                if rec is None:
                    self.send_json({"ok": True, "timeout": True, "inboxSeq": len(player.inbox)})
                else:
                    player.trace("inbox-delivered", seq=rec["seq"], to=self.headers.get("X-Source") or "wait")
                    self.send_json({"ok": True, "record": rec})
            elif path.startswith("/audio/") and path.endswith(".mp3"):
                name = path[len("/audio/"):-4]
                f = CACHE / f"{name}.mp3"
                if not (len(name) == 24 and all(c in "0123456789abcdef" for c in name) and f.exists()):
                    self.send_error(404)
                    return
                data = f.read_bytes()
                size = len(data)
                rng = self.headers.get("Range") or ""
                # Range support: without it Chrome cannot seek, so "continue where you stopped" would restart at 0
                if rng.startswith("bytes="):
                    a, _, b = rng[6:].split(",")[0].strip().partition("-")
                    start = int(a) if a else max(0, size - int(b or 0))
                    end = min(int(b), size - 1) if (a and b) else size - 1
                    if start > end or start >= size:
                        self.send_response(416)
                        self.send_header("Content-Range", f"bytes */{size}")
                        self.end_headers()
                        return
                    self.send_response(206)
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                    data = data[start:end + 1]
                else:
                    self.send_response(200)
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Type", "audio/mpeg")
                self.send_header("Content-Length", str(len(data)))
                self.headers_and_body(data)
            else:
                self.send_error(404)

        def sse(self):
            q: queue.Queue = queue.Queue()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            pid = re.sub(r"[^A-Za-z0-9]", "", (self.path.split("page=", 1) + [""])[1].split("&")[0])[:40]
            with player.lock:
                player.subs.append(q)
                if pid:
                    player.sub_pages[id(q)] = pid
            player.trace("page-connected", pages=len(player.subs), page=pid or None)
            try:
                hello = {"type": "hello", "outline": player.outline(), "state": player.snapshot(),
                         "questions": player.questions[-20:], "current": player.last_phrase,
                         "pageVersion": page_version()}
                self.headers_and_body(f"data: {json.dumps(hello, ensure_ascii=False)}\n\n".encode())
                self.wfile.flush()
                while True:
                    try:
                        ev = q.get(timeout=15)
                        self.wfile.write(f"data: {json.dumps(ev, ensure_ascii=False)}\n\n".encode())
                    except queue.Empty:
                        self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                with player.lock:
                    if q in player.subs:
                        player.subs.remove(q)
                    gone = player.sub_pages.pop(id(q), None)
                    freed = gone is not None and gone == player.sound_page and gone not in player.sub_pages.values()
                    if freed:
                        player.sound_page = None
                player.trace("page-disconnected", pages=len(player.subs), page=gone)
                if freed:
                    player.emit({"type": "sound-page", "source": "page-closed"})

        def do_POST(self):  # noqa: N802
            if self.headers.get(CTRL_HEADER) != "1":
                self.send_json({"ok": False, "error": f"missing {CTRL_HEADER} header"}, 403)
                return
            n = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(n) if n else b""
            path = self.path.split("?")[0]
            try:
                if path == "/api/cmd":
                    d = json.loads(body or b"{}")
                    if d.get("source") == "page" and d.get("pageId"):
                        player.claim_sound(d.get("pageId"), "click")
                    if d.get("cmd") == "sound-here":
                        self.send_json({"ok": True, "state": player.snapshot()})
                    else:
                        self.send_json(player.command(d.get("cmd", ""), d.get("args") or {}, d.get("source") or "api"))
                elif path == "/api/page":
                    player.page_event(json.loads(body or b"{}"))
                    self.send_json({"ok": True})
                elif path == "/api/ask-audio":
                    source = self.headers.get("X-Source") or "voice"
                    player.trace("ask-audio", bytes=len(body), contentType=self.headers.get("Content-Type"), source=source)
                    r = stt(body)
                    player.trace("stt", source=source, **r)
                    if not r["text"]:
                        self.send_json({"ok": False, "error": "nothing recognised", "stt": r})
                    else:
                        self.send_json(player.ask(r["text"], source, r))
                elif path == "/api/stt":
                    # speech to text only (the Stop & discuss note box): returns the text, asks nothing
                    player.trace("stt-audio", bytes=len(body), contentType=self.headers.get("Content-Type"))
                    r = stt(body)
                    player.trace("stt", source="note", **r)
                    self.send_json({"ok": bool(r["text"]), "text": r["text"], "stt": r,
                                    **({} if r["text"] else {"error": "nothing recognised"})})
                else:
                    self.send_json({"ok": False, "error": "not found"}, 404)
            except Exception as e:  # noqa: BLE001
                player.trace("error", path=path, error=str(e)[:300])
                self.send_json({"ok": False, "error": str(e)[:300]}, 500)

    return H


# ----------------------------------------------------------------------------- CLI

def cmd_validate(a):
    r = validate(load_script(a.script, a.project_root), Path(a.script).resolve().parent)
    print(json.dumps(r, indent=1, ensure_ascii=False))
    return 0 if r["status"] == "PASS" else 1


def cmd_outline(a):
    text = outline(load_script(a.script))
    if a.out:
        Path(a.out).write_text(text + "\n", encoding="utf-8")
        print(a.out)
    else:
        print(text)
    return 0


def cmd_tts(a):
    s = load_script(a.script)
    voices = VOICES if a.voices == "all" else a.voices.split(",")
    done = created = 0
    for v in voices:
        for ph in s["_flat"]:
            mp3, meta = tts(ph["text"], v)
            done += 1
            created += not meta["cached"]
            print(f"{v} {ph['id']} {meta['durationSec']}s {mp3.name}", flush=True)
    print(json.dumps({"status": "PASS", "audio": done, "created": created, "cached": done - created}))
    return 0


def cmd_export(a):
    from bundles import export_bundle
    result = export_bundle(a.script, a.out, a.project_root, a.with_code, a.strict, a.voice)
    if result["note"]:
        print(result["note"], flush=True)
    print(json.dumps(result, indent=1, ensure_ascii=False), flush=True)
    return 0


def cmd_serve(a):
    if a.bundle:
        from bundles import prepare_bundle
        prepared = prepare_bundle(a.bundle, a.project_root)
        a.script = str(prepared["script"])
        if not a.project_root:
            a.no_ide = True
        a.project_root = str(prepared["root"])
        a.voice = a.voice or prepared["manifest"]["voice"]
    a.voice = a.voice or VOICES[0]
    if a.view:
        a.no_ide = True
    root = str(win_to_wsl(a.project_root).resolve()) if a.project_root else None
    s = load_script(a.script, root)
    v = validate(s, Path(a.script).resolve().parent)
    if v["status"] != "PASS":
        print(json.dumps(v, indent=1))
        return 1
    run_dir = Path(a.run_dir) if a.run_dir else RUNS / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir.mkdir(parents=True, exist_ok=True)
    player = Player(s, run_dir, a.voice, a.rate, not a.no_ide, Path(a.script).resolve(), a.ide_follow,
                    root_override=root, auto_continue=a.view or a.auto_continue)
    player.ide_start, player.ide_min_free_gb = a.ide_start, a.ide_min_free_gb
    player.answerer, player.answer_model = a.answerer, a.answer_model
    if a.positions:
        player.positions_dir = Path(a.positions)
    restored = None if a.from_start and not a.start_at else player.restore_position(a.start_at)
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(player))
    srv.daemon_threads = True
    info = {"version": VERSION, "url": f"http://127.0.0.1:{a.port}/", "pid": os.getpid(), "runDir": str(run_dir),
            "script": str(Path(a.script).resolve()), "startedAt": now_iso(), "ide": not a.no_ide,
            "answerer": a.answerer if a.answerer == "off" else f"{a.answerer} ({a.answer_model})",
            "restored": restored}
    (run_dir / "server.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
    info.update(player.start_focus())
    player.trace("server-start", **info)
    print(json.dumps(info), flush=True)
    import signal

    def _term(*_):   # runners stop the server with SIGTERM: run the cleanup below (focus helper) too
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, _term)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        player.trace("server-stop")
        if player.focus:
            player.focus.stop()
    return 0


def player_urlopen(request, timeout=60):
    """Keep loopback player traffic local even when the machine has an HTTP proxy."""
    url = request.full_url if isinstance(request, urllib.request.Request) else request
    if urllib.parse.urlsplit(url).hostname in ("127.0.0.1", "localhost", "::1"):
        return urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=timeout)
    return urllib.request.urlopen(request, timeout=timeout)


def post(url: str, path: str, obj: dict) -> dict:
    req = urllib.request.Request(url.rstrip("/") + path, data=json.dumps(obj).encode(), method="POST",
                                 headers={"Content-Type": "application/json", CTRL_HEADER: "1"})
    with player_urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def cmd_ctl(a):
    if a.cmd == "wait":
        req = urllib.request.Request(f"{a.url.rstrip('/')}/api/wait?after={a.after}&timeout={a.timeout}",
                                     headers={"X-Source": a.source})
        with player_urlopen(req, timeout=a.timeout + 30) as r:
            out = json.loads(r.read())
        print(json.dumps(out, indent=1, ensure_ascii=False))
        return 0 if out.get("record") else 2
    args = {}
    if a.value is not None:
        args["value"] = a.value
    for k in ("text", "qid", "file", "line", "end", "phrase", "by", "note", "accept"):
        if getattr(a, k, None) is not None:
            args[k] = getattr(a, k)
    if a.script:
        args["script"] = str(Path(a.script).resolve())
    r = post(a.url, "/api/cmd", {"cmd": a.cmd, "args": args, "source": a.source})
    print(json.dumps(r, indent=1, ensure_ascii=False))
    return 0 if r.get("ok") else 1


# ----------------------------------------------------------------------------- amend (new script version)

def _find_phrase(raw: dict, pid: str):
    for ch in raw["chapters"]:
        for it in ch["items"]:
            for i, ph in enumerate(it["phrases"]):
                if ph["id"] == pid:
                    return ch, it, it["phrases"], i
    raise KeyError(f"phrase {pid} not found")


def apply_patch(raw: dict, patch: dict) -> dict:
    new = copy.deepcopy(raw)
    for op in patch["ops"]:
        kind = op["op"]
        if kind in ("replace_text", "set_code", "delete", "insert_before", "insert_after"):
            ch, it, lst, i = _find_phrase(new, op["phrase"])
            if kind == "replace_text":
                lst[i]["text"] = op["text"]
            elif kind == "set_code":
                if op.get("code"):
                    lst[i]["code"] = op["code"]
                else:
                    lst[i].pop("code", None)
            elif kind == "delete":
                lst.pop(i)
                if not lst:
                    ch["items"].remove(it)
                if not ch["items"]:
                    new["chapters"].remove(ch)
            else:
                at = i if kind == "insert_before" else i + 1
                lst[at:at] = op["phrases"]
        elif kind == "insert_item_after":
            for ch in new["chapters"]:
                ids = [it["id"] for it in ch["items"]]
                if op["item"] in ids:
                    ch["items"].insert(ids.index(op["item"]) + 1, op["newItem"])
                    break
            else:
                raise KeyError(f"item {op['item']} not found")
        elif kind == "insert_chapter_after":
            ids = [ch["id"] for ch in new["chapters"]]
            if op["chapter"] not in ids:
                raise KeyError(f"chapter {op['chapter']} not found")
            new["chapters"].insert(ids.index(op["chapter"]) + 1, op["newChapter"])
        elif kind == "retitle":
            for ch in new["chapters"]:
                if ch["id"] == op["target"]:
                    ch["title"] = op["title"]
                for it in ch["items"]:
                    if it["id"] == op["target"]:
                        it["title"] = op["title"]
        else:
            raise ValueError(f"unknown op {kind}")
    return new


def amend(script_path: Path, patch_path: Path, out: Path | None = None) -> dict:
    raw = json.loads(script_path.read_text(encoding="utf-8"))
    patch = json.loads(patch_path.read_text(encoding="utf-8"))
    version = int(raw.get("version", 1))
    try:
        new = apply_patch(raw, patch)
    except (KeyError, ValueError) as e:
        return {"status": "FAIL", "error": str(e)}
    new["version"], new["parentVersion"] = version + 1, version
    if out is None:
        stem = re.sub(r"(?:\.v\d+)+$", "", script_path.name.removesuffix(".walk.json"))
        if version > 1 and re.fullmatch(r"v\d+", stem):
            stem = "v1"  # migrate the old standalone vN.walk.json convention
        out = script_path.with_name(f"{stem}.v{version + 1}.walk.json")
    if out.exists():
        return {"status": "FAIL", "error": f"{out} exists; amend never overwrites"}
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(new, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    v = validate(load_script(tmp), out.resolve().parent)
    if v["status"] != "PASS":
        tmp.rename(out.with_suffix(".rejected.json"))
        return {"status": "FAIL", "error": "new version failed validation", "findings": v["findings"]}
    tmp.rename(out)
    entry = {"version": version + 1, "parent": version, "file": out.name, "from": script_path.name,
             "sha256": hashlib.sha256(out.read_bytes()).hexdigest()[:16], "at": now_iso(),
             "ops": [{k: op[k] for k in op if k in ("op", "phrase", "item", "chapter", "target")} for op in patch["ops"]],
             "reason": patch.get("reason"), "quote": patch.get("quote"), "by": patch.get("by")}
    with open(out.parent / "changelog.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return {"status": "PASS", "out": str(out), "version": version + 1, "phrases": v["phrases"], "changelog": entry}


def cmd_amend(a):
    r = amend(Path(a.script), Path(a.patch), Path(a.out) if a.out else None)
    print(json.dumps(r, indent=1, ensure_ascii=False))
    return 0 if r["status"] == "PASS" else 1


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="sub", required=True)
    v = sub.add_parser("validate"); v.add_argument("--script", required=True)
    v.add_argument("--project-root", help="where the walked project is (overrides the root in the script)")
    v.set_defaults(fn=cmd_validate)
    o = sub.add_parser("outline"); o.add_argument("--script", required=True); o.add_argument("--out")
    o.set_defaults(fn=cmd_outline)
    t = sub.add_parser("tts"); t.add_argument("--script", required=True); t.add_argument("--voices", default=VOICES[0])
    t.set_defaults(fn=cmd_tts)
    e = sub.add_parser("export", help="export one walk, referencing source by default; no audio")
    e.add_argument("--script", required=True); e.add_argument("--out", required=True)
    e.add_argument("--project-root"); e.add_argument("--with-code", action="store_true")
    e.add_argument("--strict", action="store_true"); e.add_argument("--voice", default=VOICES[0], choices=VOICES)
    e.set_defaults(fn=cmd_export)
    s = sub.add_parser("serve")
    source = s.add_mutually_exclusive_group(required=True)
    source.add_argument("--script"); source.add_argument("--bundle")
    s.add_argument("--port", type=int, default=DEFAULT_PORT)
    s.add_argument("--voice", choices=VOICES); s.add_argument("--rate", type=float, default=1.0)
    s.add_argument("--no-ide", action="store_true", help="do not move IDEA (page only)")
    s.add_argument("--view", action="store_true",
                   help="pure view mode: page only, plays through chapter ends without stopping (press Play once)")
    s.add_argument("--auto-continue", action="store_true", help="skip planned pauses and chapter ends")
    s.add_argument("--project-root", help="where the walked project is (overrides the root in the script)")
    s.add_argument("--ide-follow", choices=["safe", "always"], default="safe",
                   help="safe (default): move IDEA only while IDEA is in front, catch up when you switch to it; "
                        "always: move IDEA at every phrase (IDEA comes to the front - do not type elsewhere)")
    s.add_argument("--ide-start", choices=["ask", "auto", "never"], default="ask",
                   help="if IDEA is closed: ask (Start IDEA button, default), auto (start it once when first needed - its window comes to the front), never")
    s.add_argument("--ide-min-free-gb", type=float, default=5.0, help="do not start IDEA below this much free memory")
    s.add_argument("--answerer", choices=["claude", "off"], default="claude" if shutil.which("claude") else "off",
                   help="answer page questions automatically with a short headless Claude call (default: on if the "
                        "claude CLI is installed); tests that script their own answers use off")
    s.add_argument("--answer-model", default="sonnet", help="model for the answer helper")
    s.add_argument("--start-at", help="phrase id to start at (instead of the saved position)")
    s.add_argument("--from-start", action="store_true", help="ignore the saved position")
    s.add_argument("--positions", help="folder for saved positions (default runs/positions; tests use their own)")
    s.add_argument("--run-dir"); s.set_defaults(fn=cmd_serve)
    m = sub.add_parser("amend", help="apply a patch to a walk script -> next version (+ changelog)")
    m.add_argument("--script", required=True); m.add_argument("--patch", required=True); m.add_argument("--out")
    m.set_defaults(fn=cmd_amend)
    c = sub.add_parser("ctl", help="play|pause|continue|next|prev|next-chapter|prev-chapter|restart-chapter|goto|"
                                   "speed|voice|ask|answer|stop|state|discuss|reload|corrections|wait")
    c.add_argument("cmd"); c.add_argument("--value"); c.add_argument("--text"); c.add_argument("--qid")
    c.add_argument("--file"); c.add_argument("--line", type=int); c.add_argument("--end", type=int)
    c.add_argument("--phrase"); c.add_argument("--by"); c.add_argument("--source", default="cli")
    c.add_argument("--note"); c.add_argument("--script"); c.add_argument("--accept")
    c.add_argument("--after", type=int, default=0); c.add_argument("--timeout", type=float, default=60)
    # CODEWALK_URL (also used by mcp_server.py) points ctl at another player, e.g. a test server
    c.add_argument("--url", default=os.environ.get("CODEWALK_URL") or f"http://127.0.0.1:{DEFAULT_PORT}/")
    c.set_defaults(fn=cmd_ctl)
    a = p.parse_args(argv)
    try:
        return a.fn(a)
    except (ValueError, OSError) as error:
        # Expected input/IO failures keep their machine-readable result; other exceptions propagate.
        if a.sub not in ("export", "serve"):
            raise
        print(json.dumps({"status": "FAIL", "error": str(error)}, ensure_ascii=False), flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
