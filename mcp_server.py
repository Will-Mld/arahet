#!/usr/bin/env python3
"""codewalk MCP server (stdio, JSON-RPC 2.0, one message per line).

Lets an LLM client (Claude Code, the IDEA AI Assistant, Codex) drive a running codewalk player.
It forwards to the player's local HTTP API (CODEWALK_URL, default http://127.0.0.1:60777/), source "mcp".
Example client config:  {"command": "python3", "args": ["<this folder>/mcp_server.py"]}
"""
import json
import os
import sys
import urllib.request
from codewalk import VERSION, player_urlopen

URL = os.environ.get("CODEWALK_URL", "http://127.0.0.1:60777/").rstrip("/")
CONTROL = ["play", "pause", "continue", "next", "prev", "next-item", "prev-item", "next-chapter", "prev-chapter",
           "restart-chapter", "stop", "stop-answer"]

TOOLS = [
    {"name": "codewalk_state", "description": "Current position (chapter, item, phrase), status, voice, speed and recent questions.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "codewalk_control", "description": "Playback control: " + ", ".join(CONTROL) + ".",
     "inputSchema": {"type": "object", "properties": {"command": {"type": "string", "enum": CONTROL}}, "required": ["command"]}},
    {"name": "codewalk_goto", "description": "Jump to a phrase id from the walk script (for example c3.p1) and play it.",
     "inputSchema": {"type": "object", "properties": {"phrase": {"type": "string"}}, "required": ["phrase"]}},
    {"name": "codewalk_settings", "description": "Change playback speed (0.5-2.0) and/or the narrator voice.",
     "inputSchema": {"type": "object", "properties": {"speed": {"type": "number"}, "voice": {"type": "string"}}}},
    {"name": "codewalk_ask", "description": "Ask a question at the current position; playback pauses.",
     "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
    {"name": "codewalk_answer", "description": "Answer a question by id. The answer is spoken; an optional code pointer moves IDEA and the page.",
     "inputSchema": {"type": "object", "properties": {
         "questionId": {"type": "string"}, "text": {"type": "string"}, "file": {"type": "string", "description": "path relative to the project root"},
         "line": {"type": "integer"}, "endLine": {"type": "integer"}, "by": {"type": "string", "description": "who answers, e.g. the model name"}},
         "required": ["questionId", "text"]}},
    {"name": "codewalk_discuss", "description": "Stop the walk for a discussion; saves a bookmark and creates an inbox record.",
     "inputSchema": {"type": "object", "properties": {"note": {"type": "string"}}}},
    {"name": "codewalk_wait", "description": "Wait (up to timeoutSec, max 60) for the next discussion or question after inbox seq 'after'.",
     "inputSchema": {"type": "object", "properties": {"after": {"type": "integer"}, "timeoutSec": {"type": "number"}}}},
    {"name": "codewalk_reload", "description": "Load an amended walk script version; the bookmark is mapped onto it (see design rules a-e).",
     "inputSchema": {"type": "object", "properties": {"script": {"type": "string", "description": "path of the new version"}},
                     "required": ["script"]}},
    {"name": "codewalk_start_ide", "description": "Open the walk's project in IntelliJ IDEA (starts IDEA if it is closed; "
     "refused below the free-memory limit). IDEA's window comes to the front.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "codewalk_corrections", "description": "Accept or skip replaying corrected earlier phrases before continuing.",
     "inputSchema": {"type": "object", "properties": {"accept": {"type": "boolean"}}, "required": ["accept"]}},
]


def http(method, path, obj=None):
    data = json.dumps(obj).encode() if obj is not None else None
    req = urllib.request.Request(URL + path, data=data, method=method,
                                 headers={"Content-Type": "application/json", "X-Codewalk": "1"})
    with player_urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def cmd(c, args=None):
    return http("POST", "/api/cmd", {"cmd": c, "args": args or {}, "source": "mcp"})


def call(name, a):
    if name == "codewalk_state":
        d = http("GET", "/api/state")
        return {"state": d["state"], "questions": d.get("questions", [])}
    if name == "codewalk_control":
        return cmd(a["command"])
    if name == "codewalk_goto":
        return cmd("goto", {"phrase": a["phrase"]})
    if name == "codewalk_settings":
        out = {}
        if "speed" in a:
            out["speed"] = cmd("speed", {"value": a["speed"]})
        if "voice" in a:
            out["voice"] = cmd("voice", {"value": a["voice"]})
        return out or {"ok": False, "error": "give speed and/or voice"}
    if name == "codewalk_ask":
        return cmd("ask", {"text": a["text"]})
    if name == "codewalk_answer":
        args = {"qid": a["questionId"], "text": a["text"], "by": a.get("by") or "mcp client"}
        if a.get("file"):
            args.update(file=a["file"], line=a.get("line") or 1, end=a.get("endLine") or a.get("line") or 1)
        return cmd("answer", args)
    if name == "codewalk_discuss":
        return cmd("discuss", {"note": a.get("note") or ""})
    if name == "codewalk_wait":
        t = min(float(a.get("timeoutSec") or 30), 60)
        return http("GET", f"/api/wait?after={int(a.get('after') or 0)}&timeout={t}")
    if name == "codewalk_reload":
        return cmd("reload", {"script": a["script"]})
    if name == "codewalk_start_ide":
        return cmd("start-ide")
    if name == "codewalk_corrections":
        return cmd("corrections", {"accept": bool(a["accept"])})
    raise ValueError(f"unknown tool {name}")


def reply(i, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": i}
    msg["error" if error else "result"] = error or result
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            m = json.loads(line)
        except ValueError:
            continue
        i, method, params = m.get("id"), m.get("method"), m.get("params") or {}
        if i is None:
            continue  # notification
        if method == "initialize":
            reply(i, {"protocolVersion": params.get("protocolVersion", "2024-11-05"), "capabilities": {"tools": {}},
                      "serverInfo": {"name": "codewalk", "version": VERSION}})
        elif method == "ping":
            reply(i, {})
        elif method == "tools/list":
            reply(i, {"tools": TOOLS})
        elif method == "tools/call":
            try:
                out = call(params.get("name"), params.get("arguments") or {})
                reply(i, {"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}],
                          "isError": isinstance(out, dict) and out.get("ok") is False})
            except Exception as e:  # noqa: BLE001
                reply(i, {"content": [{"type": "text", "text": f"error: {e}"}], "isError": True})
        else:
            reply(i, error={"code": -32601, "message": f"method not found: {method}"})


if __name__ == "__main__":
    main()
