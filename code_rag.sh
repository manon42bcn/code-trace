#!/bin/sh
set -eu

cd "$(dirname "$0")"
config=${1:-config.example.json}
make setup
make indexes CONFIG="$config"
make evaluate-real CONFIG="$config"
