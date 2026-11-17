"""Selected safety fixes: external services are mocked, private ports and consent files only."""
import argparse
import contextlib
import copy
from http.server import ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import queue
import secrets
import socket
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import bootstrap
import bundles
import codewalk
import consent
import process_identity
import walk_schema
from tests import test_export


class Base(unittest.TestCase):
    def setUp(self):
        folder = ROOT / "runs/p1/unit"
        folder.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=folder)
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        env = patch.dict(os.environ, {"CODEWALK_CONSENT_FILE": str(self.directory / "consent.json")})
        env.start(); self.addCleanup(env.stop)
        self.raw = {"schema": "codewalk-script-v1", "id": "p1", "title": "Fixture", "version": 1,
                    "project": {"root": str(self.directory)},
                    "chapters": [{"id": "c", "title": "C", "items": [{"id": "i", "title": "I",
                                    "phrases": [{"id": "p", "text": "Caption works without cloud speech"}]}]}]}
        self.script = self.directory / "fixture.walk.json"
        self.save()

    def save(self):
        self.script.write_text(json.dumps(self.raw), encoding="utf-8")

    def player(self):
        player = codewalk.Player(codewalk.load_script(self.script), self.directory, codewalk.VOICES[0], 1, False, self.script)
        player.positions_dir = self.directory / "positions"
        self.addCleanup(player.trace_f.close)
        return player

    @contextlib.contextmanager
    def server(self):
        player = self.player()
        for port in range(60902, 60921):
            try:
                server = ThreadingHTTPServer(("127.0.0.1", port), codewalk.make_handler(player))
                break
            except OSError:
                continue
        else:
            self.fail("No authorized test port is free")
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield player, f"http://127.0.0.1:{server.server_port}", server
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=5)

    def post(self, url, path, value, extra=None):
        request = urllib.request.Request(url + path, data=json.dumps(value).encode(), method="POST",
                                        headers={"X-Codewalk": "1", "Content-Type": "application/json", **(extra or {})})
        with codewalk.player_urlopen(request, timeout=3) as response:
            return json.loads(response.read())


class Structure(Base):
    def invalid(self, raw, message):
        self.script.write_text(json.dumps(raw), encoding="utf-8")
        result = codewalk.validate(raw)
        self.assertEqual(result["status"], "FAIL")
        with self.assertRaises(walk_schema.InvalidWalk) as caught:
            codewalk.load_script(self.script)
        self.assertIn(message, str(caught.exception))
        self.assertEqual(caught.exception.findings, result["findings"])
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(codewalk.main(["validate", "--script", str(self.script)]), 1)
        self.assertEqual(json.loads(output.getvalue())["findings"], result["findings"])
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(codewalk.main(["serve", "--script", str(self.script), "--port", "60902", "--no-ide"]), 1)
        self.assertEqual(json.loads(output.getvalue())["error"], str(caught.exception))

    def test_empty_walk_chapter_and_item_are_refused_consistently(self):
        for place, field, message in ((self.raw, "chapters", "walk has no chapters"),
                                     (self.raw["chapters"][0], "items", "has no items"),
                                     (self.raw["chapters"][0]["items"][0], "phrases", "has no phrases")):
            original = place[field]
            place[field] = []
            with self.subTest(field=field):
                self.invalid(self.raw, message)
            place[field] = original

    def test_duplicate_ids_at_each_level_are_refused(self):
        for kind in ("chapter", "item", "phrase"):
            raw = copy.deepcopy(self.raw)
            values = raw["chapters"] if kind == "chapter" else raw["chapters"][0]["items"] if kind == "item" else raw["chapters"][0]["items"][0]["phrases"]
            values.append(copy.deepcopy(values[0]))
            with self.subTest(kind=kind):
                self.invalid(raw, "duplicate " + kind + " id")

    def test_wrong_types_are_findings_not_tracebacks(self):
        for field, bad in (("chapters", {}), ("project", []), ("defaults", []), ("diagrams", []), ("title", 4), ("id", []), ("version", True)):
            raw = {**self.raw, field: bad}
            with self.subTest(field=field):
                self.invalid(raw, field)
        for kind, field in (("chapter", "items"), ("item", "phrases"), ("phrase", "text"), ("phrase", "id")):
            raw = copy.deepcopy(self.raw)
            place = raw["chapters"][0]
            if kind != "chapter": place = place["items"][0]
            if kind == "phrase": place = place["phrases"][0]
            place[field] = 5
            with self.subTest(kind=kind, field=field): self.invalid(raw, field)


