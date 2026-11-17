"""Offline regressions for chained amendments, narration accounting and view-mode playback."""
import argparse
import contextlib
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import bootstrap
import codewalk


class WalkRegressions(unittest.TestCase):
    def setUp(self):
        allowed = patch.object(codewalk.consent, "decision", return_value=True)
        allowed.start(); self.addCleanup(allowed.stop)
        base = ROOT / "runs" / "player-unit"
        base.mkdir(parents=True, exist_ok=True)
        temp = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name)
        self.raw = {
            "schema": "codewalk-script-v1", "id": "fixture", "version": 1, "title": "Fixture",
            "project": {"name": "fixture", "root": str(self.directory)}, "defaults": {"gapMs": 0},
            "chapters": [
                {"id": "c1", "title": "One", "items": [{"id": "i1", "title": "One", "phrases": [
                    {"id": "p1", "text": "First phrase", "pauseAfter": True},
                    {"id": "p2", "text": "Second phrase"}]}]},
                {"id": "c2", "title": "Two", "items": [{"id": "i2", "title": "Two", "phrases": [
                    {"id": "p3", "text": "Third phrase"}]}]},
            ],
        }
        self.script = self.write("demo.walk.json", self.raw)
        self.patch = self.write("patch.json", {"reason": "test", "quote": "correct p1", "by": "unit test",
                                               "ops": [{"op": "replace_text", "phrase": "p1", "text": "Corrected"}]})

    def write(self, name, data):
        path = self.directory / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_repeated_amends_use_one_original_stem_and_latest_is_selected(self):
        original = self.script.read_bytes()
        current = self.script
        for version in (2, 3, 4):
            result = codewalk.amend(current, self.patch)
            self.assertEqual(result["status"], "PASS")
            current = Path(result["out"])
            self.assertEqual(current.name, f"demo.v{version}.walk.json")
            self.assertEqual(json.loads(current.read_text())["parentVersion"], version - 1)
        with patch.object(bootstrap, "HERE", self.directory):
            self.assertEqual(bootstrap.latest_version("demo.walk.json"), (current, 4))
        self.assertEqual(self.script.read_bytes(), original)
        self.assertEqual(len((self.directory / "changelog.jsonl").read_text().splitlines()), 3)

    def test_legacy_nested_versions_are_read_and_amend_to_canonical_name(self):
        old = self.write("demo.v2.v3.walk.json", {**self.raw, "version": 3, "parentVersion": 2})
        self.write("demo.v2.walk.json", {**self.raw, "version": 2})
        self.write("demo.vbad.walk.json", self.raw)
        self.write("other.v99.walk.json", self.raw)
        with patch.object(bootstrap, "HERE", self.directory):
            self.assertEqual(bootstrap.latest_version("demo.walk.json"), (old, 3))
            canonical = self.write("demo.v3.walk.json", {**self.raw, "version": 3})
            self.assertEqual(bootstrap.latest_version("demo.walk.json"), (canonical, 3))
            result = codewalk.amend(old, self.patch)
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(Path(result["out"]).name, "demo.v4.walk.json")
            self.assertEqual(bootstrap.latest_version("demo.walk.json"), (Path(result["out"]), 4))

    def test_old_standalone_v_files_remain_readable(self):
        self.write("v1.walk.json", self.raw)
        old = self.write("v2.walk.json", {**self.raw, "version": 2})
        with patch.object(bootstrap, "HERE", self.directory):
            self.assertEqual(bootstrap.latest_version("v1.walk.json"), (old, 2))
            result = codewalk.amend(old, self.patch)
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(Path(result["out"]).name, "v1.v3.walk.json")
            self.assertEqual(bootstrap.latest_version("v1.walk.json"), (Path(result["out"]), 3))

    def test_amend_never_overwrites_an_existing_version(self):
        first = codewalk.amend(self.script, self.patch)
        path = Path(first["out"])
        before = path.read_bytes()
        result = codewalk.amend(self.script, self.patch)
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("exists", result["error"])
        self.assertEqual(path.read_bytes(), before)

    def test_narration_counts_new_cached_and_duplicate_clips(self):
        raw = copy.deepcopy(self.raw)
        raw["chapters"][0]["items"][0]["phrases"][1]["text"] = "First phrase"
        self.write(self.script.name, raw)
        cache = self.directory / "cache"
        cache.mkdir()
        voice = codewalk.VOICES[0]
        with patch.object(codewalk, "CACHE", cache):
            mp3, meta = codewalk.clip_paths("Third phrase", voice)
            mp3.write_bytes(b"cached audio")
            meta.write_text(json.dumps({"durationSec": 1}), encoding="utf-8")
            with patch.object(codewalk, "speech_creds", return_value=("unused", "unused")), \
                 patch.object(codewalk.THROTTLE, "acquire"), patch.object(codewalk, "audio_duration", return_value=1), \
                 patch.object(codewalk.urllib.request, "urlopen", return_value=io.BytesIO(b"new audio")) as network, \
                 contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(codewalk.cmd_tts(argparse.Namespace(script=self.script, voices=voice)), 0)
            summary = json.loads(output.getvalue().splitlines()[-1])
            self.assertEqual(summary, {"status": "PASS", "audio": 3, "created": 1, "cached": 2})
            network.assert_called_once()
            new_meta = codewalk.clip_paths("First phrase", voice)[1]
            self.assertNotIn("cached", json.loads(new_meta.read_text()))
            with patch.object(codewalk, "speech_creds", side_effect=AssertionError("cached playback needs no key")), \
                 contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(codewalk.cmd_tts(argparse.Namespace(script=self.script, voices=voice)), 0)
            self.assertEqual(json.loads(output.getvalue().splitlines()[-1]),
                             {"status": "PASS", "audio": 3, "created": 0, "cached": 3})

    def player(self, view):
        run = self.directory / "run"
        run.mkdir()
        player = codewalk.Player(codewalk.load_script(self.script), run, codewalk.VOICES[0], 1, False,
                                 self.script, auto_continue=view)
        player.positions_dir = self.directory / "positions"
        self.addCleanup(player.trace_f.close)
        return player

    def test_view_mode_plays_through_pause_after_and_chapter_end(self):
        player = self.player(True)

        class InlineThread:
            def __init__(self, target, args=(), **kwargs):
                self.target, self.args = target, args

            def start(self):
                self.target(*self.args)

        with patch.object(codewalk, "tts", return_value=(self.directory / "clip.mp3", {"durationSec": 1})), \
             patch.object(codewalk.threading, "Thread", InlineThread):
            player.start_phrase(0, "test")
            for index in range(3):
                self.assertEqual((player.idx, player.status), (index, "playing"))
                player.page_event({"event": "audio-ended", "kind": "phrase", "token": player.token})
            self.assertEqual(player.status, "finished")

    def test_interactive_mode_keeps_its_requested_pause(self):
        player = self.player(False)
        with patch.object(codewalk, "tts", return_value=(self.directory / "clip.mp3", {"durationSec": 1})):
            player.start_phrase(0, "test")
            player.page_event({"event": "audio-ended", "kind": "phrase", "token": player.token})
        self.assertEqual((player.idx, player.status), (0, "paused"))


if __name__ == "__main__":
    unittest.main()
