"""Offline bundle regressions; the only HTTP server is local and owned by these tests."""
import contextlib
import copy
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import stat
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import warnings
import zipfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import bootstrap
import bundles
import codewalk

MIT = '''MIT License
Copyright (c) 2026 Example Authors

Permission is hereby granted, free of charge, to any person obtaining a copy
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
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
'''
ISC = '''ISC License
Copyright (c) 2026 Example Authors

Permission to use, copy, modify, and/or distribute this software for any
purpose with or without fee is hereby granted, provided that the above
copyright notice and this permission notice appear in all copies.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH
REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY
AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY SPECIAL, DIRECT,
INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM
LOSS OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR
OTHER TORTIOUS ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR
PERFORMANCE OF THIS SOFTWARE.
'''
BSD_HEAD = '''BSD License
Copyright (c) 2026 Example Authors
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this
   list of conditions and the following disclaimer.
2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.
'''
BSD_THIRD = '''3. Neither the name of Example Authors nor the names of its contributors may
   be used to endorse or promote products derived from this software without
   specific prior written permission.
'''
BSD_TAIL = '''THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
POSSIBILITY OF SUCH DAMAGE.
'''


class Exports(unittest.TestCase):
    def setUp(self):
        base = ROOT / "runs/export-unit"
        base.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.project = self.directory / "project"
        (self.project / "src").mkdir(parents=True)
        self.source = b"def hello():\n    return 42\n"
        (self.project / "src/main.py").write_bytes(self.source)
        (self.project / "LICENSE").write_text(MIT, encoding="utf-8")
        self.walk = self.directory / "walk"
        self.walk.mkdir()
        self.raw = {"schema": "codewalk-script-v1", "id": "fixture", "version": 3, "parentVersion": 2,
                    "title": "Fixture", "project": {"name": "fixture", "root": "../project"},
                    "chapters": [{"id": "c", "title": "Chapter", "items": [{"id": "i", "title": "Item",
                    "phrases": [{"id": "p1", "text": "The answer is returned here.",
                                 "code": {"file": "src/main.py", "start": 1, "end": 2, "anchor": "def hello"}}]}]}]}
        self.script = self.walk / "fixture.walk.json"
        self.save_script()
        self.output = self.directory / "fixture.codewalk.zip"
        self.cache = self.directory / "cache/bundles"
        git = patch.object(bundles, "_git", return_value=None)
        git.start(); self.addCleanup(git.stop)

    def save_script(self):
        self.script.write_text(json.dumps(self.raw), encoding="utf-8")

    def export(self, **kwargs):
        return bundles.export_bundle(self.script, self.output, **kwargs)

    def manifest(self):
        with zipfile.ZipFile(self.output) as archive:
            return json.loads(archive.read("manifest.json"))

    def rewrite(self, edits=None, additions=()):
        target = self.directory / "modified.zip"
        with zipfile.ZipFile(self.output) as old, zipfile.ZipFile(target, "w") as new:
            for info in old.infolist():
                new.writestr(info, (edits or {}).get(info.filename, old.read(info.filename)))
            for name, data in additions:
                new.writestr(name, data)
        return target

    def test_all_five_standard_licences_and_alternate_filenames(self):
        cases = {"MIT": MIT, "ISC": ISC, "BSD-2-Clause": BSD_HEAD + BSD_TAIL,
                 "BSD-3-Clause": BSD_HEAD + BSD_THIRD + BSD_TAIL,
                 "Apache-2.0": (ROOT / "third_party/APACHE-2.0.txt").read_text(encoding="utf-8")}
        for ident, text in cases.items():
            with self.subTest(licence=ident):
                (self.project / "LICENSE").write_text(text, encoding="utf-8")
                self.assertEqual(bundles.detect_license(self.project)["id"], ident)
                self.assertTrue(bundles.detect_license(self.project)["allowed"])
        (self.project / "LICENSE").unlink()
        for name in ("LICENSE.txt", "LICENSE.md", "COPYING"):
            (self.project / name).write_text(MIT, encoding="utf-8")
            self.assertEqual(bundles.detect_license(self.project)["id"], "MIT")
            (self.project / name).unlink()

    def test_polyform_unknown_missing_and_just_an_spdx_label_are_refused(self):
        for text in ((ROOT / "LICENSE").read_text(encoding="utf-8"), "All rights reserved.", "SPDX-License-Identifier: MIT",
                     MIT + "Additional restriction: no redistribution."):
            (self.project / "LICENSE").write_text(text, encoding="utf-8")
            self.assertFalse(bundles.detect_license(self.project)["allowed"])
        (self.project / "LICENSE").unlink()
        self.assertEqual(bundles.detect_license(self.project)["id"], "missing")

    def test_reference_manifest_has_hashes_and_neither_code_nor_audio(self):
        self.export()
        manifest = self.manifest()
        self.assertFalse(manifest["codeIncluded"])
        self.assertEqual(manifest["walk"]["version"], 3)
        self.assertTrue(manifest["project"]["localOnly"])
        self.assertEqual(manifest["files"], [{"path": "src/main.py", "sha256": hashlib.sha256(self.source).hexdigest(),
                                             "bytes": len(self.source), "lines": 2}])
        with zipfile.ZipFile(self.output) as archive:
            self.assertFalse(any(name.startswith(("code/", "LICENSES/")) or name.endswith(".mp3") for name in archive.namelist()))
            for name, expected in manifest["members"].items():
                self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(), expected["sha256"])

    def test_code_round_trip_preserves_source_licence_notice_and_version(self):
        (self.project / "NOTICE").write_bytes(b"Project notice\n")
        self.export(with_code=True)
        with contextlib.redirect_stdout(io.StringIO()):
            prepared = bundles.prepare_bundle(self.output, cache_dir=self.cache)
        self.assertIn("bundled code", prepared["source"])
        self.assertEqual((prepared["root"] / "src/main.py").read_bytes(), self.source)
        raw = json.loads(prepared["script"].read_text())
        self.assertEqual(raw["version"], 3)
        self.assertEqual(raw["chapters"], self.raw["chapters"])
        self.assertEqual(prepared["script"].parent.parent.name, "fixture-v3")
        with zipfile.ZipFile(self.output) as archive:
            self.assertEqual(archive.read("LICENSES/LICENSE"), (self.project / "LICENSE").read_bytes())
            self.assertEqual(archive.read("LICENSES/NOTICE"), b"Project notice\n")
            self.assertIn(b"included to play this walk", archive.read("LICENSES/ATTRIBUTION.txt"))

    def test_assets_outside_walk_folder_are_bundled_and_unused_assets_omitted(self):
        assets = self.directory / "shared"
        assets.mkdir()
        (assets / "d.puml").write_text("@startuml\nrectangle Main as main\n@enduml\n")
        (assets / "d.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"><text>Main</text></svg>')
        self.raw["diagrams"] = {"d": {"source": "../shared/d.puml", "svg": "../shared/d.svg", "title": "Diagram"},
                                "unused": {"source": "../shared/d.puml", "svg": "../shared/d.svg", "title": "Unused"}}
        self.raw["chapters"][0]["items"][0]["phrases"][0]["diagram"] = "d"
        self.save_script()
        self.export(with_code=True)
        with contextlib.redirect_stdout(io.StringIO()):
            prepared = bundles.prepare_bundle(self.output, cache_dir=self.cache)
        raw = json.loads(prepared["script"].read_text())
        self.assertEqual(raw["diagrams"]["d"]["svg"], "assets/0.svg")
        self.assertNotIn("unused", raw["diagrams"])
        self.assertEqual((prepared["script"].parent / "assets/0.svg").read_bytes(), (assets / "d.svg").read_bytes())

    def test_unallowed_with_code_falls_back_and_strict_writes_nothing(self):
        (self.project / "LICENSE").write_text("All rights reserved.")
        result = self.export(with_code=True)
        self.assertFalse(result["codeIncluded"])
        self.assertIn("not one canonical allowed licence", result["note"])
        output = self.directory / "not-created/strict.zip"
        with self.assertRaisesRegex(bundles.BundleError, "--strict"):
            bundles.export_bundle(self.script, output, with_code=True, strict=True)
        self.assertFalse(output.parent.exists())

    def test_no_overwrite(self):
        self.output.write_bytes(b"keep me")
        with self.assertRaisesRegex(bundles.BundleError, "overwrite"):
            self.export()
        self.assertEqual(self.output.read_bytes(), b"keep me")

    def test_code_and_reference_variants_do_not_overwrite_an_active_cache(self):
        self.export(with_code=True)
        with contextlib.redirect_stdout(io.StringIO()):
            first = bundles.prepare_bundle(self.output, cache_dir=self.cache)
        original = first["script"].read_bytes()
        reference = self.directory / "reference.zip"
        bundles.export_bundle(self.script, reference)
        with contextlib.redirect_stdout(io.StringIO()):
            second = bundles.prepare_bundle(reference, self.project, self.cache)
            again = bundles.prepare_bundle(self.output, cache_dir=self.cache)
        self.assertNotEqual(first["script"], second["script"])
        self.assertIn(".variants", second["script"].parts)
        self.assertEqual(again["script"].read_bytes(), original)
        self.assertEqual(first["script"].read_bytes(), original)

    def test_local_project_hashes_checked_and_mismatch_never_falls_back(self):
        self.export()
        with contextlib.redirect_stdout(io.StringIO()):
            prepared = bundles.prepare_bundle(self.output, self.project, self.cache)
        self.assertEqual(prepared["root"], self.project.resolve())
        (self.project / "src/main.py").write_text("changed")
        with patch.object(bundles, "download_sources", side_effect=AssertionError("no fallback on mismatch")), \
             self.assertRaisesRegex(bundles.BundleError, "checksum mismatch"):
            bundles.prepare_bundle(self.output, self.project, self.cache)

    def test_tampered_payload_manifest_and_cached_files_are_rejected(self):
        self.export(with_code=True)
        tampered = self.rewrite({"code/src/main.py": b"wrong"})
        with self.assertRaisesRegex(bundles.BundleError, "checksum mismatch"):
            bundles.prepare_bundle(tampered, cache_dir=self.cache)
        manifest = self.manifest()
        manifest["files"][0]["sha256"] = "0" * 64
        tampered = self.rewrite({"manifest.json": json.dumps(manifest).encode()})
        with self.assertRaisesRegex(bundles.BundleError, "checksum mismatch"):
            bundles.prepare_bundle(tampered, cache_dir=self.cache)
        other_cache = self.directory / "good-cache"
        with contextlib.redirect_stdout(io.StringIO()):
            prepared = bundles.prepare_bundle(self.output, cache_dir=other_cache)
        (prepared["root"] / "src/main.py").write_text("changed")
        with self.assertRaisesRegex(bundles.BundleError, "checksum mismatch"):
            bundles.prepare_bundle(self.output, cache_dir=other_cache)

    def test_unsafe_zip_entries_links_duplicates_and_collisions_are_rejected(self):
        self.export()
        for name in ("../escape", "/absolute", "C:/drive", "walk/../escape", "walk\\escape", "code/file:stream", "code/NUL", "code/file."):
            with self.subTest(path=name), self.assertRaises(bundles.BundleError):
                bundles.unpack_bundle(self.rewrite(additions=[(name, b"bad")]), self.cache)
        linked = zipfile.ZipInfo("code/link")
        linked.create_system = 3
        linked.external_attr = (stat.S_IFLNK | 0o777) << 16
        with self.assertRaises(bundles.BundleError):
            bundles.unpack_bundle(self.rewrite(additions=[(linked, b"../escape")]), self.cache)
        for name in ("README.txt", "readme.TXT"):
            with warnings.catch_warnings(), self.assertRaises(bundles.BundleError):
                warnings.simplefilter("ignore", UserWarning)
                bundles.unpack_bundle(self.rewrite(additions=[(name, b"duplicate")]), self.cache)

    def test_size_limits_and_invalid_walk_identity_are_rejected(self):
        self.export()
        with patch.object(bundles, "MAX_MEMBERS", 2), self.assertRaises(bundles.BundleError):
            bundles.export_bundle(self.script, self.directory / "too-many-members.zip")
        with patch.object(bundles, "MAX_FILE", 1024), self.assertRaises(bundles.BundleError):
            bundles.unpack_bundle(self.rewrite(additions=[("code/huge", b"x" * 1025)]), self.cache)
        manifest = self.manifest()
        manifest["walk"]["id"] = "../escape"
        with self.assertRaises(bundles.BundleError):
            bundles.unpack_bundle(self.rewrite({"manifest.json": json.dumps(manifest).encode()}), self.cache)

    def test_github_sources_are_pinned_and_credentials_are_not_exported(self):
        project = {"commit": "a" * 40, "sources": ["git@github.com:apache/ignite.git"]}
        self.assertEqual(bundles.raw_urls(project, "src/main.py"),
                         ["https://raw.githubusercontent.com/apache/ignite/" + "a" * 40 + "/src/main.py"])
        project["commit"] = "main"
        self.assertEqual(bundles.raw_urls(project, "src/main.py"), [])
        self.assertEqual(bundles.clean_remote("https://user:private@github.com/owner/repo.git?credential=private"),
                         "https://github.com/owner/repo.git")

    def test_player_loopback_bypasses_proxies_without_changing_external_requests(self):
        with patch.object(codewalk.urllib.request, "build_opener") as direct, \
             patch.object(codewalk.urllib.request, "urlopen") as external:
            for address in ("http://127.0.0.1:60865/api/state", "http://localhost:60865/api/state", "http://[::1]:60865/api/state"):
                codewalk.player_urlopen(address, timeout=2)
            self.assertEqual(direct.return_value.open.call_count, 3)
            external.assert_not_called()
            request = codewalk.urllib.request.Request("https://example.com/explicit-remote-player")
            codewalk.player_urlopen(request, timeout=3)
            external.assert_called_once_with(request, timeout=3)

    def test_git_reference_records_head_remote_and_project_subdirectory(self):
        responses = {("rev-parse", "HEAD"): "a" * 40, ("rev-parse", "--show-toplevel"): str(self.directory),
                     ("remote", "get-url", "origin"): "https://user:private@github.com/example/project.git"}
        with patch.object(bundles, "_git", side_effect=lambda root, *args: responses.get(args)):
            project = bundles.project_reference(self.raw["project"], self.project)
        self.assertEqual(project["kind"], "git")
        self.assertEqual(project["commit"], "a" * 40)
        self.assertEqual(project["sources"], ["https://github.com/example/project.git"])
        self.assertEqual(project["subdir"], "project")
        self.assertTrue(bundles.raw_urls(project, "src/main.py")[0].endswith("/project/src/main.py"))

    def test_modified_git_file_cannot_be_misrepresented_as_pinned_source(self):
        project = {"name": "fixture", "kind": "git", "subdir": "", "commit": "a" * 40,
                   "sources": [], "repository": None, "localOnly": True}
        with patch.object(bundles, "project_reference", return_value=project), \
             patch.object(bundles, "_git_file", side_effect=lambda root, project, path:
                          (self.project / "LICENSE").read_bytes() if path == "LICENSE" else None), \
             patch.object(bundles, "_git", side_effect=["pinned-object", "different-working-object"]), \
             self.assertRaisesRegex(bundles.BundleError, "differ from the pinned Git commit"):
            self.export(with_code=True)
        self.assertFalse(self.output.exists())

    def test_local_http_download_hashes_every_file_and_cache_is_reused(self):
        self.http_download(False)

    def test_local_http_tampered_download_is_not_kept_or_used(self):
        self.http_download(True)

    def http_download(self, tamper):
        payload = b"tampered" if tamper else self.source
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(self.path)
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                pass

        server = None
        for port in range(60902, 60920):
            try:
                server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
                break
            except OSError:
                continue
        self.assertIsNotNone(server, "no free local test port in 60902-60919")
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            project = {"name": "fixture", "kind": "example", "repository": "https://github.com/example/fixture.git",
                       "sources": ["https://github.com/example/fixture.git"], "commit": "a" * 40, "localOnly": False}
            with patch.object(bundles, "project_reference", return_value=project):
                self.export()
            url = f"http://127.0.0.1:{server.server_port}/src/main.py"
            with patch.object(bundles, "raw_urls", return_value=[url]), contextlib.redirect_stdout(io.StringIO()):
                if tamper:
                    with self.assertRaisesRegex(bundles.BundleError, "checksum mismatch"):
                        bundles.prepare_bundle(self.output, cache_dir=self.cache)
                    self.assertFalse((self.cache / "fixture-v3/project/src/main.py").exists())
                else:
                    prepared = bundles.prepare_bundle(self.output, cache_dir=self.cache)
                    self.assertEqual((prepared["root"] / "src/main.py").read_bytes(), self.source)
                    bundles.prepare_bundle(self.output, cache_dir=self.cache)
                    self.assertEqual(len(requests), 1)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
