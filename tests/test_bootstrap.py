"""Offline project/download regressions. Run: python -m unittest discover -s tests -p test_bootstrap.py."""
import argparse
import contextlib
import io
import itertools
import json
import pathlib
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import Mock, patch

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import bootstrap


class Projects(unittest.TestCase):
    def setUp(self):
        self.base = ROOT / "runs" / "bootstrap-unit"
        self.base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=self.base)
        self.addCleanup(self.temp.cleanup)
        self.directory = pathlib.Path(self.temp.name)
        self.demo = patch.object(bootstrap, "DEMO_DIR", self.directory / "demo")
        self.demo.start(); self.addCleanup(self.demo.stop)

    def archive(self, names=None):
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as z:
            for name, data in (names or {"ignite-source/pom.xml": b"<project/>\n", "ignite-source/bin/run.sh": b"#!/bin/sh\n"}).items():
                z.writestr(name, data)
        return out.getvalue()

    def args(self, **values):
        return argparse.Namespace(project="ignite", source="archive", force=False, writable=False, **values)

    def run_archive(self, data):
        with patch.object(bootstrap.urllib.request, "urlopen", return_value=io.BytesIO(data)), contextlib.redirect_stdout(io.StringIO()):
            return bootstrap.cmd_demo(self.args())

    def test_hash_prefix_and_git_metadata_exclusion(self):
        root = self.directory / "source"; root.mkdir()
        (root / "pom.xml").write_bytes(b"<project/>\n")
        expected_zip = io.BytesIO()
        with zipfile.ZipFile(expected_zip, "w") as z:
            z.writestr("github.com/apache/ignite@2.17.0/pom.xml", b"<project/>\n")
        with zipfile.ZipFile(expected_zip) as z:
            expected = bootstrap.module_h1(z)
        (root / ".git").mkdir(); (root / ".git" / "config").write_text("metadata")
        (root / ".codewalk-verified").write_text("marker")
        self.assertEqual(bootstrap.tree_h1(root, "github.com/apache/ignite", "2.17.0"), expected)
        self.assertNotEqual(bootstrap.tree_h1(root), expected, "MarketStore remains the no-argument prefix")

    def test_missing_ignite_does_not_gate_marketstore_or_start_player(self):
        folder = bootstrap.demo_root(); folder.mkdir(parents=True)
        (folder / "go.mod").write_text("module example")
        (folder / ".codewalk-verified").write_text(json.dumps(bootstrap.DEMO))
        self.assertTrue(bootstrap.demo_ready())
        self.assertFalse(bootstrap.demo_ready("ignite"))
        with patch.object(bootstrap.subprocess, "Popen", side_effect=AssertionError("must not start")), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(bootstrap.main(["run", "ignite", "--background", "--no-open"]), 1)
        self.assertIn("bootstrap.py demo ignite", output.getvalue())

    def test_default_demo_still_means_marketstore(self):
        folder = bootstrap.demo_root(); folder.mkdir(parents=True)
        (folder / "go.mod").write_text("module example")
        (folder / ".codewalk-verified").write_text(json.dumps(bootstrap.DEMO))
        with patch.object(bootstrap.urllib.request, "urlopen", side_effect=AssertionError("must not download")), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(bootstrap.main(["demo"]), 0)
        self.assertIn("already there and verified", output.getvalue())

    def test_both_project_markers_must_match_every_pin_field(self):
        for name, project in bootstrap.PROJECTS.items():
            folder = bootstrap.demo_root(name); folder.mkdir(parents=True)
            source = folder / ("go.mod" if name == "marketstore" else "pom.xml")
            source.write_text("source")
            marker = folder / ".codewalk-verified"
            pins = {key: project[key] for key in ("module", "version", "commit", "h1")}
            marker.write_text(json.dumps(pins))
            self.assertTrue(bootstrap.demo_ready(name), "existing markers need only the four pin fields")
            marker.write_text(json.dumps({k: v for k, v in pins.items() if k != "commit"}))
            self.assertTrue(bootstrap.demo_ready(name), "markers from an older bootstrap have no commit field")
            for key in pins:
                for invalid in ({**pins, key: "wrong"}, *([] if key == "commit" else [{k: v for k, v in pins.items() if k != key}])):
                    with self.subTest(project=name, field=key, marker=invalid):
                        marker.write_text(json.dumps(invalid))
                        self.assertFalse(bootstrap.demo_ready(name))
            for invalid in ("{}", "[]", "not json"):
                marker.write_text(invalid)
                self.assertFalse(bootstrap.demo_ready(name))
            marker.write_text(json.dumps(pins))
            source.unlink()
            self.assertFalse(bootstrap.demo_ready(name))

    def test_all_keeps_both_verified_projects_without_network(self):
        for name, project in bootstrap.PROJECTS.items():
            folder = bootstrap.demo_root(name); folder.mkdir(parents=True)
            (folder / ("go.mod" if name == "marketstore" else "pom.xml")).write_text("source")
            (folder / ".codewalk-verified").write_text(json.dumps(project))
        with patch.object(bootstrap.urllib.request, "urlopen", side_effect=AssertionError("must not download")), \
             patch.object(bootstrap, "demo_git", side_effect=AssertionError("must not fetch")), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(bootstrap.main(["demo", "all"]), 0)
        self.assertEqual(output.getvalue().count("already there and verified"), 2)

    def test_wrong_archive_checksum_keeps_nothing(self):
        self.assertEqual(self.run_archive(self.archive()), 1)
        self.assertFalse(bootstrap.demo_root("ignite").exists())
        self.assertFalse((bootstrap.DEMO_DIR / "ignite-2.17.0.partial").exists())
        self.assertFalse((bootstrap.DEMO_DIR / "ignite-2.17.0.zip.partial").exists())

    def test_archive_path_escape_refused_before_writing(self):
        self.assertEqual(self.run_archive(self.archive({"ignite-source/../../escape": b"bad"})), 1)
        self.assertFalse((self.directory / "escape").exists())
        self.assertFalse(bootstrap.demo_root("ignite").exists())

    def test_archive_requires_one_top_folder(self):
        data = self.archive({"one/pom.xml": b"one", "two/file": b"two"})
        self.assertEqual(self.run_archive(data), 1)
        self.assertFalse(bootstrap.demo_root("ignite").exists())

    def test_auto_falls_back_when_git_fetch_fails(self):
        with patch.object(bootstrap, "which", return_value="git"), patch.object(bootstrap, "demo_git", return_value=None), \
             patch.object(bootstrap, "demo_archive", return_value=0) as fallback, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(bootstrap.main(["demo", "ignite"]), 0)
        fallback.assert_called_once()

    def test_removal_is_confined_to_project_folder(self):
        outside = self.directory / "keep"; outside.mkdir()
        with self.assertRaises(ValueError):
            bootstrap.remove_tree(outside)
        self.assertTrue(outside.exists())


