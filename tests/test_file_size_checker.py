#!/usr/bin/env python3
"""Tests for file-size-checker-cli. Standard library unittest only."""

import ast
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import file_size_checker as fsc


def make_file(path, size):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


def run_cli(args, cwd=None):
    """Run main() with captured output. Returns (exit code, stdout, stderr)."""
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            code = fsc.main(args)
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


class TestParseLimit(unittest.TestCase):
    def test_bare_number_is_bytes(self):
        self.assertEqual(fsc.parse_limit("1024"), 1024)

    def test_decimal_units(self):
        self.assertEqual(fsc.parse_limit("1KB"), 1000)
        self.assertEqual(fsc.parse_limit("1MB"), 1000 ** 2)
        self.assertEqual(fsc.parse_limit("1GB"), 1000 ** 3)
        self.assertEqual(fsc.parse_limit("2TB"), 2 * 1000 ** 4)
        self.assertEqual(fsc.parse_limit("100MB"), 100 * 1000 ** 2)

    def test_binary_units(self):
        self.assertEqual(fsc.parse_limit("1KiB"), 1024)
        self.assertEqual(fsc.parse_limit("1MiB"), 1024 ** 2)
        self.assertEqual(fsc.parse_limit("1GiB"), 1024 ** 3)
        self.assertEqual(fsc.parse_limit("1TiB"), 1024 ** 4)

    def test_case_and_space(self):
        self.assertEqual(fsc.parse_limit("1mb"), 1000 ** 2)
        self.assertEqual(fsc.parse_limit("1.5 MB"), 1500000)
        self.assertEqual(fsc.parse_limit(" 500KB "), 500000)
        self.assertEqual(fsc.parse_limit("1b"), 1)

    def test_bad_limits(self):
        for bad in ("", "abc", "1XB", "1PB", "-5MB", "0", "0KB", "1.5.2MB"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    fsc.parse_limit(bad)


class TestFormatSize(unittest.TestCase):
    def test_bytes(self):
        self.assertEqual(fsc.format_size(0), "0 B")
        self.assertEqual(fsc.format_size(999), "999 B")

    def test_kilobytes(self):
        self.assertEqual(fsc.format_size(1000), "1.0 KB")
        self.assertEqual(fsc.format_size(1500), "1.5 KB")
        self.assertEqual(fsc.format_size(3180), "3.2 KB")

    def test_megabytes_and_up(self):
        self.assertEqual(fsc.format_size(1000 ** 2), "1.0 MB")
        self.assertEqual(fsc.format_size(2500000), "2.5 MB")
        self.assertEqual(fsc.format_size(1000 ** 3), "1.0 GB")
        self.assertEqual(fsc.format_size(3 * 1000 ** 4), "3.0 TB")


class TestCollectFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_single_file(self):
        target = make_file(self.base / "a.txt", 10)
        files, unreadable = fsc.collect_files([str(target)], True, [])
        self.assertEqual(files, [target])
        self.assertEqual(unreadable, [])

    def test_folder_recursive(self):
        make_file(self.base / "a.txt", 10)
        make_file(self.base / "sub" / "b.txt", 20)
        make_file(self.base / "sub" / "deep" / "c.txt", 30)
        files, _ = fsc.collect_files([str(self.base)], True, [])
        self.assertEqual(
            [str(p) for p in files],
            [str(self.base / "a.txt"),
             str(self.base / "sub" / "b.txt"),
             str(self.base / "sub" / "deep" / "c.txt")],
        )

    def test_folder_not_recursive(self):
        make_file(self.base / "a.txt", 10)
        make_file(self.base / "sub" / "b.txt", 20)
        files, _ = fsc.collect_files([str(self.base)], False, [])
        self.assertEqual([str(p) for p in files], [str(self.base / "a.txt")])

    def test_missing_path_raises(self):
        with self.assertRaises(ValueError):
            fsc.collect_files([str(self.base / "nope.txt")], True, [])

    def test_exclude_by_name(self):
        make_file(self.base / "keep.txt", 10)
        make_file(self.base / "skip.log", 20)
        files, _ = fsc.collect_files([str(self.base)], True, ["*.log"])
        self.assertEqual([p.name for p in files], ["keep.txt"])

    def test_exclude_by_path(self):
        make_file(self.base / "sub" / "skip.txt", 10)
        make_file(self.base / "keep.txt", 10)
        files, _ = fsc.collect_files(
            [str(self.base)], True, ["*" + os.sep + "sub" + os.sep + "*"]
        )
        self.assertEqual([p.name for p in files], ["keep.txt"])

    def test_git_folder_skipped(self):
        make_file(self.base / ".git" / "objects" / "big.bin", 10)
        make_file(self.base / "a.txt", 10)
        files, _ = fsc.collect_files([str(self.base)], True, [])
        self.assertEqual([p.name for p in files], ["a.txt"])

    def test_directory_symlink_not_followed(self):
        real = make_file(self.base / "real" / "a.txt", 10)
        os.symlink(self.base / "real", self.base / "link")
        files, _ = fsc.collect_files([str(self.base)], True, [])
        self.assertEqual(files, [real])

    def test_broken_symlink_is_unreadable(self):
        target = self.base / "gone.txt"
        link = self.base / "link.txt"
        os.symlink(target, link)
        files, unreadable = fsc.collect_files([str(link)], True, [])
        self.assertEqual(files, [])
        self.assertEqual(len(unreadable), 1)
        self.assertIn("link.txt", unreadable[0][0])

    def test_empty_folder(self):
        files, unreadable = fsc.collect_files([str(self.base)], True, [])
        self.assertEqual(files, [])
        self.assertEqual(unreadable, [])


class TestCheckFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_under_and_at_limit_pass(self):
        small = make_file(self.base / "small.txt", 999)
        exact = make_file(self.base / "exact.txt", 1000)
        self.assertEqual(fsc.check_files([small, exact], 1000), [])

    def test_one_byte_over_fails(self):
        over = make_file(self.base / "over.txt", 1001)
        result = fsc.check_files([over], 1000)
        self.assertEqual(result, [(str(over), 1001)])

    def test_multiple_over_sorted(self):
        b = make_file(self.base / "b.txt", 2000)
        a = make_file(self.base / "a.txt", 3000)
        files, _ = fsc.collect_files([str(self.base)], True, [])
        result = fsc.check_files(files, 1000)
        self.assertEqual(
            result, [(str(a), 3000), (str(b), 2000)]
        )


class TestCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_pass_exit_zero(self):
        make_file(self.base / "a.txt", 10)
        code, out, _ = run_cli(["--limit", "1KB", str(self.base)])
        self.assertEqual(code, 0)
        self.assertIn("PASS", out)
        self.assertIn("Checked 1 file(s), 0 over", out)

    def test_fail_exit_one_names_file_and_size(self):
        big = make_file(self.base / "big.txt", 2048)
        code, out, _ = run_cli(["--limit", "1KB", str(self.base)])
        self.assertEqual(code, 1)
        self.assertIn(str(big), out)
        self.assertIn("2.0 KB", out)
        self.assertIn("FAIL", out)

    def test_default_limit_is_100mb(self):
        make_file(self.base / "a.txt", 10)
        code, out, _ = run_cli([str(self.base)])
        self.assertEqual(code, 0)
        self.assertIn("limit of 100.0 MB", out)

    def test_missing_path_exit_two(self):
        code, _, err = run_cli([str(self.base / "nope")])
        self.assertEqual(code, 2)
        self.assertIn("no such file or folder", err)

    def test_bad_limit_exit_two(self):
        code, _, err = run_cli(["--limit", "1XB", str(self.base)])
        self.assertEqual(code, 2)
        self.assertIn("bad limit", err)

    def test_bad_flag_exit_two(self):
        code, _, _ = run_cli(["--nope", str(self.base)])
        self.assertEqual(code, 2)

    def test_empty_folder_exit_one(self):
        code, out, _ = run_cli([str(self.base)])
        self.assertEqual(code, 1)
        self.assertIn("No files found", out)

    def test_no_recursive_flag(self):
        make_file(self.base / "a.txt", 10)
        make_file(self.base / "sub" / "b.txt", 5000)
        code, out, _ = run_cli(
            ["--limit", "1KB", "--no-recursive", str(self.base)]
        )
        self.assertEqual(code, 0)
        self.assertIn("Checked 1 file(s)", out)

    def test_exclude_flag(self):
        make_file(self.base / "keep.txt", 10)
        make_file(self.base / "skip.log", 5000)
        code, out, _ = run_cli(
            ["--limit", "1KB", "--exclude", "*.log", str(self.base)]
        )
        self.assertEqual(code, 0)
        self.assertIn("Checked 1 file(s)", out)

    def test_json_output(self):
        big = make_file(self.base / "big.txt", 2048)
        make_file(self.base / "small.txt", 10)
        code, out, err = run_cli(["--limit", "1KB", "--json", str(self.base)])
        self.assertEqual(code, 1)
        data = json.loads(out)
        self.assertEqual(data["checked"], 2)
        self.assertEqual(data["limit_bytes"], 1000)
        self.assertFalse(data["pass"])
        self.assertEqual(len(data["over"]), 1)
        self.assertEqual(data["over"][0]["path"], str(big))
        self.assertEqual(data["over"][0]["size_bytes"], 2048)
        self.assertIn("FAIL", err)

    def test_json_pass(self):
        make_file(self.base / "a.txt", 10)
        code, out, err = run_cli(["--limit", "1KB", "--json", str(self.base)])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertTrue(data["pass"])
        self.assertEqual(data["over"], [])
        self.assertIn("PASS", err)

    def test_version(self):
        code, out, _ = run_cli(["--version"])
        self.assertEqual(code, 0)
        self.assertIn("1.0.0", out)

    def test_input_files_unchanged(self):
        target = make_file(self.base / "a.txt", 5000)
        before = target.read_bytes()
        run_cli(["--limit", "1KB", str(self.base)])
        self.assertEqual(target.read_bytes(), before)


class TestExamples(unittest.TestCase):
    def test_sample_output_matches_fresh_run(self):
        expected = (ROOT / "examples" / "sample-output.txt").read_text()
        result = subprocess.run(
            ["sh", "examples/run-example.sh"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, expected)

    def test_run_example_script_exits_zero(self):
        result = subprocess.run(
            ["sh", "examples/run-example.sh"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("FAIL", result.stdout)
        self.assertIn("PASS", result.stdout)

    def test_example_files_have_expected_sizes(self):
        examples = ROOT / "examples"
        self.assertEqual((examples / "small.txt").stat().st_size, 36)
        self.assertEqual((examples / "big.txt").stat().st_size, 3180)
        self.assertEqual((examples / "nested" / "deep.txt").stat().st_size, 2205)


class TestStdlibOnly(unittest.TestCase):
    def test_source_imports_stdlib_only(self):
        allowed = {
            "argparse", "fnmatch", "json", "os", "re", "sys", "pathlib",
        }
        tree = ast.parse((ROOT / "src" / "file_size_checker.py").read_text())
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".")[0])
        self.assertEqual(imports, allowed)

    def test_test_file_imports_stdlib_only(self):
        allowed = {
            "ast", "io", "json", "os", "subprocess", "sys", "tempfile",
            "unittest", "contextlib", "pathlib", "file_size_checker",
            # file_size_checker is the module under test, not a dependency.
        }
        tree = ast.parse(Path(__file__).read_text())
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".")[0])
        self.assertTrue(imports <= allowed, "unexpected imports: %s" % (imports - allowed))


