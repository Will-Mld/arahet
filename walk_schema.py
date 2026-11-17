"""Structural invariants shared by validation and all walk loaders."""


def findings(script):
    errors = []

    def error(code, detail):
        errors.append({"code": code, "detail": detail})

    def text(obj, field, where):
        if not isinstance(obj.get(field), str) or not obj[field].strip():
            error("STRUCTURE", f"{where}.{field} must be a nonempty string")

    def children(obj, field, where):
        value = obj.get(field)
        if not isinstance(value, list):
            error("STRUCTURE", f"{where}.{field} must be a list")
            return []
        if not value:
            error("EMPTY", f"{where} has no {field}")
        return value

    if not isinstance(script, dict):
        return [{"code": "STRUCTURE", "detail": "walk must be an object"}]
    for field in ("id", "title"):
        text(script, field, "walk")
    for field in ("defaults", "diagrams", "operator"):
        if field in script and not isinstance(script[field], dict):
            error("STRUCTURE", f"walk.{field} must be an object")
    if "version" in script and (type(script["version"]) is not int or script["version"] < 1):
        error("STRUCTURE", "walk.version must be a positive integer")
    if isinstance(script.get("diagrams"), dict):
        for key, diagram in script["diagrams"].items():
            if not isinstance(diagram, dict):
                error("STRUCTURE", f"diagrams.{key} must be an object")
    if not isinstance(script.get("project"), dict):
        error("STRUCTURE", "walk.project must be an object")
    else:
        text(script["project"], "root", "walk.project")
    ids = {"chapter": set(), "item": set(), "phrase": set()}

    def node(value, kind, where):
        if not isinstance(value, dict):
            error("STRUCTURE", f"{where} must be an object")
            return False
        text(value, "id", where)
        ident = value.get("id")
        if isinstance(ident, str):
            if ident in ids[kind]:
                error(kind.upper() + "_ID", f"duplicate {kind} id: {ident}")
            ids[kind].add(ident)
        text(value, "text" if kind == "phrase" else "title", where)
        if kind == "phrase":
            for field in ("code", "action"):
                if field in value and not isinstance(value[field], dict):
                    error("STRUCTURE", f"{where}.{field} must be an object")
            for field in ("diagramFocus", "diagramComponents"):
                if field in value and (not isinstance(value[field], list) or any(not isinstance(x, str) for x in value[field])):
                    error("STRUCTURE", f"{where}.{field} must be a list of strings")
            if "diagram" in value and not isinstance(value["diagram"], str):
                error("STRUCTURE", f"{where}.diagram must be a string")
        return True

    for ci, chapter in enumerate(children(script, "chapters", "walk")):
        where = f"chapters[{ci}]"
        if not node(chapter, "chapter", where):
            continue
        for ii, item in enumerate(children(chapter, "items", where)):
            iw = f"{where}.items[{ii}]"
            if not node(item, "item", iw):
                continue
            for pi, phrase in enumerate(children(item, "phrases", iw)):
                node(phrase, "phrase", f"{iw}.phrases[{pi}]")
    return errors


class InvalidWalk(ValueError):
    def __init__(self, errors):
        self.findings = errors
        super().__init__("Invalid walk: " + "; ".join(error["detail"] for error in errors))


def require(script):
    errors = findings(script)
    if errors:
        raise InvalidWalk(errors)
