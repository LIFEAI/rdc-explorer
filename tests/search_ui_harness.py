"""Direct functional harness for the portable ripgrep Search panel.

This is deliberately not a cursor script.  Every test calls the same public
controller methods wired to the UI: ``submit_search``, ``set_search_options``,
``select_profile``, ``select_result``, ``set_pinned``, and settings save/reload.

Run:
  build_venv\\Scripts\\python tests\\search_ui_harness.py
  build_venv\\Scripts\\python tests\\search_ui_harness.py --live-regen-root
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PyQt6.QtWidgets import QApplication

import rdc_dashboard
import rg_search
from rdc_dashboard import SearchPanel

APP = None
SUPPORTED_GLOBS = (
    "*.md", "*.mdx", "*.txt", "*.ts", "*.tsx", "*.js", "*.jsx", "*.mjs", "*.cjs",
    "*.py", "*.ps1", "*.psm1", "*.psd1", "*.json", "*.yaml", "*.yml", "*.toml",
    "*.sql", "*.html", "*.css", "*.scss", "*.xml",
)


def wait_until(predicate, timeout_seconds=15):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.03)
        if predicate():
            return
    raise AssertionError("Timed out waiting for direct search completion")


def default_profile(name, root, include=SUPPORTED_GLOBS, exclude=("**/node_modules/**",)):
    return {
        "name": name, "pinned": True, "roots": [str(root)],
        "include": list(include), "exclude": list(exclude),
        "options": {
            "regex": False, "case_insensitive": True, "whole_word": False,
            "hidden": False, "follow_symlinks": False, "no_ignore": False,
            "max_depth": 0, "threads": 0, "max_matches_per_file": 100,
            "max_file_size": "10M",
        },
    }


class PortableSearchHarness(unittest.TestCase):
    """Twenty direct tests for user-visible search behavior and configuration."""

    @classmethod
    def setUpClass(cls):
        global APP
        APP = QApplication.instance() or QApplication([])
        cls.rg_path = shutil.which("rg.exe") or shutil.which("rg")
        if not cls.rg_path:
            raise RuntimeError("ripgrep is required for this harness")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="rdc-search-harness-")
        self.root = Path(self.temp.name)
        (self.root / "notes.md").write_text(
            "Needle appears here\nneedle lower\nneedlework is not whole word\n", encoding="utf-8"
        )
        (self.root / "script.py").write_text("needle = 'python result'\n", encoding="utf-8")
        (self.root / "many.md").write_text("needle\nneedle\nneedle\nneedle\n", encoding="utf-8")
        (self.root / ".hidden.md").write_text("hiddenneedle\n", encoding="utf-8")
        (self.root / "node_modules").mkdir()
        (self.root / "node_modules" / "skip.md").write_text("needle skipped\n", encoding="utf-8")
        (self.root / "deep").mkdir()
        (self.root / "deep" / "below.md").write_text("needle deep\n", encoding="utf-8")
        for pattern in SUPPORTED_GLOBS:
            extension = pattern.removeprefix("*")
            (self.root / f"type-probe{extension}").write_text("typeprobe\n", encoding="utf-8")
        self.config_path = self.root / "rg-search.json"
        self.write_config([default_profile("Harness", self.root)])
        self.settings_patch = patch.object(rdc_dashboard.mru, "search_config_path", lambda: self.config_path)
        self.settings_patch.start()
        self.panel = SearchPanel()
        self.panel.resize(1280, 820)
        self.panel.show()
        QApplication.processEvents()

    def tearDown(self):
        self.panel.close()
        self.settings_patch.stop()
        self.temp.cleanup()

    def write_config(self, profiles, active="Harness"):
        self.config_path.write_text(json.dumps({"rg_path": self.rg_path, "active_profile": active, "profiles": profiles}), encoding="utf-8")

    def command(self, query="needle"):
        return rg_search.build_command(query, self.panel._profile(), self.panel.config)

    def search(self, query="needle"):
        self.panel.submit_search(query)
        wait_until(lambda: self.panel.search_button.isEnabled())
        return [self.panel.results.item(i).data(256) for i in range(self.panel.results.count())]

    # 01–06: text interpretation and file selection.
    def test_01_literal_search_uses_fixed_strings(self):
        self.assertIn("--fixed-strings", self.command("needle.*"))

    def test_02_regex_search_removes_fixed_strings(self):
        self.panel.set_search_options(regex=True)
        self.assertNotIn("--fixed-strings", self.command("needle.*"))

    def test_03_case_insensitive_returns_both_cases(self):
        matches = self.search("needle")
        self.assertTrue(any(match["text"].startswith("Needle") for match in matches))
        self.assertTrue(any(match["text"].startswith("needle") for match in matches))

    def test_04_case_sensitive_excludes_upper_case(self):
        self.panel.set_search_options(case_insensitive=False)
        matches = self.search("needle")
        self.assertFalse(any(match["text"].startswith("Needle") for match in matches))

    def test_05_whole_word_excludes_word_prefixes(self):
        self.panel.set_search_options(whole_word=True)
        matches = self.search("needle")
        self.assertFalse(any("needlework" in match["text"] for match in matches))

    def test_06_twenty_two_file_types_are_searchable(self):
        matches = self.search("typeprobe")
        found_extensions = {Path(match["path"]).suffix for match in matches}
        expected_extensions = {pattern.removeprefix("*") for pattern in SUPPORTED_GLOBS}
        self.assertEqual(expected_extensions, found_extensions)

    # 07–13: scope and every search modifier/tuning control.
    def test_07_exclude_glob_omits_node_modules(self):
        matches = self.search("needle")
        self.assertFalse(any("node_modules" in match["path"] for match in matches))

    def test_08_include_hidden_adds_hidden_flag(self):
        self.panel.set_search_options(hidden=True)
        self.assertIn("--hidden", self.command("hiddenneedle"))
        self.assertEqual(1, len(self.search("hiddenneedle")))

    def test_09_follow_links_adds_follow_flag(self):
        self.panel.set_search_options(follow_symlinks=True)
        self.assertIn("--follow", self.command())

    def test_10_ignore_gitignore_adds_no_ignore_flag(self):
        self.panel.set_search_options(no_ignore=True)
        self.assertIn("--no-ignore", self.command())

    def test_11_max_depth_maps_to_ripgrep(self):
        self.panel.set_search_options(max_depth=1)
        command = self.command()
        self.assertEqual("1", command[command.index("--max-depth") + 1])

    def test_12_threads_maps_to_ripgrep(self):
        self.panel.set_search_options(threads=2)
        command = self.command()
        self.assertEqual("2", command[command.index("--threads") + 1])

    def test_13_max_matches_per_file_caps_returned_lines(self):
        self.panel.set_search_options(max_matches_per_file=2)
        matches = self.search("needle")
        many = [match for match in matches if match["path"].endswith("many.md")]
        self.assertEqual(2, len(many))

    # 14–20: profiles, settings, result model, validation, and result scrolling.
    def test_14_max_file_size_is_preserved_in_command(self):
        self.panel._profile()["options"]["max_file_size"] = "1K"
        command = self.command()
        self.assertEqual("1K", command[command.index("--max-filesize") + 1])

    def test_15_profile_selection_switches_scope(self):
        secondary = self.root / "secondary"; secondary.mkdir()
        (secondary / "secondary.md").write_text("otherneedle\n", encoding="utf-8")
        self.write_config([default_profile("Harness", self.root), default_profile("Secondary", secondary)], active="Harness")
        self.panel.reload_settings()
        self.assertTrue(self.panel.select_profile("Secondary"))
        self.assertIn(str(secondary), self.command("otherneedle"))

    def test_16_pin_state_persists_to_portable_settings(self):
        self.assertTrue(self.panel.set_pinned(False))
        saved = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertFalse(saved["profiles"][0]["pinned"])

    def test_17_selected_result_shows_context(self):
        self.search("needle")
        self.assertTrue(self.panel.select_result(0))
        wait_until(lambda: bool(self.panel.context.toPlainText()))
        self.assertIn(">", self.panel.context.toPlainText())

    def test_18_settings_save_and_reload_round_trip(self):
        self.assertTrue(self.panel.save_settings())
        self.panel.reload_settings()
        self.assertEqual("Harness", self.panel._profile()["name"])

    def test_19_invalid_result_selection_is_safe(self):
        self.assertFalse(self.panel.select_result(-1))
        self.assertFalse(self.panel.select_result(999))

    def test_20_500_regen_root_files_scroll_top_and_bottom(self):
        regen_root = Path(r"C:\Dev\regen-root")
        if not regen_root.is_dir():
            self.skipTest("Regen Root is not present on this machine")
        source_files = subprocess.run(
            [self.rg_path, "-l", "-i", "--glob", "*.md", "--glob", "!**/.git/**",
             "--glob", "!**/node_modules/**", "--glob", "!**/.next/**", "surface", str(regen_root)],
            capture_output=True, text=True, encoding="utf-8", check=False,
        ).stdout.splitlines()[:500]
        self.assertEqual(500, len(source_files), "Expected 500 real Regen Root Markdown files containing 'surface'")
        corpus = self.root / "regen-root-sample"
        for source in map(Path, source_files):
            target = corpus / source.relative_to(regen_root)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        self.panel._profile()["roots"] = [str(corpus)]
        self.panel._profile()["include"] = ["*.md"]
        matches = self.search("surface")
        self.assertGreaterEqual(len(matches), 500)
        scroll = self.panel.results.verticalScrollBar()
        self.assertGreater(scroll.maximum(), 0)
        scroll.setValue(scroll.maximum())
        self.assertEqual(scroll.maximum(), scroll.value())
        scroll.setValue(scroll.minimum())
        self.assertEqual(scroll.minimum(), scroll.value())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live-regen-root", action="store_true", help="Run the 500-file scrolling test")
    args, remaining = parser.parse_known_args()
    if args.live_regen_root:
        suite = unittest.TestSuite([PortableSearchHarness("test_20_500_regen_root_files_scroll_top_and_bottom")])
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    else:
        result = unittest.main(argv=[sys.argv[0], *remaining], exit=False, verbosity=2).result
    if not result.wasSuccessful():
        raise SystemExit(1)
    print(f"SEARCH_UI_HARNESS_OK tests_run={result.testsRun}")


if __name__ == "__main__":
    main()
