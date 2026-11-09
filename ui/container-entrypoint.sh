#!/bin/bash
set -euo pipefail
case "${1:-}" in
    watch) yarn install --immutable; exec yarn watch ;;
    build) exec ./build.sh ;;
    *) echo "Append 'watch' or 'build'" >&2; exit 2 ;;
esac
