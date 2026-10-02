#!/usr/bin/env bash
# Installs pinned, official Linux x86_64 tooling into the ignored local directory.
if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  printf '%s\n' 'Run this script as a command; do not source it.' >&2
  return 2
fi
set -euo pipefail
gray_fog_repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
python3 "$gray_fog_repo/tools/setup_android.py" "$@"
