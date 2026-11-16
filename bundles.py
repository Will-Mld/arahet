"""Versioned walk bundles. Standard library only; source is referenced unless explicitly allowed."""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

HERE = Path(__file__).resolve().parent
FORMAT = "codewalk-bundle-v1"
ALLOWED = frozenset(("Apache-2.0", "MIT", "BSD-2-Clause", "BSD-3-Clause", "ISC"))
LICENSE_NAMES = ("LICENSE", "LICENSE.txt", "LICENSE.md", "COPYING")
NOTICE_NAMES = ("NOTICE", "NOTICE.txt", "NOTICE.md")
MAX_FILE = 16 * 1024 * 1024
MAX_TOTAL = 128 * 1024 * 1024
MAX_MEMBERS = 4096
DENIED_LICENSE_TERMS = re.compile(
    r"commons\s+clause|business\s+source\s+license|polyform|server\s+side\s+public\s+license|"
    r"elastic\s+license|non[-\s]?commercial|commercial\s+use\s+is\s+prohibited|"
    r"not\s+permitted\s+to\s+sell|may\s+not\s+sell", re.IGNORECASE)
MIT_BODY = """Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:
The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE."""
ISC_BODY = """Permission to use, copy, modify, and/or distribute this software for any
purpose with or without fee is hereby granted, provided that the above
copyright notice and this permission notice appear in all copies.
THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH
REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY
AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY SPECIAL, DIRECT,
INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM
LOSS OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR
OTHER TORTIOUS ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR
PERFORMANCE OF THIS SOFTWARE."""
BSD_GRANT = """Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:
1. Redistributions of source code must retain the above copyright notice, this
list of conditions and the following disclaimer.
2. Redistributions in binary form must reproduce the above copyright notice,
this list of conditions and the following disclaimer in the documentation
and/or other materials provided with the distribution."""
BSD_DISCLAIMER = """THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
POSSIBILITY OF SUCH DAMAGE."""


class BundleError(ValueError):
    pass


class DownloadUnavailable(BundleError):
    pass


def _normal(text):
    return " ".join(text.replace("\ufeff", "").replace("“", '"').replace("”", '"').lower().split())


def _standard_body(text, body):
    """Ignore a title/copyright header, never an extra term after a standard grant."""
    normalized, target = _normal(text), _normal(body)
    if not normalized.endswith(target):
        return False
    prefix = text[:text.lower().find(body.split()[0].lower())]
    return all(not line.strip() or re.match(r"(?i)^(?:#+\s*)?(?:copyright\b|all rights reserved\.|"
               r"(?:the )?mit licen[cs]e|isc licen[cs]e|bsd.*licen[cs]e|spdx-license-identifier:)", line.strip())
               for line in prefix.splitlines())


def license_id(text):
    normalized = _normal(text)
    if "polyform strict license" in normalized:
        return "PolyForm-Strict-1.0.0"
    if DENIED_LICENSE_TERMS.search(normalized):
        return "restricted"
    apache = _normal((HERE / "third_party/APACHE-2.0.txt").read_text(encoding="utf-8"))
    if normalized.startswith(apache):  # keep any component notices verbatim with the project licence
        return "Apache-2.0"
    if _standard_body(text, MIT_BODY):
        return "MIT"
    if _standard_body(text, ISC_BODY):
        return "ISC"
    for clauses in (2, 3):
        third = (r" 3\. neither the name of .+? nor the names of its contributors may be used to endorse or "
                 r"promote products derived from this software without specific prior written permission.") if clauses == 3 else ""
        pattern = re.escape(_normal(BSD_GRANT)) + third + " " + re.escape(_normal(BSD_DISCLAIMER))
        match = re.search(pattern + "$", normalized)
        if match and _standard_body(text, text[text.lower().find("redistribution and use"):]):
            return f"BSD-{clauses}-Clause"
    return "unknown"


