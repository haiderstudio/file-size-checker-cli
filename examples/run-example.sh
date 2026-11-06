#!/bin/sh
# Check the example files against a 1 KB limit, then against 1 MB.
# Run from the repo root: sh examples/run-example.sh
set -e
python3 src/file_size_checker.py --limit 1KB examples/small.txt examples/big.txt examples/nested || true
python3 src/file_size_checker.py --limit 1MB examples/small.txt examples/big.txt examples/nested
