"""Portable ripgrep command construction and JSON result parsing."""
import json
import shutil
import subprocess


def locate_rg(config: dict) -> str | None:
    configured = config.get("rg_path", "").strip()
    if configured:
        return configured
    return shutil.which("rg.exe") or shutil.which("rg")


def build_command(query: str, profile: dict, config: dict) -> list[str]:
    rg = locate_rg(config)
    if not rg:
        raise FileNotFoundError("ripgrep was not found. Set rg_path in rg-search.json.")

    options = profile.get("options", {})
    command = [rg, "--json", "--line-number", "--column", "--color", "never"]
    command += ["--max-count", str(options.get("max_matches_per_file", 100))]
    command += ["--max-filesize", str(options.get("max_file_size", "10M"))]
    if options.get("regex", False) is False:
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
    for pattern in profile.get("include", []):
        command += ["--glob", pattern]
    for pattern in profile.get("exclude", []):
        command += ["--glob", f"!{pattern}"]
    command += [query, *profile.get("roots", [])]
    return command


def search(query: str, profile: dict, config: dict):
    """Yield normalised match dictionaries from ripgrep's stable JSON output."""
    command = build_command(query, profile, config)
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        for raw in process.stdout:
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if event.get("type") != "match":
                continue
            data = event["data"]
            yield {
                "path": data["path"]["text"],
                "line": data["line_number"],
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