def detect_license(root, texts=None):
    found = []
    for name in LICENSE_NAMES:
        path = Path(root) / name
        present = name in texts if texts is not None else path.is_file()
        if present:
            data = texts[name] if texts is not None else read_file(path)
            found.append((name, license_id(data.decode("utf-8-sig", errors="replace"))))
    if not found:
        return {"id": "missing", "file": None, "allowed": False}
    # Ambiguous/conflicting root licence files do not opt into code redistribution.
    ids = {item[1] for item in found}
    ident = found[0][1] if len(ids) == 1 else "unknown"
    return {"id": ident, "file": found[0][0], "files": [x[0] for x in found], "allowed": ident in ALLOWED}


def safe_path(value):
    if not isinstance(value, str) or not value or len(value) > 1024 or "\\" in value or ":" in value:
        raise BundleError(f"Unsafe bundle path: {value!r}")
    parts = value.split("/")
    reserved = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
    if any(p in ("", ".", "..") or p.endswith((".", " ")) or p.split(".")[0].lower() in reserved
           or any(ord(c) < 32 or c in '<>"|?*' for c in p) for p in parts):
        raise BundleError(f"Unsafe bundle path: {value!r}")
    return PurePosixPath(value).as_posix()


def read_file(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_FILE:
        raise BundleError(f"Missing, linked or oversized file: {path}")
    with path.open("rb") as source:
        data = source.read(MAX_FILE + 1)
    if len(data) > MAX_FILE:
        raise BundleError(f"Oversized file: {path}")
    return data


def source_file(root, relative):
    relative = safe_path(relative)
    if Path(root).is_symlink():
        raise BundleError("Linked source root refused")
    root = Path(root).resolve()
    current = root
    for part in relative.split("/"):
        current = current / part
        if current.is_symlink():
            raise BundleError(f"Linked source path refused: {relative}")
    if root not in current.resolve().parents:
        raise BundleError(f"Source path escapes project: {relative}")
    return current


def digest(data):
    return hashlib.sha256(data).hexdigest()


def mismatch_message(prefix, data, expected_sha):
    lf = data.replace(b"\r\n", b"\n")
    crlf = lf.replace(b"\n", b"\r\n")
    if any(candidate != data and digest(candidate) == expected_sha for candidate in (lf, crlf)):
        detail = "File line endings differ from the pinned source/commit (CRLF vs LF)."
    else:
        detail = "Check the content and line endings (CRLF vs LF) against the pinned commit."
    return prefix + " " + detail + " Use a checkout with core.autocrlf=false, or a fresh clone configured that way."


def validate_svg(data):
    """Reject active SVG before it can be served or inserted into the control page."""
    try:
        text = data.decode("utf-8-sig")
        if re.search(r"<!\s*ENTITY\b|<\s*(?:[\w.-]+:)?(?:script|foreignobject|set|animate)", text, re.IGNORECASE):
            raise BundleError("Unsafe SVG: active elements or entity declarations")
        svg = ET.fromstring(text)
    except (UnicodeDecodeError, ET.ParseError) as error:
        raise BundleError("Invalid SVG XML") from error
    if svg.tag.rsplit("}", 1)[-1].lower() != "svg":
        raise BundleError("Invalid SVG root")
    for element in svg.iter():
        name = element.tag.rsplit("}", 1)[-1].lower()
        if name in ("script", "foreignobject", "set") or name.startswith("animate"):
            raise BundleError("Unsafe SVG element: " + name)
        for attribute, value in element.attrib.items():
            name = attribute.rsplit("}", 1)[-1].lower()
            if name.startswith("on") or (name == "href" and not value.startswith("#")):
                raise BundleError("Unsafe SVG attribute: " + name)


def _git_file(root, project, relative):
    path = (project.get("subdir", "") + "/" if project.get("subdir") else "") + relative
    spec = project["commit"] + ":" + path
    size = _git(root, "cat-file", "-s", spec)
    if size is None:
        return None
    if not size.isdigit() or int(size) > MAX_FILE:
        raise BundleError("Pinned Git file is oversized or invalid: " + relative)
    try:
        result = subprocess.run(["git", "-C", str(root), "show", spec], capture_output=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise BundleError("Cannot read pinned Git file: " + relative) from error
    if result.returncode or len(result.stdout) != int(size):
        raise BundleError("Cannot read pinned Git file: " + relative)
    return result.stdout


def project_notices(root, project):
    texts = {}
    pinned_git = project.get("kind") == "git" or (root / ".git").exists()
    for name in LICENSE_NAMES + NOTICE_NAMES:
        path = root / name
        working = read_file(path) if path.exists() else None
        pinned = _git_file(root, project, name) if pinned_git else working
        if pinned_git and working != pinned:
            prefix = f"Working-tree licence/NOTICE differs from the pinned Git commit: {name}."
            raise BundleError(mismatch_message(prefix, working, digest(pinned)) if working is not None and pinned is not None else prefix)
        if pinned is not None:
            texts[name] = pinned
    return texts


def _file_info(data):
    try:
        lines = len(data.decode("utf-8").splitlines())
    except UnicodeDecodeError as error:
        raise BundleError("Referenced source must be UTF-8 text") from error
    return {"sha256": digest(data), "bytes": len(data), "lines": lines}


def _git(root, *args):
    try:
        result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, timeout=20)
        return result.stdout.decode("utf-8").strip() if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, UnicodeDecodeError):
        return None


