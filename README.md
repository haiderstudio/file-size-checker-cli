# file-size-checker-cli

Check no file is bigger than your limit, fail CI on an oversized file.

[![CI](https://github.com/haiderstudio/file-size-checker-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/haiderstudio/file-size-checker-cli/actions/workflows/ci.yml) [![Licence: MIT](https://img.shields.io/badge/Licence-MIT-yellow.svg)](LICENSE)

## What it does

`file_size_checker` walks the files and folders you name, compares
every file's size with a limit you set, and reports every file over
it with its path and size. The default limit is 100 MB — the GitHub
push limit — so a run with no flags answers the question "can I push
this folder?" It exits 1 when a file is over the limit, so it can
fail a CI run before a huge file lands in the repo.

- `--limit` sets the limit: a number and a unit, like `1MB`, `500KB`,
  `1.5 GB`, or a bare number of bytes. Decimal units (KB = 1000
  bytes) and binary units (KiB = 1024 bytes) both work.
- Give it files, folders, or both. Folders are walked recursively
  unless you pass `--no-recursive`. A `.git` folder is never walked,
  and directory links are never followed, so a link cycle cannot
  loop the check.
- `--exclude PATTERN` skips files whose name matches a glob, and can
  be repeated. `--json` prints the result as JSON instead of plain
  text, for scripts.
- It is report-only and runs fully offline: it never deletes, moves,
  or changes a file, sends nothing anywhere, and needs no API key.

## What it does NOT do

- It does not delete or move oversized files. If a file is too big,
  removing it or shrinking it is your job.
- It does not check the total size of a folder, only each file on
  its own. Ten 90 MB files pass a 100 MB limit, even though the
  folder holds 900 MB.
- It does not check file types, line counts, or diff sizes. Line
  counts in a change are covered by commit-size-checker-cli.
- It does not block a push by itself. It only reports and exits 1;
  your CI or hook decides what to do with that.

## Who it is for

Anyone who has pushed a huge file by mistake: a developer keeping
build output and videos out of a repo, a team that agreed on a file
size limit and wants CI to enforce it, or anyone adding a one-line
guard to a pre-commit hook. If every file is under the limit, you
get a short PASS; if one is over, the report names it and its size.

## How this differs from similar tools

Most file-size tools only list sizes. The nearest GitHub results for
this job are small untested scripts: Lazaris02/FileSizeChecker
(0 stars, Python) is a script that finds files over a size in MB,
Noah-Herron/FileSizeChecker (0 stars, Python) lists files in
descending size order, and SumukhPhulari10/FileSizeChecker (0 stars,
Python) analyses sizes with coloured output. The closest tested
tool, fs-size-checker (1 star, TypeScript, an npm package), checks
file *and* directory sizes against limits with exit codes — but it
needs Node, and it measures whole folders, not each file on its own.
None of them is a Python standard-library-only CLI that checks each
file against a limit you set, reports every oversized file, and
fails CI.

This tool does that one narrow job: a Python standard-library-only
CLI, no install beyond Python, no network, no Node — one limit, one
check, per file.

## Install

Python standard library only — no packages to download. Clone the
repo and run it in place:

```sh
git clone https://github.com/haiderstudio/file-size-checker-cli.git
cd file-size-checker-cli
```

Python 3.10 or newer.

## Usage

Check the example files against a 1 KB limit:

```sh
python3 src/file_size_checker.py --limit 1KB examples/small.txt examples/big.txt examples/nested
```

Real output:

```text
examples/big.txt: 3.2 KB (limit 1.0 KB)
examples/nested/deep.txt: 2.2 KB (limit 1.0 KB)
Checked 3 file(s), 2 over the limit of 1.0 KB.
FAIL — 2 file(s) over the limit.
```

The command exits 1. The same output is saved in
`examples/sample-output.txt`.

Check the same files against a 1 MB limit:

```sh
python3 src/file_size_checker.py --limit 1MB examples/small.txt examples/big.txt examples/nested
```

Real output:

```text
Checked 3 file(s), 0 over the limit of 1.0 MB.
PASS — all 3 file(s) under the limit of 1.0 MB.
```

The command exits 0.

Check a whole folder with the default 100 MB limit:

```sh
python3 src/file_size_checker.py examples
```

Real output:

```text
Checked 5 file(s), 0 over the limit of 100.0 MB.
PASS — all 5 file(s) under the limit of 100.0 MB.
```

Check one file, as JSON:

```sh
python3 src/file_size_checker.py --limit 1KB --json examples/small.txt examples/big.txt examples/nested
```

Real output (the summary goes to standard error):

```text
{
  "checked": 3,
  "limit_bytes": 1000,
  "limit": "1.0 KB",
  "pass": false,
  "over": [
    {
      "path": "examples/big.txt",
      "size_bytes": 3180,
      "size": "3.2 KB"
    },
    {
      "path": "examples/nested/deep.txt",
      "size_bytes": 2205,
      "size": "2.2 KB"
    }
  ],
  "unreadable": []
}
```

## Examples

### 1. Fail CI on one oversized file

`examples/big.txt` is 3180 bytes. A 3 KB limit catches it and
passes the other two files:

```sh
python3 src/file_size_checker.py --limit 3KB examples/small.txt examples/big.txt examples/nested
echo $?
```

```text
examples/big.txt: 3.2 KB (limit 3.0 KB)
Checked 3 file(s), 1 over the limit of 3.0 KB.
FAIL — 1 file(s) over the limit.
1
```

The exit code is 1 when a file is over the limit. Put the same
command in CI and the build fails until the file is removed or the
limit is raised on purpose.

### 2. Top level only, and skipping files

`--no-recursive` checks only the top level of a folder, so the file
in `examples/nested/` is not seen:

```sh
python3 src/file_size_checker.py --limit 1KB --no-recursive examples
```

```text
examples/big.txt: 3.2 KB (limit 1.0 KB)
Checked 4 file(s), 1 over the limit of 1.0 KB.
FAIL — 1 file(s) over the limit.
```

`--exclude` skips files by name. This run skips every `.txt` file,
so only the example script is checked:

```sh
python3 src/file_size_checker.py --limit 1KB --exclude '*.txt' examples
```

```text
Checked 1 file(s), 0 over the limit of 1.0 KB.
PASS — all 1 file(s) under the limit of 1.0 KB.
```

A bad limit is a usage error, exit 2, not a fail:

```sh
python3 src/file_size_checker.py --limit 1XB examples
```

```text
error: bad limit '1XB' — unknown unit 'XB', use B, KB, MB, GB, TB, or KiB, MiB, GiB, TiB
```

## How it is tested

Run the tests from the repo root:

```sh
python3 tests/test_file_size_checker.py
```

41 tests, standard library `unittest` only. They cover limit
parsing (decimal and binary units, decimals, bad units, zero),
size formatting, file collection (single files, recursive and
non-recursive folders, `--exclude` by name and by path, `.git`
skipped, directory links not followed, broken links reported),
the limit check (exactly at the limit passes, one byte over
fails), the CLI (exit codes 0/1/2, JSON output, `--version`,
usage errors, input files unchanged), and the bundled examples
(the committed `sample-output.txt` is compared against a fresh
run of `examples/run-example.sh`).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

MIT — see [LICENSE](LICENSE).

## Original work

This tool was written from scratch for this repo. The idea — keep
oversized files out of a repo with a size limit — is a common team
rule; the code, tests, and examples here are original.