class PlayerStart(unittest.TestCase):
    def setUp(self):
        base = ROOT / "runs" / "bootstrap-unit"
        base.mkdir(parents=True, exist_ok=True)
        temp = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(temp.cleanup)
        self.directory = pathlib.Path(temp.name)
        self.proc = Mock(pid=12345)
        self.proc.poll.return_value = None
        self.proc.wait.return_value = 0
        for target, value in (("STATE_DIR", self.directory), ("key_state", Mock(return_value="missing")),
                              ("background_player", Mock(return_value=None))):
            mock = patch.object(bootstrap, target, value)
            mock.start(); self.addCleanup(mock.stop)
        spawn = patch.object(bootstrap.subprocess, "Popen", return_value=self.proc)
        self.spawn = spawn.start(); self.addCleanup(spawn.stop)
        sockets = patch.object(bootstrap.socket, "socket")  # no sockets or child processes in these unit tests
        self.sockets = sockets.start(); self.addCleanup(sockets.stop)
        endpoint = patch.object(bootstrap.codewalk, "player_urlopen")
        self.endpoint = endpoint.start(); self.addCleanup(endpoint.stop)

    def run_guide(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            result = bootstrap.main(["run", "guide", "--background", "--no-open", "--port", "60858"])
        return result, output.getvalue()

    def test_existing_player_is_refused_with_address_and_stop_command(self):
        bootstrap.background_player.return_value = {"walk": "guide", "url": "http://127.0.0.1:60858/"}
        result, output = self.run_guide()
        self.assertEqual(result, 1)
        self.assertIn("http://127.0.0.1:60858/", output)
        self.assertIn("bootstrap.py stop", output)
        self.spawn.assert_not_called()

    def test_child_exit_reports_log_and_no_success(self):
        self.proc.poll.return_value = 7
        result, output = self.run_guide()
        self.assertEqual(result, 1)
        self.assertIn("exited", output)
        self.assertIn(str(self.directory / "player.log"), output)
        self.assertNotIn("PLAYER RUNNING", output)
        self.assertFalse((self.directory / "player.json").exists())

    def test_unresponsive_child_is_stopped_and_returns_failure(self):
        self.endpoint.side_effect = OSError("not ready")
        with patch.object(bootstrap.time, "monotonic", side_effect=itertools.count(0, 10)), \
             patch.object(bootstrap.time, "sleep"):
            result, output = self.run_guide()
        self.assertEqual(result, 1)
        self.proc.terminate.assert_called_once()
        self.proc.wait.assert_called_once()
        self.assertIn("did not answer", output)
        self.assertIn(str(self.directory / "player.log"), output)
        self.assertNotIn("PLAYER RUNNING", output)
        self.assertFalse((self.directory / "player.json").exists())

    def test_spawn_error_reports_log_and_returns_failure(self):
        self.spawn.side_effect = OSError("cannot start")
        result, output = self.run_guide()
        self.assertEqual(result, 1)
        self.assertIn(str(self.directory / "player.log"), output)
        self.assertNotIn("PLAYER RUNNING", output)

    def test_occupied_port_is_refused_without_spawning(self):
        self.sockets.return_value.__enter__.return_value.bind.side_effect = OSError("occupied")
        result, output = self.run_guide()
        self.assertEqual(result, 1)
        self.assertIn("port 60858 is already in use", output)
        self.spawn.assert_not_called()

    def test_demo_ide_option_is_explicitly_ignored_in_view_mode(self):
        with patch.object(bootstrap, "demo_ready", return_value=True), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            result = bootstrap.main(["run", "demo", "--background", "--no-open", "--ide", "--port", "60858"])
        self.assertEqual(result, 0)
        self.assertIn("--ide is ignored", output.getvalue())
        self.assertIn("--view", self.spawn.call_args.args[0])

    def test_success_requires_response_and_leaves_state(self):
        result, output = self.run_guide()
        self.assertEqual(result, 0)
        self.assertIn("PLAYER RUNNING: http://127.0.0.1:60858/", output)
        self.endpoint.assert_called_once()
        self.assertEqual(json.loads((self.directory / "player.json").read_text())["pid"], 12345)
        self.assertTrue(self.spawn.call_args.kwargs["stdout"].closed)


if __name__ == "__main__":
    unittest.main()
