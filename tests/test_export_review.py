"""Regressions for the independently reviewed export fixes; no external services."""
from concurrent.futures import ThreadPoolExecutor
import contextlib
import copy
from http.server import ThreadingHTTPServer
import io
import json
from pathlib import Path
import socket
import sys
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import bundles
import codewalk
from tests import test_export as fixtures


class ReviewFixes(unittest.TestCase):
    setUp = fixtures.Exports.setUp
    save_script = fixtures.Exports.save_script
    export = fixtures.Exports.export
    manifest = fixtures.Exports.manifest
    rewrite = fixtures.Exports.rewrite

    def diagram(self):
        assets = self.walk / "assets"
        assets.mkdir(exist_ok=True)
        (assets / "d.puml").write_text("@startuml\nrectangle Shape as shape\n@enduml\n", encoding="utf-8")
        safe = (b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">'
                b'<defs><path id="shape"/></defs><use href="#shape"/><use xlink:href="&#35;shape"/></svg>')
        (assets / "d.svg").write_bytes(safe)
        self.raw["diagrams"] = {"d": {"title": "Diagram", "source": "assets/d.puml", "svg": "assets/d.svg"}}
        self.raw["chapters"][0]["items"][0]["phrases"][0]["diagram"] = "d"
        self.save_script()
        return safe

    def test_e01_active_svg_and_encoded_links_are_rejected_before_publication(self):
        self.diagram()
        self.export(with_code=True)
        cases = [b'<svg><script>alert(1)</script></svg>', b'<svg><foreignObject/></svg>', b'<svg><set/></svg>',
                 b'<svg><animate/></svg>', b'<svg><animateMotion/></svg>', b'<svg><animateTransform/></svg>',
                 b'<svg><animateColor/></svg>', b'<svg onload="alert(1)"/>', b'<svg><path OnClick="alert(1)"/></svg>',
                 b'<svg><a href="java&#x09;script:alert(1)"/></svg>', b'<svg><image href="data:image/svg+xml,evil"/></svg>',
                 b'<svg><use href="https://example.invalid/tracker"/></svg>', b'<svg><use href="&#104;ttps://example.invalid/"/></svg>',
                 b'<svg xmlns:xlink="http://www.w3.org/1999/xlink"><use xlink:href="file:///secret"/></svg>',
                 b'<!DOCTYPE svg [<!ENTITY expanded "#shape">]><svg><use href="&expanded;"/></svg>']
        for svg in cases:
            with self.subTest(svg=svg):
                manifest = self.manifest()
                path = "walk/assets/0.svg"
                manifest["members"][path] = {"sha256": bundles.digest(svg), "bytes": len(svg)}
                bad = self.rewrite({path: svg, "manifest.json": json.dumps(manifest).encode()})
                with self.assertRaises(bundles.BundleError):
                    bundles.unpack_bundle(bad, self.cache)
                self.assertFalse((self.cache / "fixture-v3").exists())

    def test_e01_fragment_only_svg_survives_a_real_bundle_round_trip(self):
        safe = self.diagram()
        self.export(with_code=True)
        with contextlib.redirect_stdout(io.StringIO()):
            prepared = bundles.prepare_bundle(self.output, cache_dir=self.cache)
        self.assertEqual((prepared["script"].parent / "assets/0.svg").read_bytes(), safe)

    def test_e02_e04_restrictions_anywhere_override_standard_grants(self):
        apache = (ROOT / "third_party/APACHE-2.0.txt").read_text(encoding="utf-8")
        restricted = [apache + "\nCommons Clause: you may not sell the software.",
                      fixtures.MIT.replace("Example Authors", "Example Authors. Commercial use is prohibited.")]
        restricted += [apache + "\n" + term for term in ("Business Source License", "POLYFORM", "Server Side Public License",
                       "Elastic License", "non-commercial", "noncommercial", "not permitted to sell", "may not sell")]
        for text in restricted:
            with self.subTest(restriction=text[-100:]):
                self.assertNotIn(bundles.license_id(text), bundles.ALLOWED)
        self.assertEqual(bundles.license_id(apache), "Apache-2.0")
        self.assertEqual(bundles.license_id(fixtures.MIT), "MIT")

    def git_project(self):
        return {"name": "fixture", "kind": "git", "subdir": "", "commit": "a" * 40,
                "repository": None, "sources": [], "localOnly": True}

    def test_e03_crlf_local_project_reports_fix_without_normalising(self):
        self.export()
        crlf = self.source.replace(b"\n", b"\r\n")
        (self.project / "src/main.py").write_bytes(crlf)
        with self.assertRaises(bundles.BundleError) as caught:
            bundles.prepare_bundle(self.output, self.project, self.cache)
        for word in ("line endings differ", "CRLF vs LF", "core.autocrlf=false", "fresh clone"):
            self.assertIn(word, str(caught.exception))
        self.assertEqual((self.project / "src/main.py").read_bytes(), crlf)

    def test_e03_crlf_git_export_names_line_endings_and_refuses_output(self):
        crlf = self.source.replace(b"\n", b"\r\n")
        (self.project / "src/main.py").write_bytes(crlf)
        committed = {"LICENSE": (self.project / "LICENSE").read_bytes(), "src/main.py": self.source}
        with patch.object(bundles, "project_reference", return_value=self.git_project()), \
             patch.object(bundles, "_git_file", side_effect=lambda root, project, path: committed.get(path)), \
             patch.object(bundles, "_git", side_effect=["pinned", "working-crlf"]), \
             self.assertRaises(bundles.BundleError) as caught:
            self.export()
        self.assertIn("line endings differ", str(caught.exception))
        self.assertIn("core.autocrlf=false", str(caught.exception))
        self.assertFalse(self.output.exists())

    def test_e05_pinned_licence_and_notice_are_used_and_dirty_copies_refused(self):
        (self.project / "LICENSE").write_bytes(fixtures.MIT.encode())
        (self.project / "NOTICE").write_bytes(b"Pinned project notice\n")
        committed = {"LICENSE": fixtures.MIT.encode(), "NOTICE": b"Pinned project notice\n"}
        with patch.object(bundles, "project_reference", return_value=self.git_project()), \
             patch.object(bundles, "_git_file", side_effect=lambda root, project, path: committed.get(path)) as pinned, \
             patch.object(bundles, "_git", return_value="matching-object"):
            self.export(with_code=True)
        self.assertTrue(any(call.args[-1] == "LICENSE" for call in pinned.call_args_list))
        self.assertTrue(any(call.args[-1] == "NOTICE" for call in pinned.call_args_list))
        import zipfile
        with zipfile.ZipFile(self.output) as archive:
            self.assertEqual(archive.read("LICENSES/LICENSE"), committed["LICENSE"])
            self.assertEqual(archive.read("LICENSES/NOTICE"), committed["NOTICE"])
        for path in ("LICENSE", "NOTICE"):
            (self.project / path).write_bytes(b"Uncommitted change\n")
            with patch.object(bundles, "project_reference", return_value=self.git_project()), \
                 patch.object(bundles, "_git_file", side_effect=lambda root, project, file: committed.get(file)), \
                 self.assertRaisesRegex(bundles.BundleError, "licence/NOTICE differs"):
                bundles.export_bundle(self.script, self.directory / (path + ".zip"), with_code=True)
            (self.project / path).write_bytes(committed[path])

    def test_e05_git_show_reads_the_pinned_path_with_a_size_bound(self):
        from types import SimpleNamespace
        with patch.object(bundles, "_git", return_value="3"), \
             patch.object(bundles.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout=b"MIT")) as command:
            self.assertEqual(bundles._git_file(self.project, {"commit": "a" * 40, "subdir": "module"}, "LICENSE"), b"MIT")
        self.assertIn("a" * 40 + ":module/LICENSE", command.call_args.args[0])
        self.assertIn("show", command.call_args.args[0])
        with patch.object(bundles, "_git", return_value=str(bundles.MAX_FILE + 1)), \
             self.assertRaises(bundles.BundleError):
            bundles._git_file(self.project, self.git_project(), "LICENSE")

    def test_e06_dot_owner_repo_and_encoded_subdir_traversal_are_refused(self):
        for source in ("https://github.com/./repo", "https://github.com/../repo", "https://github.com/owner/.",
                       "https://github.com/owner/..", "https://github.com/.owner/repo", "https://github.com/owner/.repo"):
            self.assertEqual(bundles.raw_urls({"commit": "a" * 40, "sources": [source]}, "src/main.py"), [])
        with self.assertRaises(bundles.BundleError):
            bundles.raw_urls({"commit": "a" * 40, "sources": [], "subdir": "%2e%2e"}, "src/main.py")

    def test_e07_wrong_typed_manifest_fields_have_clear_errors(self):
        self.export()
        cases = [("project", "subdir", 5), ("project", "example", ["x"]), ("project", "sources", [None]),
                 ("project", "repository", []), ("project", "commit", {}), ("project", "localOnly", "true"),
                 ("walk", "id", []), ("walk", "title", {}), ("license", "id", []), ("license", "file", 5)]
        for section, key, value in cases:
            manifest = self.manifest()
            manifest[section][key] = value
            with self.subTest(field=section + "." + key), self.assertRaisesRegex(bundles.BundleError, section + r"\." + key):
                bundles.unpack_bundle(self.rewrite({"manifest.json": json.dumps(manifest).encode()}), self.cache)
        manifest = self.manifest()
        manifest["voice"] = []
        with self.assertRaisesRegex(bundles.BundleError, "voice"):
            bundles.validate_manifest(manifest)

    def test_e08_concurrent_unpacks_verify_and_share_the_atomic_winner(self):
        self.export(with_code=True)
        barrier = threading.Barrier(2)
        rename = Path.rename

        def simultaneous(source, target):
            if source.name == "payload":
                barrier.wait(timeout=10)
            return rename(source, target)

        with patch.object(Path, "rename", simultaneous), ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(bundles.unpack_bundle, self.output, self.cache) for _ in range(2)]
            results = [future.result(timeout=15) for future in futures]
        self.assertEqual(results[0][0], results[1][0])
        self.assertEqual((results[0][0] / "code/src/main.py").read_bytes(), self.source)
        self.assertEqual(list(self.cache.glob(".bundle-*")), [])

    def test_e09_expected_errors_keep_json_but_programming_errors_propagate(self):
        args = ["export", "--script", str(self.script), "--out", str(self.output)]
        for error in (ValueError("bad input"), OSError("cannot read")):
            with patch.object(bundles, "export_bundle", side_effect=error), contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(codewalk.main(args), 1)
            self.assertEqual(json.loads(output.getvalue())["status"], "FAIL")
        for error in (RuntimeError("unexpected bug"), TypeError("unexpected type bug")):
            with patch.object(bundles, "export_bundle", side_effect=error), self.assertRaises(type(error)):
                codewalk.main(args)

    @contextlib.contextmanager
    def server(self):
        self.diagram()
        folder = self.directory / "player-run"
        folder.mkdir()
        player = codewalk.Player(codewalk.load_script(self.script), folder, codewalk.VOICES[0], 1, False, self.script)
        self.addCleanup(player.trace_f.close)
        base = codewalk.make_handler(player)
        nodelay = []

        class Observed(base):
            def setup(self):
                super().setup()
                nodelay.append(self.connection.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY))

        server = None
        for port in range(60867, 60880):
            try:
                server = ThreadingHTTPServer(("127.0.0.1", port), Observed)
                break
            except OSError:
                continue
        self.assertIsNotNone(server)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}", player, nodelay
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=5)

    def test_e01_svg_headers_are_restricted_without_a_main_page_csp(self):
        with self.server() as (url, _, nodelay):
            headers, _ = self.http_response(url, "/diagram/d.svg")
            self.assertEqual(headers["content-security-policy"],
                             "default-src 'none'; style-src 'unsafe-inline'; img-src data:")
            self.assertEqual(headers["x-content-type-options"], "nosniff")
            headers, _ = self.http_response(url, "/")
            self.assertNotIn("content-security-policy", headers)
        self.assertTrue(all(nodelay))

    def http_response(self, url, path):
        # Check the server wire contract independently of the Windows urllib reader.
        port = int(url.rsplit(":", 1)[1])
        with socket.create_connection(("127.0.0.1", port), timeout=5) as connection:
            connection.sendall(f"GET {path} HTTP/1.0\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n".encode())
            data = bytearray()
            while True:
                try:
                    part = connection.recv(8192)
                except TimeoutError as error:
                    head = bytes(data).partition(b"\r\n\r\n")[0]
                    raise AssertionError(f"HTTP read timeout after {len(data)} bytes; headers: {head!r}; tail: {bytes(data[-150:])!r}") from error
                if not part:
                    break
                data.extend(part)
                if b"\r\n\r\n" in data:
                    header, body = bytes(data).split(b"\r\n\r\n", 1)
                    expected = next(int(line.split(b":", 1)[1]) for line in header.split(b"\r\n") if line.lower().startswith(b"content-length:"))
                    if len(body) == expected:
                        break
        header, body = bytes(data).split(b"\r\n\r\n", 1)
        self.assertTrue(header.startswith(b"HTTP/1.0 200"))
        fields = dict(line.decode("latin1").split(":", 1) for line in header.split(b"\r\n")[1:])
        fields = {key.lower(): value.strip() for key, value in fields.items()}
        self.assertEqual(int(fields["content-length"]), len(body))
        return fields, body

    def test_e12_json_headers_and_utf8_body_use_one_write(self):
        class Spy(io.BytesIO):
            def __init__(self):
                super().__init__()
                self.calls = 0

            def write(self, data):
                self.calls += 1
                return super().write(data)

        handler_type = codewalk.make_handler(None)
        handler = handler_type.__new__(handler_type)
        handler.request_version = "HTTP/1.1"
        handler.requestline = "GET /api/state HTTP/1.1"
        handler.command = "GET"
        handler.wfile = Spy()
        payload = {"large": "narration λ " * 10000}
        handler.send_json(payload)
        self.assertEqual(handler.wfile.calls, 1)
        headers, body = handler.wfile.getvalue().split(b"\r\n\r\n", 1)
        self.assertIn(f"Content-Length: {len(body)}".encode(), headers)
        self.assertEqual(json.loads(body), payload)

    def test_e12_real_http_response_has_nodelay_and_complete_json(self):
        with self.server() as (url, player, nodelay):
            player.last_phrase = {"phrase": {"id": "p1", "text": "Caption λ"}}
            _, data = self.http_response(url, "/api/state")
            self.assertEqual(json.loads(data)["state"]["total"], 1)
        self.assertTrue(nodelay and all(nodelay))


if __name__ == "__main__":
    unittest.main()
