"""Portable on-demand search across text, PDF, Word, and PowerPoint files."""
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

DOCUMENT_SUFFIXES = {".pdf", ".docx", ".pptx"}


def locate_rg(config: dict) -> str | None:
    """Prefer an explicit path, then bundled ripgrep, then PATH."""
    configured = config.get("rg_path", "").strip()
    if configured and Path(configured).is_file():
        return configured
    bundled = Path(getattr(sys, "_MEIPASS", "")) / "bin" / "rg.exe"
    if bundled.is_file():
        return str(bundled)
    return shutil.which("rg.exe") or shutil.which("rg")


def runtime_self_test() -> dict:
    """Verify the bundled Search runtime can execute every required component."""
    rg = locate_rg({})
    if not rg:
        raise RuntimeError("Bundled ripgrep was not found")
    probe = subprocess.run([rg, "--version"], capture_output=True, text=True, timeout=10, check=False)
    if probe.returncode != 0:
        raise RuntimeError(probe.stderr.strip() or "Bundled ripgrep could not execute")
    import pymupdf  # noqa: F401
    import docx  # noqa: F401
    import pptx  # noqa: F401
    return {"rg": rg}


def _document_patterns(profile: dict) -> list[str]:
    return [pattern for pattern in profile.get("include", []) if Path(pattern).suffix.lower() in DOCUMENT_SUFFIXES]


def _text_patterns(profile: dict) -> list[str]:
    return [pattern for pattern in profile.get("include", []) if pattern not in _document_patterns(profile)]


def build_command(query: str, profile: dict, config: dict) -> list[str]:
    """Build the exact ripgrep command for text-capable file masks only."""
    rg = locate_rg(config)
    if not rg:
        raise FileNotFoundError("ripgrep was not found. Set rg_path in rg-search.json.")

    options = profile.get("options", {})
    command = [rg, "--json", "--line-number", "--column", "--color", "never"]
    command += ["--max-count", str(options.get("max_matches_per_file", 100))]
    command += ["--max-filesize", str(options.get("max_file_size", "10M"))]
    if not options.get("regex", False):
        command.append("--fixed-strings")
    if options.get("case_insensitive", True):
        command.append("--ignore-case")
    if options.get("whole_word", False):
        command.append("--word-regexp")
    if options.get("hidden", False):
        command.append("--hidden")
    if options.get("follow_symlinks", False):
        command.append("--follow")
    if options.get("no_ignore", False):
        command.append("--no-ignore")
    if options.get("max_depth"):
        command += ["--max-depth", str(options["max_depth"])]
    if options.get("threads"):
        command += ["--threads", str(options["threads"])]
    for pattern in _text_patterns(profile):
        command += ["--glob", pattern]
    for pattern in profile.get("exclude", []):
        command += ["--glob", f"!{pattern}"]
    command += [query, *profile.get("roots", [])]
    return command


def _search_text(query: str, profile: dict, config: dict, cancel_event=None):
    if not _text_patterns(profile):
        return
    command = build_command(query, profile, config)
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        for raw in process.stdout:
            if cancel_event and cancel_event.is_set():
                return
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if event.get("type") != "match":
                continue
            data = event["data"]
            yield {
                "path": data["path"]["text"], "line": data["line_number"],
                "text": data["lines"]["text"].rstrip("\r\n"),
                "column": data.get("submatches", [{}])[0].get("start", 0) + 1,
            }
        stderr = process.stderr.read().strip()
        code = process.wait()
        if code > 1:
            raise RuntimeError(stderr or f"ripgrep exited with code {code}")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        process.stdout.close()
        process.stderr.close()


def _normalized(path: Path) -> str:
    return path.as_posix().lstrip("./")


def _excluded(relative: Path, exclusions: list[str]) -> bool:
    value = _normalized(relative)
    values = (value, value + "/")
    for pattern in exclusions:
        clean = pattern.lstrip("!").replace("\\", "/")
        alternatives = (clean, clean[3:]) if clean.startswith("**/") else (clean,)
        if any(fnmatch.fnmatch(candidate, option) for candidate in values for option in alternatives):
            return True
    return False


def _is_hidden(path: Path) -> bool:
    return any(part.startswith(".") for part in path.parts)


def _is_temporary(path: Path) -> bool:
    return any("temp" in part.lower() or "tmp" in part.lower() for part in path.parts)