def clean_remote(remote):
    if not isinstance(remote, str):
        return None
    if remote.startswith("git@"):
        remote = "ssh://" + remote.replace(":", "/", 1)
    parsed = urllib.parse.urlsplit(remote)
    if parsed.scheme not in ("http", "https", "ssh", "git") or not parsed.hostname:
        return None
    try:
        port = f":{parsed.port}" if parsed.port else ""
    except ValueError:
        return None
    return urllib.parse.urlunsplit((parsed.scheme, parsed.hostname + port, parsed.path, "", ""))


def project_reference(raw, root):
    import bootstrap
    for name, project in bootstrap.PROJECTS.items():
        if raw.get("name") == project["dest"] or (raw.get("commit") == project["commit"] and raw.get("version") == project["version"]):
            return {"name": raw.get("name", name), "kind": "example", "example": name, "module": project["module"],
                    "version": project["version"], "commit": project["commit"], "h1": project["h1"],
                    "sources": list(project["gitSources"]), "repository": project["gitSources"][0], "localOnly": False}
    commit, top = _git(root, "rev-parse", "HEAD"), _git(root, "rev-parse", "--show-toplevel")
    remote = _git(root, "remote", "get-url", "origin")
    if not remote:
        remotes = _git(root, "remote")
        remote = _git(root, "remote", "get-url", remotes.splitlines()[0]) if remotes else None
    remote = clean_remote(remote) if remote else None
    if commit and top and re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", commit):
        subdir = Path(root).resolve().relative_to(Path(top).resolve()).as_posix()
        return {"name": raw.get("name", Path(root).name), "kind": "git", "commit": commit, "sources": [remote] if remote else [],
                "repository": remote, "subdir": "" if subdir == "." else subdir, "localOnly": remote is None}
    return {"name": raw.get("name", Path(root).name), "kind": "local", "commit": None, "sources": [], "repository": None, "localOnly": True}