class LicenceRules(unittest.TestCase):
    setUp = test_export.Exports.setUp
    save_script = test_export.Exports.save_script
    export = test_export.Exports.export
    manifest = test_export.Exports.manifest

    def test_apache_with_or_without_appendix_and_exact_other_templates(self):
        apache = (ROOT / "third_party/APACHE-2.0.txt").read_text(encoding="utf-8")
        self.assertEqual(bundles.license_id(apache), "Apache-2.0")
        self.assertEqual(bundles.license_id(apache.split("APPENDIX:")[0]), "Apache-2.0")
        for body in (test_export.MIT, test_export.ISC, test_export.BSD_HEAD + test_export.BSD_TAIL,
                     test_export.BSD_HEAD + test_export.BSD_THIRD + test_export.BSD_TAIL):
            self.assertIn(bundles.license_id(body), bundles.ALLOWED)
            self.assertNotIn(bundles.license_id(body + "\nApproval from the creator is required before redistribution."), bundles.ALLOWED)

    def test_reworded_apache_restriction_falls_back_names_file_and_strict_refuses(self):
        text = (ROOT / "third_party/APACHE-2.0.txt").read_text(encoding="utf-8") + "\nApproval from the creator is required before redistribution."
        self.assertIsNone(bundles.DENIED_LICENSE_TERMS.search(text))
        (self.project / "LICENSE").write_text(text, encoding="utf-8")
        result = self.export(with_code=True)
        self.assertFalse(result["codeIncluded"])
        self.assertIn("src/main.py", result["note"])
        self.assertIn("cannot tell which terms cover it", result["note"])
        strict = self.directory / "strict.zip"
        with self.assertRaisesRegex(bundles.BundleError, "Apache header"):
            bundles.export_bundle(self.script, strict, with_code=True, strict=True)
        self.assertFalse(strict.exists())

    def test_extra_apache_requires_every_file_header_and_records_rule(self):
        apache = (ROOT / "third_party/APACHE-2.0.txt").read_text(encoding="utf-8")
        (self.project / "LICENSE").write_text(apache + "\nSubcomponents: consult each file for terms.", encoding="utf-8")
        (self.project / "src/main.py").write_bytes(b"# Licensed under the Apache License, Version 2.0 (the \"License\");\n" + self.source)
        result = self.export(with_code=True)
        self.assertTrue(result["codeIncluded"])
        self.assertEqual(self.manifest()["license"]["rule"], "per-file-headers")
        bundles.unpack_bundle(self.output, self.cache)
        self.assertFalse(bundles.apache_header(b"\n" * 40 + b"Licensed under the Apache License, Version 2.0"))
        self.assertFalse(bundles.apache_header(b"SPDX-License-Identifier: Apache-2.0"))
        self.assertFalse(bundles.apache_header(b"This file is NOT Licensed under the Apache License, Version 2.0"))

    def test_two_root_licences_are_ambiguous_even_if_identical(self):
        (self.project / "LICENSE.txt").write_text(test_export.MIT, encoding="utf-8")
        result = self.export(with_code=True)
        self.assertFalse(result["codeIncluded"])
        self.assertIn("Multiple root licence", result["note"])

    def test_two_grants_or_unrecognized_prefix_cannot_hide_in_copyright(self):
        for text in (test_export.MIT + test_export.MIT, test_export.MIT + test_export.ISC,
                     test_export.MIT.replace("Permission is hereby", "Creator approval is required.\nPermission is hereby")):
            self.assertNotIn(bundles.license_id(text), bundles.ALLOWED)


