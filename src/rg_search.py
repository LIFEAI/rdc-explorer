"""Portable on-demand search across text, PDF, Word, and PowerPoint files."""
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DOCUMENT_SUFFIXES = {".pdf", ".docx", ".pptx"}
CODE_PATTERNS = ("*.ts", "*.tsx", "*.js", "*.jsx", "*.mjs", "*.cjs", "*.py", "*.ps1", "*.psm1", "*.psd1", "*.sql", "*.html", "*.css", "*.scss", "*.xml")
# Docs are extracted once by the configured extraction workflow, then searched as
# Markdown/text. Binary formats are deliberately not reparsed during a search.
DOC_PATTERNS = ("*.md", "*.mdx", "*.txt")


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
    # Legacy direct binary extraction is intentionally off in product profiles.
    # The extractor contract supplies a one-time Markdown/text projection instead.
    if not profile.get("allow_legacy_binary_extraction", False):
        return []
    return [pattern for pattern in profile.get("include", []) if Path(pattern).suffix.lower() in DOCUMENT_SUFFIXES]


def _text_patterns(profile: dict) -> list[str]:
    return [pattern for pattern in profile.get("include", []) if Path(pattern).suffix.lower() not in DOCUMENT_SUFFIXES]


def parse_query(query: str) -> list[str]:
    """Tokenize quoted phrases and reserved and/or/not operators for source search."""
    tokens = re.findall(r'"([^"\\]*(?:\\.[^"\\]*)*)"|(\S+)', query)
    return [quoted.replace('\\"', '"') if quoted else bare for quoted, bare in tokens]


def _query_postfix(query: str) -> list[str]:
    tokens = parse_query(query)
    if not tokens:
        raise ValueError("Enter a source-search phrase")
    precedence = {"or": 1, "and": 2, "not": 3}
    output, operators = [], []
    expecting_term = True
    for token in tokens:
        operator = token.casefold()
        if operator in precedence:
            if operator == "not":
                if not expecting_term:
                    operators.append("and")
                operators.append(operator)
                expecting_term = True
                continue
            if expecting_term:
                raise ValueError(f"Expected a search term before '{token}'")
            while operators and precedence[operators[-1]] >= precedence[operator]:
                output.append(operators.pop())
            operators.append(operator)
            expecting_term = True
        else:
            if not expecting_term:
                operators.append("and")
            output.append(token)
            expecting_term = False
    if expecting_term:
        raise ValueError("A source-search operator needs a term after it")
    while operators:
        output.append(operators.pop())
    return output


def query_terms(query: str) -> list[str]:
    return [token for token in _query_postfix(query) if token not in {"and", "or", "not"}]


def matches_query(text: str, query: str, options: dict) -> bool:
    postfix = _query_postfix(query)
    flags = re.I if options.get("case_insensitive", True) else 0
    stack = []
    for token in postfix:
        if token == "not":
            stack.append(not stack.pop())
        elif token in {"and", "or"}:
            right, left = stack.pop(), stack.pop()
            stack.append(left and right if token == "and" else left or right)
        else:
            expression = token if options.get("regex") else re.escape(token)
            if options.get("whole_word"):
                expression = rf"\b(?:{expression})\b"
            stack.append(bool(re.search(expression, text, flags)))
    return bool(stack and stack[-1])


def _area_at_line(path: Path, line_number: int, cache: dict) -> tuple[int, str]:
    """Return a blank-line-delimited paragraph/source area without retaining file text."""
    key = str(path)
    lines = cache.get(key)
    if lines is None:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        if len(cache) >= 8:
            cache.pop(next(iter(cache)))
        cache[key] = lines
    index = max(0, min(line_number - 1, len(lines) - 1))
    start, end = index, index
    while start > 0 and lines[start - 1].strip():
        start -= 1
    while end + 1 < len(lines) and lines[end + 1].strip():
        end += 1
    return start + 1, "\n".join(lines[start:end + 1])


def build_command(query: str, profile: dict, config: dict) -> list[str]:
    """Build the exact ripgrep command for text-capable file masks only."""
    rg = locate_rg(config)
    if not rg:
        raise FileNotFoundError("ripgrep was not found. Set rg_path in rg-search.json.")

    options = profile.get("options", {})
    command = [rg, "--json", "--line-number", "--column", "--color", "never"]
    command += ["--max-count", str(options.get("max_matches_per_file", 100))]
    command += ["--max-filesize", str(options.get("max_file_size", "10M"))]
    terms = query_terms(query)
    if not options.get("regex", False) and terms:
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
    if terms:
        for term in terms:
            command += ["-e", term]
    else:
        command += ["-e", "."]
    command += profile.get("roots", [])
    return command


