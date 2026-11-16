#!/bin/sh
set -eu

# Replace these smoke checks with your project's test command.
test -s .github/workflows/ci.yml
test -s .github/workflows/release.yml
test -s scripts/release.py