class Privacy(Base):
    def test_azure_yes_is_asked_once_before_mock_synthesis(self):
        with patch("builtins.input", return_value="yes") as ask, \
             patch.object(bootstrap, "key_state", return_value="ready"), \
             patch.object(codewalk, "KEY_FILE", self.directory / "unused-key.env"), \
             patch.object(codewalk, "tts", return_value=(self.directory / "test.mp3", {"durationSec": 1})) as tts, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(bootstrap.main(["azure", "--test"]), 0)
            self.assertEqual(bootstrap.main(["azure", "--test"]), 0)
        ask.assert_called_once(); self.assertEqual(tts.call_count, 2)
        self.assertTrue(consent.decision("azure"))

    def test_explicit_claude_is_only_run_consent_and_default_stays_off(self):
        consent.record(claude=False)
        for extra, expected in (([], "off"), (["--answerer", "claude"], "claude (sonnet)")):
            with patch.object(codewalk, "ThreadingHTTPServer") as server, patch("signal.signal"), \
                 contextlib.redirect_stdout(io.StringIO()) as output:
                server.return_value.serve_forever.side_effect = KeyboardInterrupt
                self.assertEqual(codewalk.main(["serve", "--script", str(self.script), "--no-ide", "--port", "60902",
                                               "--run-dir", str(self.directory), "--from-start", *extra]), 0)
            self.assertEqual(json.loads(output.getvalue())["answerer"], expected)
            self.assertFalse(consent.decision("claude"))

    def test_azure_asks_once_and_no_blocks_cache_and_stt(self):
        with patch("builtins.input", return_value="no") as ask, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(bootstrap.main(["azure"]), 0)
            self.assertEqual(bootstrap.main(["azure"]), 0)
        ask.assert_called_once()
        self.assertIn("Microsoft Azure Speech", ask.call_args.args[0])
        self.assertFalse(consent.decision("azure"))
        with patch.object(codewalk, "speech_creds") as credentials, patch.object(codewalk.subprocess, "run") as external:
            with self.assertRaises(consent.Required): codewalk.tts("text", codewalk.VOICES[0])
            with self.assertRaises(consent.Required): codewalk.stt(b"audio")
        credentials.assert_not_called(); external.assert_not_called()

    def test_undecided_noninteractive_azure_stays_undecided(self):
        with patch("builtins.input", side_effect=EOFError), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(bootstrap.main(["azure", "--test"]), 1)
        self.assertIsNone(consent.decision("azure"))

    def test_yes_and_no_decisions_preserve_other_provider_and_timestamp(self):
        with contextlib.redirect_stdout(io.StringIO()):
            bootstrap.main(["consent", "--azure", "yes"])
            bootstrap.main(["consent", "--claude", "no"])
        self.assertEqual(consent.read(), {"azure": True, "claude": False})
        saved = json.loads(consent.path().read_text())
        self.assertIn("decidedAt", saved)
        self.assertNotIn("key", saved)

    def test_no_consent_still_publishes_caption_and_text_answer(self):
        player = self.player()
        with patch.object(codewalk, "tts") as tts:
            player.start_phrase(0, "test")
            self.assertEqual(player.last_phrase["phrase"]["text"], self.raw["chapters"][0]["items"][0]["phrases"][0]["text"])
            self.assertIsNone(player.last_phrase["audio"])
            q = player.ask("Why?", "test")["question"]
            self.assertTrue(player.answer({"qid": q["id"], "text": "Local reply"}, "test")["ok"])
        tts.assert_not_called()

    def test_claude_endpoint_saves_once_decision_and_no_keeps_helper_off(self):
        with self.server() as (player, url, _):
            with patch.object(codewalk.shutil, "which", return_value="installed-claude"):
                result = self.post(url, "/api/consent", {"claude": False})
                self.assertFalse(result["consent"]["claude"])
                self.assertEqual(player.answerer, "off")
                self.post(url, "/api/consent", {"claude": True})
                self.assertEqual(player.answerer, "claude")
            consent.record(claude=False)
            with patch.object(player, "run_helper") as helper:
                player.ask("Keep it local", "test")
                helper.assert_not_called()

    def test_audio_endpoint_refuses_without_consent_before_conversion(self):
        with self.server() as (_, url, _), patch.object(codewalk, "stt") as stt:
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.post(url, "/api/ask-audio", {})
            self.assertEqual(error.exception.code, 403)
            error.exception.close()
            stt.assert_not_called()


