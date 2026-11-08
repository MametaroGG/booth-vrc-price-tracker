#!/usr/bin/env bash
# DRY RUN ONLY: prepare one coherent snapshot commit plan. Never pushes files.
# Existing github credential/tool configuration is deliberately left untouched.
set -euo pipefail
HERE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
exec python3 "$HERE/prepare_deployment.py" "$@"