def _search_text(query: str, profile: dict, config: dict, cancel_event=None, deadline=None):
    if not _text_patterns(profile):
        return
    command = build_command(query, profile, config)
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    emitted_areas, area_cache = set(), {}
    try:
        for raw in process.stdout:
            if (cancel_event and cancel_event.is_set()) or (deadline and time.monotonic() >= deadline):
                return
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if event.get("type") != "match":
                continue
            data = event["data"]
            text = data["lines"]["text"].rstrip("\r\n")
            options = profile.get("options", {})
            display_line = data["line_number"]
            if options.get("same_area"):
                try:
                    display_line, area = _area_at_line(Path(data["path"]["text"]), data["line_number"], area_cache)
                except OSError:
                    continue
                area_key = (data["path"]["text"], display_line)
                if area_key in emitted_areas or not matches_query(area, query, options):
                    continue
                emitted_areas.add(area_key)
                text = area.splitlines()[0] if area else text
            elif not matches_query(text, query, options):
                continue
            if profile.get("frontmatter_only") and not _is_frontmatter_line(Path(data["path"]["text"]), data["line_number"]):
                continue
            yield {
                "path": data["path"]["text"], "line": display_line,
                "text": text,
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


def _document_files(profile: dict, deadline=None):
    patterns = _document_patterns(profile)
    if not patterns:
        return
    options = profile.get("options", {})
    max_depth = int(options.get("max_depth") or 0)
    max_size = _bytes(options.get("max_file_size", "10M"))
    include_hidden = bool(options.get("hidden"))
    exclusions = list(profile.get("exclude", []))
    examined = 0
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
                if deadline and time.monotonic() >= deadline:
                    return
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
                        examined += 1
                        if examined > 250:
                            return
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


def _is_frontmatter_line(path: Path, line_number: int) -> bool:
    if path.suffix.lower() not in {".md", ".mdx"}:
        return False
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        if not lines or lines[0].strip() != "---":
            return False
        for end in range(1, len(lines)):
            if lines[end].strip() == "---":
                return 1 < line_number <= end
    except OSError:
        return False
    return False


def _search_documents(query: str, profile: dict, cancel_event=None, deadline=None):
    options = profile.get("options", {})
    per_file = int(options.get("max_matches_per_file", 100))
    for path in _document_files(profile, deadline):
        if (cancel_event and cancel_event.is_set()) or (deadline and time.monotonic() >= deadline):
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
                    if not matches_query(line, query, options):
                        continue
                    found = re.search(query_terms(query)[0] if options.get("regex") else re.escape(query_terms(query)[0]), line, re.I if options.get("case_insensitive", True) else 0)
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
    deadline = time.monotonic() + int(profile.get("options", {}).get("search_time_limit_seconds", 12))
    for source in (_search_text(query, profile, config, cancel_event, deadline), _search_documents(query, profile, cancel_event, deadline)):
        for match in source:
            if (cancel_event and cancel_event.is_set()) or time.monotonic() >= deadline:
                return
            yield match
            remaining -= 1
            if remaining <= 0:
                return


def search_codeflow(query: str, config: dict, cancel_event=None):
    """Search the live CodeFlow symbol graph, never the local disk."""
    base = config.get("codeflow_url") or os.environ.get("CODEFLOW_URL") or "http://127.0.0.1:3109"
    terms = query_terms(query)
    max_results, request_limit, max_payload = 100, 64, 2 * 1024 * 1024
    seen, emitted = set(), 0
    for term in dict.fromkeys(terms):
        if cancel_event and cancel_event.is_set():
            return
        body = json.dumps({"query": term, "limit": request_limit, "offset": 0}).encode("utf-8")
        request = urllib.request.Request(
            base.rstrip("/") + "/api/codeflow/symbols/search", data=body,
            headers={"Content-Type": "application/json", "Accept": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > max_payload:
                    raise RuntimeError("CodeFlow response exceeded the 2 MB safety limit")
                raw = response.read(max_payload + 1)
                if len(raw) > max_payload:
                    raise RuntimeError("CodeFlow response exceeded the 2 MB safety limit")
                payload = json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read(4096).decode("utf-8", errors="replace")
            raise RuntimeError(f"CodeFlow rejected the query ({exc.code}): {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"CodeFlow is unavailable at {base}: {exc.reason}") from exc
        for symbol in payload.get("symbols", []):
            if cancel_event and cancel_event.is_set():
                return
            key = (symbol.get("name"), symbol.get("file_path"), symbol.get("start_line"))
            if key in seen or not matches_query(symbol.get("name") or "", query, {"case_insensitive": True}):
                continue
            seen.add(key)
            path = symbol.get("file_path") or "(CodeFlow symbol without a file path)"
            line = symbol.get("start_line") or 1
            location = f"{symbol.get('kind') or 'symbol'} • {symbol.get('language') or 'unknown'} • line {line}"
            yield {"path": path, "line": line, "column": 1, "text": symbol.get("name") or "(unnamed symbol)", "location": location,
                   "preview": json.dumps(symbol, indent=2, ensure_ascii=False), "codeflow": True}
            emitted += 1
            if emitted >= max_results:
                return