def export_bundle(script_path, output, project_root=None, with_code=False, strict=False, voice=None):
    import codewalk
    script_path, output = Path(script_path).resolve(), Path(output)
    if output.exists():
        raise BundleError(f"Refused to overwrite: {output}")
    raw = json.loads(read_file(script_path).decode("utf-8"))
    loaded = codewalk.load_script(script_path, str(project_root) if project_root else None)
    result = codewalk.validate(loaded, script_path.parent)
    if result["status"] != "PASS":
        raise BundleError("Walk failed validation: " + json.dumps(result["findings"]))
    root = codewalk.win_to_wsl(loaded["project"]["root"]).resolve()
    project = project_reference(raw["project"], root)
    notices = project_notices(root, project)
    license = detect_license(root, notices)
    include = with_code and license["allowed"]
    excluded = f"Code not included: licence {license['id']} is not on the fixed allow-list." if with_code and not include else None
    if excluded and strict:
        raise BundleError(excluded + " --strict: no bundle written.")
    paths = sorted({safe_path(ph["code"]["file"]) for ph in loaded["_flat"] if ph.get("code")})
    files, members = [], {}
    for relative in paths:
        data = read_file(source_file(root, relative))
        if project["kind"] == "git":
            repository_path = (project["subdir"] + "/" if project["subdir"] else "") + relative
            pinned = _git(root, "rev-parse", project["commit"] + ":" + repository_path)
            working = _git(root, "hash-object", "--no-filters", "--", relative)
            if not pinned or pinned != working:
                committed = _git_file(root, project, relative)
                prefix = f"Referenced file bytes differ from the pinned Git commit: {relative}."
                raise BundleError(mismatch_message(prefix, data, digest(committed)) if committed is not None else
                                  prefix + " Check line endings (CRLF vs LF); use a checkout with core.autocrlf=false or a fresh clone.")
        files.append({"path": relative, **_file_info(data)})
        if include:
            members["code/" + relative] = data
    bundled = copy.deepcopy(raw)
    bundled["project"]["root"] = "../code" if include else "../project"
    used = {ph["diagram"] for ph in loaded["_flat"] if ph.get("diagram")}
    bundled["diagrams"] = {key: value for key, value in bundled.get("diagrams", {}).items() if key in used}
    for number, key in enumerate(sorted(used)):
        diagram = bundled["diagrams"][key]
        for field, extension in (("source", ".puml"), ("svg", ".svg")):
            if field not in diagram:
                continue
            path = script_path.parent / diagram[field]
            if path.suffix.lower() != extension:
                raise BundleError(f"Unexpected diagram {field} type: {path.name}")
            target = f"assets/{number}{extension}"
            members["walk/" + target] = read_file(path)
            diagram[field] = target
    script_data = (json.dumps(bundled, indent=1, ensure_ascii=False) + "\n").encode("utf-8")
    members["walk/walk.walk.json"] = script_data
    attribution = f"unmodified files from {project['repository'] or 'a local-only project'} at {project['commit'] or 'a local-only revision'}, included to play this walk"
    if include:
        for name in license["files"] + [n for n in NOTICE_NAMES if n in notices]:
            members["LICENSES/" + name] = notices[name]
        members["LICENSES/ATTRIBUTION.txt"] = (attribution + "\n").encode("utf-8")
    instructions = (f"{raw['title']}\nCodewalk bundle {FORMAT}\n\n"
                    "Play: python3 bootstrap.py run --bundle <this file>\n"
                    "Or: python3 codewalk.py serve --bundle <this file> --no-ide\n"
                    "For a local-only reference add --project-root <matching project>.\n"
                    "IDEA follow requires --project-root <matching local project>.\n"
                    "No audio is included; narration uses your own local cache/key.\n\n"
                    f"Project: {project['name']}\nRepository: {project['repository'] or 'local only'}\n"
                    f"Commit: {project['commit'] or 'local only'}\nLicence: {license['id']}\n" +
                    (attribution if include else "Source is referenced; no source files are included.") + "\n")
    members["README.txt"] = instructions.encode("utf-8")
    manifest = {"format": FORMAT, "codewalkVersion": codewalk.VERSION,
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "walk": {"id": raw["id"], "version": raw.get("version", 1), "title": raw["title"],
                         "path": "walk/walk.walk.json", "sha256": digest(script_data)},
                "project": project, "files": files, "license": license, "codeIncluded": bool(include),
                "voice": voice or codewalk.VOICES[0],
                "members": {name: {"sha256": digest(data), "bytes": len(data)} for name, data in sorted(members.items())}}
    validate_manifest(manifest)
    if sum(len(data) for data in members.values()) > MAX_TOTAL:
        raise BundleError("Bundle exceeds the uncompressed size limit")
    output.parent.mkdir(parents=True, exist_ok=True)
    created = False
    try:
        with output.open("xb") as stream:
            created = True
            with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", json.dumps(manifest, indent=1, ensure_ascii=False) + "\n")
                for name, data in sorted(members.items()):
                    archive.writestr(name, data)
    except Exception:
        if created:
            output.unlink(missing_ok=True)
        raise
    return {"status": "PASS", "out": str(output), "bytes": output.stat().st_size,
            "codeIncluded": bool(include), "license": license["id"], "files": len(files), "note": excluded}


