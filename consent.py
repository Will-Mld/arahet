"""Explicit, local decisions for the two external services. No credentials live here."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import threading

LOCK = threading.RLock()
AZURE_MESSAGE = "Narration text and spoken-question audio are sent to Microsoft Azure Speech; allow this?"
CLAUDE_MESSAGE = ("Send your question, current phrase, nearby code, paths, diagram and earlier questions "
                  "to Claude (Anthropic) for an answer?")


def path():
    return Path(os.environ.get("CODEWALK_CONSENT_FILE") or Path.home() / ".config/codewalk/consent.json")


def read():
    try:
        value = json.loads(path().read_text(encoding="utf-8"))
        return {key: value[key] for key in ("azure", "claude") if type(value.get(key)) is bool}
    except (OSError, ValueError, AttributeError):
        return {}


def decision(provider):
    return read().get(provider)


def record(**decisions):
    if not decisions or any(key not in ("azure", "claude") or type(value) is not bool for key, value in decisions.items()):
        raise ValueError("Consent must specify azure/claude with an explicit yes or no")
    with LOCK:
        data = {**read(), **decisions, "decidedAt": datetime.now(timezone.utc).isoformat()}
        target = path()
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent, delete=False) as output:
            temporary = Path(output.name)
            json.dump(data, output, indent=1)
            output.write("\n")
        try:
            temporary.chmod(0o600)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    return read()


class Required(PermissionError):
    pass


def require_azure():
    if decision("azure") is not True:
        raise Required("Azure consent is not yes: narration and spoken questions are off; captions still work. "
                       "Run bootstrap.py azure or bootstrap.py consent --azure yes|no.")