class Stop(Base):
    def test_malformed_stale_state_is_removed_without_signaling(self):
        (self.directory / "player.json").write_text("{broken json")
        with patch.object(bootstrap, "STATE_DIR", self.directory), patch.object(bootstrap.os, "kill") as kill, \
             patch.object(bootstrap.subprocess, "run") as taskkill, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(bootstrap.main(["stop"]), 0)
        kill.assert_not_called(); taskkill.assert_not_called()
        self.assertFalse((self.directory / "player.json").exists())

    def test_background_check_redacts_instance_secret(self):
        info = {"pid": 1234, "url": "http://127.0.0.1:60902/", "instanceToken": secrets.token_urlsafe(32)}
        (self.directory / "player.json").write_text(json.dumps(info))
        with patch.object(bootstrap, "STATE_DIR", self.directory), patch.object(codewalk, "player_urlopen"):
            self.assertNotIn("instanceToken", bootstrap.background_player())

    def test_verified_unresponsive_player_is_only_pid_signaled(self):
        saved = {"pid": 1234, "processStart": "matching"}
        (self.directory / "player.json").write_text(json.dumps(saved))
        value = {"start": "matching", "args": [sys.executable, str(ROOT / "codewalk.py"), "serve"]}
        with patch.object(bootstrap, "STATE_DIR", self.directory), patch.object(process_identity, "identity", return_value=value), \
             patch.object(bootstrap.os, "kill") as kill, patch.object(bootstrap.subprocess, "run") as terminate, \
             contextlib.redirect_stdout(io.StringIO()):
            bootstrap.main(["stop"])
        if os.name == "nt":
            self.assertEqual(terminate.call_args.args[0], ["taskkill", "/PID", "1234", "/F"])
            kill.assert_not_called()
        else:
            kill.assert_called_once()
            terminate.assert_not_called()

    def test_stale_other_process_is_not_signaled_even_with_matching_start_time(self):
        info = {"pid": os.getpid(), "processStart": "matching"}
        (self.directory / "player.json").write_text(json.dumps(info))
        with patch.object(bootstrap, "STATE_DIR", self.directory), \
             patch.object(process_identity, "identity", return_value={"start": "matching", "args": [sys.executable, "unrelated.py"]}), \
             patch.object(bootstrap.os, "kill") as kill, patch.object(bootstrap.subprocess, "run") as taskkill, \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(bootstrap.main(["stop"]), 0)
        kill.assert_not_called(); taskkill.assert_not_called()
        self.assertIn("Killed nothing", output.getvalue())
        self.assertFalse((self.directory / "player.json").exists())

    def test_fallback_requires_both_matching_creation_time_and_player_command(self):
        for start, args in (("wrong-start", [str(ROOT / "codewalk.py"), "serve"]),
                            ("matching", [str(ROOT / "codewalk.py"), "validate"])):
            (self.directory / "player.json").write_text(json.dumps({"pid": 1234, "processStart": "matching"}))
            with patch.object(bootstrap, "STATE_DIR", self.directory), \
                 patch.object(process_identity, "identity", return_value={"start": start, "args": args}), \
                 patch.object(bootstrap.os, "kill") as kill, patch.object(bootstrap.subprocess, "run") as taskkill, \
                 contextlib.redirect_stdout(io.StringIO()):
                bootstrap.main(["stop"])
            kill.assert_not_called(); taskkill.assert_not_called()

    def test_shutdown_requires_instance_secret_and_loopback(self):
        with self.server() as (player, url, _):
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.post(url, "/api/shutdown", {}, {"X-Codewalk-Instance": "incorrect"})
            self.assertEqual(error.exception.code, 403)
            error.exception.close()
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.post(url, "/api/shutdown", {}, {"X-Codewalk-Instance": "non-ascii-é"})
            self.assertEqual(error.exception.code, 403)
            error.exception.close()
            self.assertTrue(self.post(url, "/api/shutdown", {}, {"X-Codewalk-Instance": player.instance_token})["ok"])

    def test_process_identity_reads_current_process_without_exposing_command(self):
        value = process_identity.identity(os.getpid())
        self.assertIsNotNone(value)
        self.assertTrue(value["start"])
        self.assertFalse(process_identity.is_player(value, ROOT / "codewalk.py"))
        self.assertFalse(process_identity.is_player({"args": [sys.executable, "-c", "pass", str(ROOT / "codewalk.py"), "serve"]}, ROOT / "codewalk.py"))


