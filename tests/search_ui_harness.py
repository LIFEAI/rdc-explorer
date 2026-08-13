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
import traceback
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QMimeData, QUrl, QPointF
from PyQt6.QtGui import QDropEvent

import rdc_dashboard
import rg_search
from rdc_dashboard import SearchPanel, FilePanel

APP = None
SUPPORTED_GLOBS = (
    "*.md", "*.mdx", "*.txt", "*.ts", "*.tsx", "*.js", "*.jsx", "*.mjs", "*.cjs",
    "*.py", "*.ps1", "*.psm1", "*.psd1", "*.json", "*.yaml", "*.yml", "*.toml",
    "*.sql", "*.html", "*.css", "*.scss", "*.xml", "*.pdf", "*.docx", "*.pptx",
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
            "same_area": False,
            "max_depth": 0, "threads": 0, "max_matches_per_file": 100,
            "max_total_results": 5000,
            "search_time_limit_seconds": 12,
            "max_file_size": "10M",
        },
        "search_documents": True,
        "allow_legacy_binary_extraction": True,
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
        (self.root / "areas.md").write_text("needle begins this paragraph\nsecond term appears here\n\nneedle isolated\n\nsecond term isolated\n", encoding="utf-8")
        (self.root / ".hidden.md").write_text("hiddenneedle\n", encoding="utf-8")
        (self.root / "node_modules").mkdir()
        (self.root / "node_modules" / "skip.md").write_text("needle skipped\n", encoding="utf-8")
        (self.root / "_working").mkdir()
        (self.root / "_working" / "skip.md").write_text("needle skipped working\n", encoding="utf-8")
        (self.root / "deep").mkdir()
        (self.root / "deep" / "below.md").write_text("needle deep\n", encoding="utf-8")
        for pattern in SUPPORTED_GLOBS:
            extension = pattern.removeprefix("*")
            if extension in rg_search.DOCUMENT_SUFFIXES:
                continue
            (self.root / f"type-probe{extension}").write_text("typeprobe\n", encoding="utf-8")
        # Replace the three binary placeholders with actual documents the shipped extractor must read.
        import pymupdf
        from docx import Document
        from pptx import Presentation
        pdf = pymupdf.open(); page = pdf.new_page(); page.insert_text((72, 72), "typeprobe pdfneedle")
        pdf.save(self.root / "type-probe.pdf"); pdf.close()
        word = Document(); word.add_paragraph("typeprobe docxneedle"); word.save(self.root / "type-probe.docx")
        deck = Presentation()
        slide = deck.slides.add_slide(deck.slide_layouts[0])
        slide.shapes.title.text = "typeprobe pptxneedle"
        deck.save(self.root / "type-probe.pptx")
        self.config_path = self.root / "rg-search.json"
        self.write_config([default_profile("Harness", self.root)])
        self.settings_patch = patch.object(rdc_dashboard.mru, "search_config_path", lambda: self.config_path)
        self.settings_patch.start()
        self.mru_path = self.root / "mru-state"
        self.mru_path.mkdir()
        self.mru_patch = patch.object(rdc_dashboard.mru, "_config_dir", lambda: self.mru_path)
        self.mru_patch.start()
        self.panel = SearchPanel()
        self.panel.resize(1280, 820)
        self.panel.show()
        self.files = FilePanel({"rdc2_root": str(self.root)})
        self.files.resize(1280, 820)
        self.files.show()
        QApplication.processEvents()

    def tearDown(self):
        self.panel.close()
        self.files.close()
        self.mru_patch.stop()
        self.settings_patch.stop()
        self.temp.cleanup()

    def write_config(self, profiles, active="Harness"):
        self.config_path.write_text(json.dumps({"rg_path": self.rg_path, "active_profile": active, "profiles": profiles}), encoding="utf-8")

    def command(self, query="needle"):
        return rg_search.build_command(query, self.panel._profile(), self.panel.config)

    def search(self, query="needle"):
        self.panel.submit_search(query)
        wait_until(lambda: self.panel.search_button.isEnabled())
        return list(self.panel.result_matches)

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

    def test_06_twenty_five_file_types_are_searchable(self):
        matches = self.search("typeprobe")
        found_extensions = {Path(match["path"]).suffix for match in matches}
        expected_extensions = {pattern.removeprefix("*") for pattern in SUPPORTED_GLOBS}
        self.assertEqual(expected_extensions, found_extensions)

    # 07–13: scope and every search modifier/tuning control.
    def test_07_exclude_glob_omits_node_modules(self):
        self.panel._profile()["exclude"].append("**/_working/**")
        matches = self.search("needle")
        self.assertFalse(any("node_modules" in match["path"] for match in matches))
        self.assertFalse(any("_working" in match["path"] for match in matches))

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
        self.panel.results.expandAll()
        QApplication.processEvents()
        scroll = self.panel.results.verticalScrollBar()
        self.assertGreater(scroll.maximum(), 0)
        scroll.setValue(scroll.maximum())
        self.assertEqual(scroll.maximum(), scroll.value())
        scroll.setValue(scroll.minimum())
        self.assertEqual(scroll.minimum(), scroll.value())

    def test_21_pdf_text_is_searchable_with_page_preview(self):
        matches = self.search("pdfneedle")
        self.assertEqual(1, len(matches))
        self.assertEqual("page 1", matches[0]["location"])
        self.assertTrue(self.panel.select_result(0))
        self.assertIn("pdfneedle", self.panel.context.toPlainText())

    def test_22_docx_text_is_searchable_with_document_preview(self):
        matches = self.search("docxneedle")
        self.assertEqual(1, len(matches))
        self.assertEqual("document", matches[0]["location"])
        self.assertTrue(self.panel.select_result(0))
        self.assertIn("docxneedle", self.panel.context.toPlainText())

    def test_23_pptx_text_is_searchable_with_slide_preview(self):
        matches = self.search("pptxneedle")
        self.assertEqual(1, len(matches))
        self.assertEqual("slide 1", matches[0]["location"])
        self.assertTrue(self.panel.select_result(0))
        self.assertIn("pptxneedle", self.panel.context.toPlainText())

    def test_24_existing_profile_is_upgraded_for_documents(self):
        self.write_config([default_profile("Harness", self.root, include=("*.md",))])
        self.panel.reload_settings()
        self.assertTrue(all(pattern in self.panel._profile()["include"] for pattern in ("*.pdf", "*.docx", "*.pptx")))

    def test_25_search_runtime_dependencies_execute(self):
        self.assertTrue(Path(rg_search.runtime_self_test()["rg"]).is_file())

    def test_26_existing_profile_is_upgraded_to_exclude_working(self):
        self.write_config([default_profile("Harness", self.root, exclude=("**/.git/**",))])
        self.panel.reload_settings()
        self.assertIn("**/_working/**", self.panel._profile()["exclude"])

    def test_27_temp_and_tmp_directories_are_always_excluded(self):
        temp_dir = self.root / "temporary-build"; temp_dir.mkdir()
        tmp_dir = self.root / "tmp-output"; tmp_dir.mkdir()
        (temp_dir / "leak.md").write_text("needle should not appear\n", encoding="utf-8")
        (tmp_dir / "leak.md").write_text("needle should not appear\n", encoding="utf-8")
        matches = self.search("needle")
        self.assertFalse(any("temporary-build" in match["path"] or "tmp-output" in match["path"] for match in matches))

    def test_28_global_result_cap_bounds_memory_and_reports_limit(self):
        self.panel.set_search_options(max_total_results=3)
        matches = self.search("needle")
        self.assertEqual(3, len(matches))
        self.assertIn("limit reached", self.panel.status.text())

    def test_29_context_zoom_is_controllable_without_mouse_automation(self):
        baseline = self.panel.context_zoom
        self.panel.set_context_zoom(2)
        self.assertEqual(baseline + 2, self.panel.context_zoom)
        self.panel.reset_context_zoom()
        self.assertEqual(0, self.panel.context_zoom)

    def test_30_both_high_contrast_theme_palettes_are_shipped(self):
        self.assertIn("background: #1e1e1e", rdc_dashboard.DARK_QSS)
        self.assertIn("background: #f7f9fc", rdc_dashboard.LIGHT_QSS)

    def test_31_repeated_search_discards_old_results_and_stale_batches(self):
        self.search("needle")
        old_generation = self.panel.search_generation
        current = self.search("typeprobe")
        self.assertTrue(current)
        self.assertTrue(all("typeprobe" in match["text"] for match in current))
        before = self.panel.match_count
        self.panel._add_results((old_generation, [{"path": "C:/stale.md", "line": 1, "text": "stale"}]))
        self.assertEqual(before, self.panel.match_count)
        self.assertEqual(before, len(self.panel.result_matches))

    def test_32_in_scope_supports_string_in_markdown(self):
        self.panel.set_search_scope("*.md")
        matches = self.search("needle")
        self.assertTrue(matches)
        self.assertTrue(all(Path(match["path"]).suffix == ".md" for match in matches))

    def test_34_query_grammar_supports_quoted_and_or_not(self):
        self.assertTrue(rg_search.matches_query("Needle appears here", '"Needle appears" and not lower', self.panel._profile()["options"]))
        self.assertTrue(rg_search.matches_query("needle lower", 'missing or "needle lower"', self.panel._profile()["options"]))
        self.assertFalse(rg_search.matches_query("needle lower", 'needle and not lower', self.panel._profile()["options"]))

    def test_35_in_frontmatter_limits_markdown_to_frontmatter(self):
        (self.root / "frontmatter.md").write_text("---\ntitle: needle metadata\n---\nneedle body\n", encoding="utf-8")
        self.panel.set_search_scope("frontmatter")
        matches = self.search("needle")
        self.assertTrue(any("needle metadata" in match["text"] for match in matches))
        self.assertFalse(any("needle body" in match["text"] for match in matches))

    def test_36_directory_label_shows_start_and_end_with_ellipsis(self):
        original = r"C:\\very-long-directory-name\\deep\\nested\\another-long-directory-name"
        label = self.panel.compact_path(original)
        self.assertTrue(label.startswith(original[:15]))
        self.assertIn(" … ", label)
        self.assertTrue(label.endswith(original[-25:]))

    def test_37_in_cf_uses_codeflow_symbols_route_not_disk(self):
        response = MagicMock()
        response.read.return_value = json.dumps({"symbols": [{
            "name": "needleSymbol", "file_path": "apps/test.ts", "start_line": 42,
            "kind": "function", "language": "typescript",
        }]}).encode("utf-8")
        with patch("rg_search.urllib.request.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value = response
            matches = list(rg_search.search_codeflow("needle", {"codeflow_url": "http://codeflow.test"}))
        self.assertEqual("apps/test.ts", matches[0]["path"])
        self.assertIn("function", matches[0]["location"])
        request = urlopen.call_args.args[0]
        self.assertEqual("http://codeflow.test/api/codeflow/symbols/search", request.full_url)
        self.assertEqual({"query": "needle", "limit": 64, "offset": 0}, json.loads(request.data.decode("utf-8")))

    def test_38_search_busy_indicator_tracks_worker_lifecycle(self):
        self.assertFalse(self.panel.search_busy.isVisible())
        self.panel.query.setText("needle")
        self.panel._run_search()
        self.assertTrue(self.panel.search_busy.isVisible())
        wait_until(lambda: self.panel.search_button.isEnabled())
        self.assertFalse(self.panel.search_busy.isVisible())

    def test_39_codeflow_response_is_hard_bounded(self):
        oversized = MagicMock()
        oversized.headers = {"Content-Length": str(2 * 1024 * 1024 + 1)}
        with patch("rg_search.urllib.request.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value = oversized
            with self.assertRaisesRegex(RuntimeError, "2 MB safety limit"):
                list(rg_search.search_codeflow("needle", {"codeflow_url": "http://codeflow.test"}))

    def test_40_same_area_requires_terms_in_one_paragraph(self):
        self.panel.set_search_options(same_area=True)
        matches = self.search("needle and second")
        area_matches = [match for match in matches if match["path"].endswith("areas.md")]
        self.assertEqual(1, len(area_matches))
        self.assertEqual(1, area_matches[0]["line"])

    def test_41_blank_scope_skips_expensive_document_extraction(self):
        self.panel._profile()["search_documents"] = False
        self.panel._profile()["allow_legacy_binary_extraction"] = False
        self.assertEqual([], rg_search._document_patterns(self.panel._profile()))
        self.panel.set_search_scope("docs")
        scoped, source = self.panel._scoped_profile(self.panel._profile())
        self.assertEqual("disk", source)
        self.assertFalse(scoped["search_documents"])
        self.assertEqual(["*.md", "*.mdx", "*.txt"], scoped["include"])

    def test_43_binary_docs_require_the_one_time_extractor_projection(self):
        self.panel.set_search_scope("*.pdf")
        with self.assertRaisesRegex(ValueError, "one-time extractor projection"):
            self.panel._scoped_profile(self.panel._profile())

    def test_44_worker_failure_reenables_search_and_shows_the_error(self):
        with patch("rg_search.search", side_effect=RuntimeError("forced worker failure")):
            self.panel.submit_search("needle")
            wait_until(lambda: self.panel.search_button.isEnabled())
        self.assertIn("forced worker failure", self.panel.status.text())
        self.assertFalse(self.panel.search_busy.isVisible())

    def test_45_search_button_clicked_signal_does_not_replace_query_with_bool(self):
        self.panel.query.setText("needle")
        self.panel.search_button.click()
        wait_until(lambda: self.panel.search_button.isEnabled())
        self.assertEqual("needle", self.panel.query.text())
        self.assertNotIn("unexpected type 'bool'", self.panel.status.text())

    def test_46_first_match_auto_renders_context_without_tree_click(self):
        self.search("needle")
        self.assertTrue(self.panel.results.selectedItems())
        self.assertIn("needle", self.panel.context.toPlainText().casefold())
        self.assertEqual(f"Hit 1 of {len(self.panel.result_items)}", self.panel.hit_position.text())

    def test_47_bottom_hit_navigation_changes_selection(self):
        self.search("needle")
        first = self.panel._selected_match()
        self.assertTrue(self.panel.navigate_result(1))
        self.assertNotEqual(first, self.panel._selected_match())
        self.assertTrue(self.panel.previous_hit.isEnabled())
        self.assertTrue(self.panel.next_hit.isEnabled())

    def test_48_tab_order_and_enter_signal_connect_query_to_in(self):
        candidate = self.panel.query.nextInFocusChain()
        while candidate.focusPolicy() == Qt.FocusPolicy.NoFocus:
            candidate = candidate.nextInFocusChain()
        self.assertIs(candidate, self.panel.search_scope)
        calls = []
        with patch.object(self.panel, "_run_search", side_effect=lambda: calls.append(True)):
            self.panel.search_scope.returnPressed.emit()
        self.assertEqual([True], calls)

    def test_49_text_zoom_controls_are_not_hit_navigation(self):
        baseline = self.panel.context_zoom
        self.panel.set_context_zoom(1)
        self.assertEqual(baseline + 1, self.panel.context_zoom)
        self.assertEqual("← Previous hit", self.panel.previous_hit.text())
        self.assertEqual("Next hit →", self.panel.next_hit.text())

    def test_50_search_and_in_share_one_horizontal_input_row(self):
        row = self.panel.search_input_row
        self.assertLess(row.indexOf(self.panel.query), row.indexOf(self.panel.search_scope))
        self.assertLess(row.indexOf(self.panel.search_scope), row.indexOf(self.panel.search_button))

    def test_51_file_tree_search_uses_active_folder_as_its_only_root(self):
        profile, _config = self.files.tree_profile()
        self.assertEqual(profile["roots"], [str(self.root)])
        self.assertFalse(profile["search_documents"])
        self.assertLessEqual(profile["options"]["max_total_results"], 500)

    def test_52_pin_file_and_folder_persist_in_file_tree(self):
        self.files.pin_paths([str(self.root / "notes.md"), str(self.root / "deep")])
        self.assertIn(str(self.root / "notes.md"), rdc_dashboard.mru.get_pinned_files())
        self.assertIn(str(self.root / "deep"), rdc_dashboard.mru.get_pinned_folders())
        self.assertEqual(self.files.pins.topLevelItem(0).childCount(), 1)
        self.assertEqual(self.files.pins.topLevelItem(1).childCount(), 1)

    def test_53_dragged_pin_navigates_the_live_tree_without_file_move(self):
        self.files.pin_paths([str(self.root / "deep")])
        self.files.open_pinned(str(self.root / "deep"))
        self.assertEqual(self.files.current_root, str(self.root / "deep"))
        self.assertTrue((self.root / "deep" / "below.md").is_file())

    def test_54_tree_search_groups_files_by_directory_and_previews_first_match(self):
        self.files.tree_query.setText("needle")
        self.assertTrue(self.files.search_tree())
        wait_until(lambda: self.files.tree_search_button.isEnabled())
        self.assertGreater(self.files.search_results.topLevelItemCount(), 0)
        directory = self.files.search_results.topLevelItem(0)
        self.assertGreater(directory.childCount(), 0)
        self.assertIn("needle", self.files.preview.toPlainText().lower())

    def test_55_clear_tree_search_returns_to_live_filesystem_tree(self):
        self.files.tree_query.setText("needle")
        self.files.search_tree()
        wait_until(lambda: self.files.tree_search_button.isEnabled())
        self.files.clear_tree_search()
        self.assertIs(self.files.tree_stack.currentWidget(), self.files.tree)

    def test_56_tree_search_uses_the_same_safe_query_grammar(self):
        self.files.tree_query.setText('"Needle appears" and here')
        self.assertTrue(self.files.search_tree())
        wait_until(lambda: self.files.tree_search_button.isEnabled())
        self.assertGreater(self.files.search_results.topLevelItemCount(), 0)

    def test_57_file_preview_text_zoom_and_reset_are_directly_controllable(self):
        self.files.show_preview(str(self.root / "notes.md"), 1)
        self.files.set_preview_zoom(2)
        self.assertEqual(self.files.preview_zoom, 2)
        self.files.reset_preview_zoom()
        self.assertEqual(self.files.preview_zoom, 0)

    def test_58_unpin_removes_the_location_from_the_file_tree(self):
        target = str(self.root / "notes.md")
        self.files.pin_paths([target])
        item = self.files.pins.topLevelItem(1).child(0)
        self.files.pins.setCurrentItem(item)
        self.files.unpin_selected()
        self.assertNotIn(target, rdc_dashboard.mru.get_pinned_files())

    def test_59_file_tree_url_drop_pins_without_moving_the_source_file(self):
        target = self.root / "notes.md"
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(target))])
        event = QDropEvent(QPointF(8, 8), Qt.DropAction.CopyAction, mime,
                           Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        self.files.pins.dropEvent(event)
        self.assertIn(str(target), rdc_dashboard.mru.get_pinned_files())
        self.assertTrue(target.is_file())

    def test_42_search_time_limit_is_a_profile_option(self):
        self.assertEqual(12, self.panel._profile()["options"]["search_time_limit_seconds"])

    def test_33_unhandled_exception_writes_persistent_crash_log(self):
        crash_path = self.root / "crash.log"
        with patch.object(rdc_dashboard.mru, "crash_log_path", lambda: crash_path):
            try:
                raise RuntimeError("harness crash sentinel")
            except RuntimeError:
                rdc_dashboard.write_crash_log("harness", *sys.exc_info())
        text = crash_path.read_text(encoding="utf-8")
        self.assertIn("origin=harness", text)
        self.assertIn("harness crash sentinel", text)


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
