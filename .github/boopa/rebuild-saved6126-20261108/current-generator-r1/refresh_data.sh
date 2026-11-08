#!/usr/bin/env bash
# Offline refresh: explicit producer-completed snapshot -> new validated candidate.
# No downloads, directory swaps, collection, publication, or credentials changes.
set -euo pipefail
HERE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
exec python3 "$HERE/build_site.py" "$@"