def _typed(value, expected, field, nullable=False):
    if value is None and nullable:
        return
    if type(value) is not expected:
        raise BundleError(f"Manifest {field} must be {expected.__name__}")


def _project_fields(project):
    _typed(project, dict, "project")
    for field in ("name", "kind", "example", "module", "version", "h1", "subdir"):
        if field in project:
            _typed(project[field], str, "project." + field)
    for field in ("commit", "repository"):
        if field in project:
            _typed(project[field], str, "project." + field, nullable=True)
    if "localOnly" in project:
        _typed(project["localOnly"], bool, "project.localOnly")
    _typed(project.get("sources"), list, "project.sources")
    for source in project["sources"]:
        _typed(source, str, "project.sources[]")
    subdir = project.get("subdir", "")
    if subdir:
        safe_path(subdir)
        decoded = urllib.parse.unquote(subdir)
        safe_path(decoded)


def validate_manifest(manifest):
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
        raise BundleError("Unknown bundle format")
    try:
        walk = manifest["walk"]
        _typed(walk, dict, "walk")
        for field in ("id", "path", "title", "sha256"):
            _typed(walk[field], str, "walk." + field)
        for field in ("codewalkVersion", "createdAt", "voice"):
            _typed(manifest[field], str, field)
        _project_fields(manifest["project"])
        license = manifest["license"]
        _typed(license, dict, "license")
        _typed(license["id"], str, "license.id")
        _typed(license["file"], str, "license.file", nullable=True)
        if "allowed" in license:
            _typed(license["allowed"], bool, "license.allowed")
        if "files" in license:
            _typed(license["files"], list, "license.files")
            for file in license["files"]:
                safe_path(file)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", walk["id"]):
            raise BundleError("Unsafe walk id")
        safe_path(walk["id"])
        if type(walk["version"]) is not int or not 1 <= walk["version"] <= 1_000_000:
            raise BundleError("Invalid walk version")
        if walk["path"] != "walk/walk.walk.json":
            raise BundleError("Unexpected walk path")
        members, files = manifest["members"], manifest["files"]
        if not isinstance(members, dict) or not isinstance(files, list) or len(members) + 1 > MAX_MEMBERS or len(files) > MAX_MEMBERS:
            raise BundleError("Invalid bundle inventory")
        all_paths = set()
        for name, info in members.items():
            safe_path(name)
            _typed(info, dict, "members[]")
            _typed(info["sha256"], str, "members[].sha256")
            if name not in ("README.txt", "walk/walk.walk.json") and not name.startswith(("walk/assets/", "code/", "LICENSES/")):
                raise BundleError(f"Unexpected bundle member: {name}")
            if name.casefold() in all_paths:
                raise BundleError("Case-colliding bundle paths")
            all_paths.add(name.casefold())
            if not re.fullmatch(r"[a-f0-9]{64}", info["sha256"]) or type(info["bytes"]) is not int or not 0 <= info["bytes"] <= MAX_FILE:
                raise BundleError("Invalid member digest or size")
        if walk["sha256"] != members[walk["path"]]["sha256"] or "README.txt" not in members:
            raise BundleError("Missing walk or README digest")
        seen = set()
        for info in files:
            _typed(info, dict, "files[]")
            _typed(info["sha256"], str, "files[].sha256")
            path = safe_path(info["path"])
            if path.casefold() in seen:
                raise BundleError("Duplicate source path")
            seen.add(path.casefold())
            if not re.fullmatch(r"[a-f0-9]{64}", info["sha256"]) or type(info["lines"]) is not int or info["lines"] < 0:
                raise BundleError("Invalid source digest or line count")
            if type(info["bytes"]) is not int or not 0 <= info["bytes"] <= MAX_FILE:
                raise BundleError("Invalid source size")
        included = manifest["codeIncluded"]
        if type(included) is not bool or not isinstance(manifest["project"], dict):
            raise BundleError("Invalid project or code flag")
        expected = {"code/" + info["path"] for info in files} if included else set()
        if {name for name in members if name.startswith("code/")} != expected:
            raise BundleError("Code inventory disagrees with manifest")
        if included and (manifest["license"]["id"] not in ALLOWED or "LICENSES/ATTRIBUTION.txt" not in members
                         or "LICENSES/" + safe_path(manifest["license"]["file"]) not in members):
            raise BundleError("Code bundle lacks an allowed licence/attribution")
        if not included and any(name.startswith("LICENSES/") for name in members):
            raise BundleError("Reference bundle unexpectedly contains licence payload")
        if sum(info["bytes"] for info in members.values()) > MAX_TOTAL:
            raise BundleError("Bundle exceeds size limit")
        if sum(info["bytes"] for info in files) > MAX_TOTAL:
            raise BundleError("Referenced source exceeds size limit")
    except (KeyError, TypeError) as error:
        raise BundleError("Malformed bundle manifest") from error


