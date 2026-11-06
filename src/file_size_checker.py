#!/usr/bin/env python3
"""Check no file is bigger than a size limit you set.

One job only: read the files and folders you name, compare every
file's size with a limit (default 100 MB, the GitHub push limit),
and report every file over it with its path and size. It never
deletes or changes a file, runs fully offline, and needs no network
at all.

Exit codes: 0 = every file is under the limit, 1 = one or more files
are over the limit (or a file could not be read, or no files were
found), 2 = a usage error (bad limit, missing path, bad flag).

Standard library only.
"""

import argparse
import fnmatch
import json
import os
import re
import sys
from pathlib import Path

VERSION = "1.0.0"

DEFAULT_LIMIT = "100MB"

# Decimal units (KB = 1000 bytes, the way file sizes are usually
# talked about) and binary units (KiB = 1024 bytes).
UNITS = {
    "": 1,
    "B": 1,
    "KB": 1000,
    "MB": 1000 ** 2,
    "GB": 1000 ** 3,
    "TB": 1000 ** 4,
    "KIB": 1024,
    "MIB": 1024 ** 2,
    "GIB": 1024 ** 3,
    "TIB": 1024 ** 4,
}

LIMIT_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([a-zA-Z]{0,3})\s*$")

# A .git folder is version-control data, not the user's files, so it
# is never walked. Everything else is checked, hidden files included.
SKIPPED_DIRS = {".git"}


def parse_limit(text):
    """Turn a limit like "1MB", "500KB", "1.5 MB", "1024" into bytes.

    Raises ValueError with a plain message for anything that is not
    a positive number with a known unit.
    """
    match = LIMIT_RE.match(text)
    if not match:
        raise ValueError(
            "bad limit %r — use a number and a unit, like 1MB or 500KB" % text
        )
    number, unit = match.groups()
    unit = unit.upper()
    if unit not in UNITS:
        raise ValueError(
            "bad limit %r — unknown unit %r, use B, KB, MB, GB, TB, "
            "or KiB, MiB, GiB, TiB" % (text, unit)
        )
    size = int(float(number) * UNITS[unit])
    if size <= 0:
        raise ValueError("bad limit %r — the limit must be more than 0" % text)
    return size


def format_size(size):
    """Turn a byte count into a short human size, like "3.0 KB"."""
    if size < 1000:
        return "%d B" % size
    for unit in ("KB", "MB", "GB", "TB"):
        size = size / 1000.0
        if size < 1000 or unit == "TB":
            return "%.1f %s" % (size, unit)
    return "%d B" % size  # never reached


def is_excluded(path, patterns):
    """True when a file name or path matches any --exclude pattern."""
    name = path.name
    text = str(path)
    return any(
        fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(text, pattern)
        for pattern in patterns
    )


def collect_files(paths, recursive, exclude):
    """Return (files, unreadable) for the given files and folders.

    Files are returned sorted by path so output is the same every
    run. Directory symlinks are not followed, so a link cycle cannot
    loop the walk. A file that cannot be read is reported in
    `unreadable` instead of stopping the check.
    """
    files = []
    unreadable = []
    for given in paths:
        path = Path(given)
        if not path.exists() and not path.is_symlink():
            raise ValueError("no such file or folder: %s" % given)
        if path.is_file() or path.is_symlink():
            if is_excluded(path, exclude):
                continue
            try:
                path.stat()
            except OSError as exc:
                unreadable.append((str(path), str(exc)))
                continue
            files.append(path)
            continue
        # A folder: walk it.
        for root, dirs, names in os.walk(path, followlinks=False):
            dirs[:] = sorted(d for d in dirs if d not in SKIPPED_DIRS)
            for name in sorted(names):
                candidate = Path(root) / name
                if is_excluded(candidate, exclude):
                    continue
                try:
                    candidate.stat()
                except OSError as exc:
                    unreadable.append((str(candidate), str(exc)))
                    continue
                files.append(candidate)
            if not recursive:
                break
    files.sort(key=str)
    return files, unreadable


def check_files(files, limit):
    """Return the files over the limit as (path, size) pairs."""
    over = []
    for path in files:
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size > limit:
            over.append((str(path), size))
    return over


def build_parser():
    parser = argparse.ArgumentParser(
        prog="file_size_checker",
        description="Check no file is bigger than your limit.",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=["."],
        help="files or folders to check (default: the current folder)",
    )
    parser.add_argument(
        "--limit",
        default=DEFAULT_LIMIT,
        help='size limit, like "1MB" or "500KB" (default: %(default)s)',
    )
    parser.add_argument(
        "--no-recursive",
        action="store_true",
        help="check only the top level of a folder, not its subfolders",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="PATTERN",
        help="skip files whose name matches this glob (repeatable)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print the result as JSON instead of plain text",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s " + VERSION,
    )
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        limit = parse_limit(args.limit)
    except ValueError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2

    try:
        files, unreadable = collect_files(
            args.paths, not args.no_recursive, args.exclude
        )
    except ValueError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2

    over = check_files(files, limit)
    passed = bool(files) and not over and not unreadable

    if args.json:
        result = {
            "checked": len(files),
            "limit_bytes": limit,
            "limit": format_size(limit),
            "pass": passed,
            "over": [
                {"path": path, "size_bytes": size, "size": format_size(size)}
                for path, size in over
            ],
            "unreadable": [
                {"path": path, "error": error} for path, error in unreadable
            ],
        }
        print(json.dumps(result, indent=2))
        if not files:
            print("No files found.", file=sys.stderr)
        elif passed:
            print(
                "PASS — all %d file(s) under the limit of %s."
                % (len(files), format_size(limit)),
                file=sys.stderr,
            )
        else:
            print(
                "FAIL — %d file(s) over the limit of %s."
                % (len(over) + len(unreadable), format_size(limit)),
                file=sys.stderr,
            )
        return 0 if passed else 1

    if not files:
        print("No files found.")
        return 1

    for path, size in over:
        print("%s: %s (limit %s)" % (path, format_size(size), format_size(limit)))
    for path, error in unreadable:
        print("%s: could not read (%s)" % (path, error))
    print(
        "Checked %d file(s), %d over the limit of %s."
        % (len(files), len(over), format_size(limit))
    )
    if passed:
        print("PASS — all %d file(s) under the limit of %s."
              % (len(files), format_size(limit)))
        return 0
    problems = len(over) + len(unreadable)
    print("FAIL — %d file(s) over the limit." % problems)
    return 1


if __name__ == "__main__":
    sys.exit(main())
