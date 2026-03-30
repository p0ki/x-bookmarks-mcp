#!/usr/bin/env python3
"""Scan git-tracked files for private/local data leaks.

Catches:
- Windows user paths (C:\\Users\\..., D:\\Projekti\\...)
- Unix home paths (/home/..., /Users/...)
- Private IPv4 ranges (192.168.x.x, 10.x.x.x, 172.16-31.x.x)
- Localhost with non-standard ports

Usage:
    python scripts/check_private_data.py
    Exit code 0 = clean, 1 = findings.
"""

import re
import subprocess
import sys
from pathlib import Path

# --- Patterns ---

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "Windows user path",
        re.compile(r"[A-Z]:\\Users\\", re.IGNORECASE),
    ),
    (
        "Windows project path",
        re.compile(r"[A-Z]:\\Projekti\\", re.IGNORECASE),
    ),
    (
        "Unix home path",
        re.compile(r"(?<!/usr)/home/\w+", re.IGNORECASE),
    ),
    (
        "macOS user path",
        re.compile(r"/Users/\w+"),
    ),
    (
        "Private IP (192.168.x.x)",
        re.compile(r"\b192\.168\.\d{1,3}\.\d{1,3}\b"),
    ),
    (
        "Private IP (10.x.x.x)",
        re.compile(r"\b10\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"),
    ),
    (
        "Private IP (172.16-31.x.x)",
        re.compile(r"\b172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}\b"),
    ),
    (
        "Localhost non-standard port",
        re.compile(r"\b127\.0\.0\.1:(?!(?:3000|5000|8000|8080)\b)\d{2,5}\b"),
    ),
]

# Files to skip (relative to repo root).
SKIP_FILES: set[str] = {
    "scripts/check_private_data.py",
}

# Binary file extensions to skip.
BINARY_EXTENSIONS: set[str] = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2",
    ".ttf", ".eot", ".db", ".sqlite", ".pyc", ".zip", ".tar",
    ".gz", ".pdf",
}

# Lines matching these patterns are structural false positives.
FALSE_POSITIVE_PATTERNS: list[re.Pattern[str]] = [
    # "FETCH_TIMEOUT_SECONDS=10" is not a 10.x.x.x IP
    re.compile(r"^\s*\w+=\d+\s*$"),
    # Timeout/retry values like "timeout=10" or "delay: 10"
    re.compile(r"(?:timeout|delay|retries|max_retries|limit)\s*[=:]\s*\d+"),
]


def get_tracked_files() -> list[str]:
    """Return list of git-tracked file paths."""
    result = subprocess.run(
        ["git", "ls-files"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [f for f in result.stdout.strip().split("\n") if f]


def is_binary(filepath: str) -> bool:
    """Check if file has a binary extension."""
    return Path(filepath).suffix.lower() in BINARY_EXTENSIONS


def scan_file(filepath: str) -> list[tuple[int, str, str]]:
    """Scan a single file. Returns list of (line_number, pattern_name, line)."""
    findings: list[tuple[int, str, str]] = []
    try:
        with open(filepath, encoding="utf-8", errors="ignore") as f:
            for line_num, line in enumerate(f, start=1):
                # Inline suppression (works in any file type)
                if "noqa: private-data" in line:
                    continue

                # Skip structural false positives
                if any(fp.search(line) for fp in FALSE_POSITIVE_PATTERNS):
                    continue

                for pattern_name, pattern in PATTERNS:
                    if pattern.search(line):
                        findings.append((line_num, pattern_name, line.rstrip()))
                        break  # One finding per line is enough
    except OSError:
        pass
    return findings


def main() -> int:
    """Run the scan. Returns 0 if clean, 1 if findings."""
    files = get_tracked_files()
    total_findings: list[tuple[str, int, str, str]] = []

    for filepath in files:
        if filepath in SKIP_FILES:
            continue
        if is_binary(filepath):
            continue

        findings = scan_file(filepath)
        for line_num, pattern_name, line in findings:
            total_findings.append((filepath, line_num, pattern_name, line))

    if total_findings:
        print(f"\n{'='*60}")
        print(f"PRIVATE DATA SCAN: {len(total_findings)} finding(s)")
        print(f"{'='*60}\n")
        for filepath, line_num, pattern_name, line in total_findings:
            print(f"  {filepath}:{line_num}")
            print(f"    Pattern: {pattern_name}")
            print(f"    Line:    {line}")
            print()
        print("To suppress a false positive, add '# noqa: private-data' to the line.")
        return 1

    print("Private data scan: CLEAN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