def unpack_bundle(bundle, cache_dir=None):
    bundle = Path(bundle)
    if bundle.stat().st_size > MAX_TOTAL:
        raise BundleError("Compressed bundle exceeds size limit")
    fingerprint = digest(bundle.read_bytes())
    cache = Path(cache_dir or os.environ.get("CODEWALK_BUNDLE_CACHE_DIR") or HERE / "cache/bundles")
    try:
        with zipfile.ZipFile(bundle) as archive:
            infos = archive.infolist()
            names, total = {}, 0
            if len(infos) > MAX_MEMBERS:
                raise BundleError("Too many archive entries")
            for info in infos:
                name = safe_path(info.filename.rstrip("/") if info.is_dir() else info.filename)
                mode = stat.S_IFMT(info.external_attr >> 16)
                if "\x00" in info.orig_filename or mode not in (0, stat.S_IFREG, stat.S_IFDIR) or info.flag_bits & 1:
                    raise BundleError("Linked, special or encrypted zip entry refused")
                if name.casefold() in names:
                    raise BundleError("Duplicate/case-colliding zip entries")
                names[name.casefold()] = name
                total += info.file_size
                if info.file_size > MAX_FILE or total > MAX_TOTAL:
                    raise BundleError("Archive exceeds size limit")
            manifest = json.loads(archive.read("manifest.json"))
            validate_manifest(manifest)
            actual = {info.filename for info in infos if not info.is_dir()}
            if actual != set(manifest["members"]) | {"manifest.json"}:
                raise BundleError("Zip inventory differs from manifest")
            destination = cache / f"{manifest['walk']['id']}-v{manifest['walk']['version']}"
            cache.mkdir(parents=True, exist_ok=True)
            if destination.is_symlink():
                raise BundleError("Linked bundle cache refused")
            if destination.exists():
                marker = destination / ".bundle-sha256"
                if marker.is_symlink() or not marker.is_file():
                    raise BundleError("Unowned bundle cache directory refused")
                previous = marker.read_text(encoding="utf-8")
                if previous != fingerprint:
                    if not re.fullmatch(r"[a-f0-9]{64}", previous):
                        raise BundleError("Invalid bundle cache marker")
                    variants = destination / ".variants"
                    if variants.is_symlink():
                        raise BundleError("Linked bundle variants directory refused")
                    variants.mkdir(exist_ok=True)
                    destination = variants / fingerprint
                    if destination.is_symlink():
                        raise BundleError("Linked bundle variant refused")
                    if destination.exists() and read_file(destination / ".bundle-sha256").decode() != fingerprint:
                        raise BundleError("Bundle variant marker mismatch")
            if not destination.exists():
                with tempfile.TemporaryDirectory(prefix=".bundle-", dir=cache) as temporary:
                    folder = Path(temporary) / "payload"
                    folder.mkdir()
                    for name, expected in manifest["members"].items():
                        data = archive.read(name)
                        if digest(data) != expected["sha256"] or len(data) != expected["bytes"]:
                            raise BundleError(f"Bundle checksum mismatch: {name}")
                        if name.startswith("walk/assets/") and name.lower().endswith(".svg"):
                            validate_svg(data)
                        target = folder / name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(data)
                    (folder / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
                    (folder / ".bundle-sha256").write_text(fingerprint, encoding="utf-8")
                    try:
                        folder.rename(destination)
                    except OSError:
                        if not destination.exists():
                            raise
                        if destination.is_symlink() or read_file(destination / ".bundle-sha256").decode() != fingerprint:
                            raise BundleError("Concurrent bundle cache marker mismatch")
            for name, expected in manifest["members"].items():
                data = read_file(source_file(destination, name))
                if digest(data) != expected["sha256"] or len(data) != expected["bytes"]:
                    raise BundleError(f"Cached bundle checksum mismatch: {name}")
                if name.startswith("walk/assets/") and name.lower().endswith(".svg"):
                    validate_svg(data)
    except (zipfile.BadZipFile, KeyError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BundleError(f"Invalid bundle: {error}") from error
    raw = json.loads(read_file(destination / manifest["walk"]["path"]).decode("utf-8"))
    _typed(raw, dict, "walk payload")
    if (raw.get("id"), raw.get("version", 1), raw.get("title")) != tuple(manifest["walk"][k] for k in ("id", "version", "title")):
        raise BundleError("Walk identity differs from manifest")
    try:
        referenced = {safe_path(p["code"]["file"]) for ch in raw["chapters"] for item in ch["items"]
                      for p in item["phrases"] if p.get("code")}
    except (KeyError, TypeError) as error:
        raise BundleError("Malformed bundled walk") from error
    if referenced != {entry["path"] for entry in manifest["files"]}:
        raise BundleError("Walk source references differ from manifest")
    diagrams = raw.get("diagrams", {})
    _typed(diagrams, dict, "walk diagrams")
    for diagram in diagrams.values():
        _typed(diagram, dict, "walk diagram")
        for field in ("source", "svg"):
            if field in diagram and "walk/" + safe_path(diagram[field]) not in manifest["members"]:
                raise BundleError("Missing or unsafe diagram asset")
            if field == "svg" and field in diagram:
                validate_svg(read_file(source_file(destination, "walk/" + diagram[field])))
    if manifest["codeIncluded"]:
        text = read_file(destination / "LICENSES" / manifest["license"]["file"]).decode("utf-8-sig")
        if license_id(text) != manifest["license"]["id"]:
            raise BundleError("Bundled licence text does not match its allowed id")
    return destination, manifest


def verify_source(root, files):
    for info in files:
        data = read_file(source_file(root, info["path"]))
        if _file_info(data) != {k: info[k] for k in ("sha256", "bytes", "lines")}:
            raise BundleError(mismatch_message(f"Source checksum mismatch: {info['path']}.", data, info["sha256"]))


def raw_urls(project, relative):
    _project_fields(project)
    commit = project.get("commit")
    if not isinstance(commit, str) or not re.fullmatch(r"[a-fA-F0-9]{40}", commit):
        return []
    urls = []
    subdir = project.get("subdir", "")
    path = safe_path((subdir + "/" if subdir else "") + relative)
    for source in project.get("sources", []):
        clean = clean_remote(source)
        if not clean:
            continue
        parsed = urllib.parse.urlsplit(clean)
        match = re.fullmatch(r"/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?", parsed.path)
        if parsed.hostname == "github.com" and not parsed.port and match:
            owner, repository = match.groups()
            if owner.startswith(".") or repository.startswith("."):
                continue
            urls.append(f"https://raw.githubusercontent.com/{owner}/{repository}/{commit}/" + urllib.parse.quote(path, safe="/"))
    return list(dict.fromkeys(urls))


def download_sources(destination, project, files):
    from codewalk import player_urlopen
    deadline = time.monotonic() + 300
    for index, info in enumerate(files, 1):
        target = source_file(destination, info["path"])
        if target.exists():
            verify_source(destination, [info])
            continue
        urls = raw_urls(project, info["path"])
        if not urls:
            raise DownloadUnavailable("No pinned GitHub source; pass --project-root with matching files")
        data, last_error = None, None
        for url in urls:
            if time.monotonic() >= deadline:
                raise DownloadUnavailable("Per-file download exceeded five minutes")
            try:
                with player_urlopen(url, timeout=min(30, max(1, deadline - time.monotonic()))) as response:
                    data = response.read(min(MAX_FILE, info["bytes"]) + 1)
                break
            except (OSError, urllib.error.URLError) as error:
                last_error = type(error).__name__
        if data is None:
            raise DownloadUnavailable(f"Pinned file download unavailable: {info['path']} ({last_error})")
        if _file_info(data) != {k: info[k] for k in ("sha256", "bytes", "lines")}:
            raise BundleError(mismatch_message(f"Downloaded source checksum mismatch: {info['path']}.", data, info["sha256"]))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)  # only verified bytes enter the source cache
        print(f"Verified source {index}/{len(files)}: {info['path']}", flush=True)


def prepare_bundle(bundle, project_root=None, cache_dir=None):
    import bootstrap
    import codewalk
    folder, manifest = unpack_bundle(bundle, cache_dir)
    if manifest.get("voice") not in codewalk.VOICES:
        raise BundleError("Unsupported bundle voice")
    files = manifest["files"]
    if manifest["codeIncluded"]:
        verify_source(folder / "code", files)
    if project_root:
        source = codewalk.win_to_wsl(str(project_root)).resolve()
        verify_source(source, files)
        origin = "verified local project (--project-root)"
    elif manifest["codeIncluded"]:
        source, origin = folder / "code", "verified bundled code"
    elif not files:
        source, origin = folder / "project", "no source files referenced"
        source.mkdir(exist_ok=True)
    else:
        source = folder / "project"
        source.mkdir(exist_ok=True)
        try:
            download_sources(source, manifest["project"], files)
            verify_source(source, files)
            origin = "verified per-file download/cache at the pinned commit"
        except DownloadUnavailable:
            example = manifest["project"].get("example")
            if example not in bootstrap.PROJECTS or not bootstrap.demo_ready(example):
                raise
            source = bootstrap.demo_root(example)
            verify_source(source, files)
            origin = "verified existing pinned example project"
    script = folder / manifest["walk"]["path"]
    checked = codewalk.validate(codewalk.load_script(script, str(source)), script.parent)
    if checked["status"] != "PASS":
        raise BundleError("Unpacked walk failed validation: " + json.dumps(checked["findings"]))
    print("Bundle source: " + origin, flush=True)
    return {"script": script, "root": source, "manifest": manifest, "source": origin}