def _document_files(profile: dict):
    patterns = _document_patterns(profile)
    if not patterns:
        return
    options = profile.get("options", {})
    max_depth = int(options.get("max_depth") or 0)
    max_size = _bytes(options.get("max_file_size", "10M"))
    include_hidden = bool(options.get("hidden"))
    exclusions = list(profile.get("exclude", []))
    for root_text in profile.get("roots", []):
        root = Path(root_text)
        if not root.is_dir():
            continue
        for directory, dirs, files in os.walk(root, followlinks=bool(options.get("follow_symlinks"))):
            current = Path(directory)
            relative_dir = current.relative_to(root)
            dirs[:] = [
                name for name in dirs
                if name != ".git" and not _is_temporary(relative_dir / name)
                and (include_hidden or not _is_hidden(relative_dir / name))
                and not _excluded(relative_dir / name, exclusions)
                and (not max_depth or len((relative_dir / name).parts) <= max_depth)
            ]
            for name in files:
                relative = relative_dir / name
                if _is_temporary(relative) or (not include_hidden and _is_hidden(relative)) or _excluded(relative, exclusions):
                    continue
                if max_depth and len(relative.parts) - 1 > max_depth:
                    continue
                if not any(fnmatch.fnmatch(name.lower(), pattern.lower()) for pattern in patterns):
                    continue
                candidate = current / name
                try:
                    if candidate.stat().st_size <= max_size:
                        yield candidate
                except OSError:
                    continue


def _bytes(value) -> int:
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([kmg]?)\s*", str(value), re.I)
    if not match:
        return 10 * 1024 * 1024
    scale = {"": 1, "k": 1024, "m": 1024**2, "g": 1024**3}[match.group(2).lower()]
    return int(float(match.group(1)) * scale)


def _document_sections(path: Path):
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        import pymupdf
        with pymupdf.open(path) as document:
            return [(f"page {index + 1}", page.get_text("text")) for index, page in enumerate(document)]
    if suffix == ".docx":
        from docx import Document
        document = Document(path)
        return [("document", "\n".join(paragraph.text for paragraph in document.paragraphs))]
    if suffix == ".pptx":
        from pptx import Presentation
        presentation = Presentation(path)
        return [
            (f"slide {index + 1}", "\n".join(shape.text for shape in slide.shapes if getattr(shape, "has_text_frame", False)))
            for index, slide in enumerate(presentation.slides)
        ]
    return []


def _query_pattern(query: str, options: dict):
    expression = query if options.get("regex") else re.escape(query)
    if options.get("whole_word"):
        expression = rf"\b(?:{expression})\b"
    return re.compile(expression, re.I if options.get("case_insensitive", True) else 0)


def _search_documents(query: str, profile: dict, cancel_event=None):
    options = profile.get("options", {})
    pattern = _query_pattern(query, options)
    per_file = int(options.get("max_matches_per_file", 100))
    for path in _document_files(profile):
        if cancel_event and cancel_event.is_set():
            return
        try:
            emitted = 0
            for location, section in _document_sections(path):
                if cancel_event and cancel_event.is_set():
                    return
                lines = section.splitlines() or [section]
                for index, line in enumerate(lines, 1):
                    if cancel_event and cancel_event.is_set():
                        return
                    found = pattern.search(line)
                    if not found:
                        continue
                    start, end = max(0, index - 3), min(len(lines), index + 2)
                    preview = "\n".join(
                        f"{line_number + 1:>6}  {'>' if line_number + 1 == index else ' '} {lines[line_number]}"
                        for line_number in range(start, end)
                    )
                    yield {
                        "path": str(path), "line": index, "column": found.start() + 1,
                        "text": line, "location": location, "preview": preview,
                    }
                    emitted += 1
                    if emitted >= per_file:
                        break
                if emitted >= per_file:
                    break
        except Exception:
            # A damaged, encrypted, or unsupported document must not stop the rest of an on-demand search.
            continue


def search(query: str, profile: dict, config: dict, cancel_event=None):
    """Yield normalized text and document matches using one profile contract."""
    remaining = int(profile.get("options", {}).get("max_total_results", 5000))
    for source in (_search_text(query, profile, config, cancel_event), _search_documents(query, profile, cancel_event)):
        for match in source:
            if cancel_event and cancel_event.is_set():
                return
            yield match
            remaining -= 1
            if remaining <= 0:
                return
