"""Synchronize the version string across pyproject.toml, __init__.py, conf.py.

Run by the release CI workflow on tag push. Can also be invoked manually
for a dry run.

Usage::

    python sync_version.py 0.1.1
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

TARGETS: list[tuple[Path, re.Pattern[str], str]] = [
    (
        ROOT / "pyproject.toml",
        re.compile(r'^version\s*=\s*"[^"]*"\s*$', re.MULTILINE),
        'version = "{v}"',
    ),
    (
        ROOT / "pyGigEVision" / "__init__.py",
        re.compile(r'^__version__\s*=\s*"[^"]*"\s*$', re.MULTILINE),
        '__version__ = "{v}"',
    ),
    (
        ROOT / "docs" / "source" / "conf.py",
        re.compile(r'^release\s*=\s*"[^"]*"\s*$', re.MULTILINE),
        'release = "{v}"',
    ),
]


def sync(version: str) -> None:
    """Write ``version`` into each of the configured target files."""
    if not re.fullmatch(r"\d+\.\d+\.\d+([abrc]\d+|\.dev\d+)?", version):
        raise SystemExit(f"Bad version string: {version!r}")

    for path, pattern, fmt in TARGETS:
        text = path.read_text(encoding="utf-8")
        new_line = fmt.format(v=version)
        if not pattern.search(text):
            raise SystemExit(f"Could not find version line in {path}")
        new_text = pattern.sub(new_line, text)
        if new_text == text:
            print(f"unchanged: {path}")
        else:
            path.write_text(new_text, encoding="utf-8")
            print(f"updated:   {path} -> {new_line}")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(f"Usage: {sys.argv[0]} <version>")
    sync(sys.argv[1])


if __name__ == "__main__":
    main()