class Limits(Base):
    def test_caps_are_at_least_twice_measured_demo_workload(self):
        self.assertGreaterEqual(codewalk.MAX_JSON_BODY, 2 * 386)
        self.assertGreaterEqual(codewalk.MAX_AUDIO_BODY, 2 * 11520044)
        self.assertGreaterEqual(codewalk.MAX_SUBSCRIBERS, 2 * 3)
        self.assertGreaterEqual(codewalk.MAX_EVENT_QUEUE, 2 * 487)

    def test_oversized_json_and_audio_refused_from_headers_without_reading_body(self):
        with self.server() as (_, url, _):
            port = int(url.rsplit(":", 1)[1])
            for path, limit in (("/api/cmd", codewalk.MAX_JSON_BODY), ("/api/ask-audio", codewalk.MAX_AUDIO_BODY)):
                with socket.create_connection(("127.0.0.1", port), timeout=3) as connection:
                    connection.sendall(f"POST {path} HTTP/1.0\r\nX-Codewalk: 1\r\nContent-Length: {limit + 1}\r\n\r\n".encode())
                    result = connection.recv(4096)
                self.assertIn(b"413", result)
                self.assertIn(b"Request too large", result)

    def test_negative_duplicate_and_chunked_length_are_rejected(self):
        with self.server() as (_, url, _):
            port = int(url.rsplit(":", 1)[1])
            for headers in ("Content-Length: -1", "Content-Length: 1\r\nContent-Length: 2", "Transfer-Encoding: chunked"):
                with socket.create_connection(("127.0.0.1", port), timeout=3) as connection:
                    connection.sendall(f"POST /api/cmd HTTP/1.0\r\nX-Codewalk: 1\r\n{headers}\r\n\r\n".encode())
                    self.assertIn(b"400", connection.recv(4096))

    def test_slow_subscriber_is_evicted_without_blocking_other_subscribers(self):
        player = self.player()
        slow, fast = queue.Queue(maxsize=1), queue.Queue(maxsize=10)
        slow.closed = threading.Event(); fast.closed = threading.Event()
        player.subs.extend([slow, fast])
        player.emit({"type": "test"}); player.emit({"type": "test"})
        self.assertTrue(slow.closed.is_set())
        self.assertNotIn(slow, player.subs)
        self.assertEqual(slow.qsize(), 1)
        self.assertEqual(fast.qsize(), 2)

    def test_non_sound_tab_closing_frees_its_subscription_immediately(self):
        player = self.player()
        subscriber = queue.Queue(maxsize=codewalk.MAX_EVENT_QUEUE)
        subscriber.closed = threading.Event()
        player.subs.append(subscriber)
        player.sub_pages[id(subscriber)] = "closing-tab"
        player.page_event({"event": "page-closing", "pageId": "closing-tab"})
        self.assertTrue(subscriber.closed.is_set())
        self.assertNotIn(subscriber, player.subs)
        self.assertNotIn(id(subscriber), player.sub_pages)

    def test_concurrent_stream_cap_rejects_excess_with_clear_429(self):
        with self.server() as (player, url, _):
            player.subs.extend(queue.Queue() for _ in range(codewalk.MAX_SUBSCRIBERS))
            with self.assertRaises(urllib.error.HTTPError) as error:
                codewalk.player_urlopen(url + "/api/events", timeout=3)
            self.assertEqual(error.exception.code, 429)
            self.assertIn(b"Too many live tabs", error.exception.read())
            error.exception.close()


if __name__ == "__main__":
    unittest.main()