class TestHygiene(unittest.TestCase):
    def test_no_placeholders_or_secrets(self):
        # The banned-word list itself lives in this test file, so
        # tests/ is excluded from the scan (the Day 22 pattern).
        # .git and __pycache__ are excluded too (the Day 21 rule):
        # GitHub's checkout ships sample hooks under .git/hooks/
        # that contain "TODO".
        banned = ["TODO", "FIXME", "coming soon", "lorem", "API_KEY"]
        hits = []
        for path in ROOT.rglob("*"):
            if ".git" in path.parts or "__pycache__" in path.parts:
                continue
            if "tests" in path.relative_to(ROOT).parts:
                continue
            if not path.is_file():
                continue
            text = path.read_bytes().decode("utf-8", errors="ignore")
            for word in banned:
                if word in text:
                    hits.append((str(path.relative_to(ROOT)), word))
        self.assertEqual(hits, [])

    def test_no_absolute_paths(self):
        hits = []
        for path in ROOT.rglob("*"):
            if ".git" in path.parts or "__pycache__" in path.parts:
                continue
            if "tests" in path.relative_to(ROOT).parts:
                continue
            if not path.is_file():
                continue
            text = path.read_bytes().decode("utf-8", errors="ignore")
            if "/home/" in text or "C:\\" in text:
                hits.append(str(path.relative_to(ROOT)))
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
