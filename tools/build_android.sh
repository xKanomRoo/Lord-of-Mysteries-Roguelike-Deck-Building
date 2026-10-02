#!/usr/bin/env bash
# Export and verify a native debug APK; no Gradle, browser wrapper or publishing.
if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  printf '%s\n' 'Run this script as a command; do not source it.' >&2
  return 2
fi
set -euo pipefail
gray_fog_repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
gray_fog_toolroot="$gray_fog_repo/.local/android-tools"
gray_fog_output="$gray_fog_repo/.local/android-artifacts/gray-fog-debug.apk"
while (($#)); do
  case "$1" in
    --tool-root) gray_fog_toolroot=$2; shift 2 ;;
    --output) gray_fog_output=$2; shift 2 ;;
    *) printf 'Unknown option: %s\n' "$1" >&2; exit 2 ;;
  esac
done
mapfile -t gray_fog_paths < <(python3 - "$gray_fog_toolroot" "$gray_fog_output" <<'PY'
import json,sys
from pathlib import Path
root=Path(sys.argv[1]).resolve()
p=json.loads((root/'toolchain-paths.json').read_text())
print(p['godot']); print(p['java']); print(p['sdk']); print(root)
print(Path(sys.argv[2]).resolve())
PY
)
if ((${#gray_fog_paths[@]} != 5)); then
  printf '%s\n' 'Run bash tools/setup_android.sh first.' >&2
  exit 2
fi
gray_fog_godot=${gray_fog_paths[0]}
export JAVA_HOME=${gray_fog_paths[1]}
export ANDROID_HOME=${gray_fog_paths[2]}
export ANDROID_SDK_ROOT="$ANDROID_HOME"
gray_fog_toolroot=${gray_fog_paths[3]}
gray_fog_output=${gray_fog_paths[4]}
export ANDROID_USER_HOME="$gray_fog_toolroot/android-user"
export XDG_CONFIG_HOME="$gray_fog_toolroot/xdg-config"
export XDG_DATA_HOME="$gray_fog_toolroot/xdg-data"
export XDG_CACHE_HOME="$gray_fog_toolroot/xdg-cache"
export PATH="$JAVA_HOME/bin:$ANDROID_HOME/platform-tools:$PATH"
mkdir -p -- "$(dirname -- "$gray_fog_output")" "$ANDROID_USER_HOME"
gray_fog_log="${gray_fog_output%.apk}.build.log"
python3 "$gray_fog_repo/tools/android_cloud_config.py" --project "$gray_fog_repo/mobile"
if [[ $("$gray_fog_godot" --version) != '4.6.3.stable.official.7d41c59c4' ]]; then
  printf '%s\n' 'Godot version differs from the pinned Android profile.' >&2
  exit 2
fi
# Import native resources first so the headless exporter cannot omit new assets.
"$gray_fog_godot" --headless --path "$gray_fog_repo/mobile" --editor --import --quit 2>&1 | tee "$gray_fog_log"
"$gray_fog_godot" --headless --path "$gray_fog_repo/mobile" --export-debug Android "$gray_fog_output" 2>&1 | tee -a "$gray_fog_log"
python3 - "$gray_fog_log" <<'PY'
import sys
from pathlib import Path
log = Path(sys.argv[1])
if any(line.startswith(('ERROR:', 'SCRIPT ERROR:')) for line in log.read_text().splitlines()):
    raise SystemExit(f'Godot reported an error; inspect {log}')
PY
python3 "$gray_fog_repo/tools/verify_android_apk.py" --apk "$gray_fog_output" --tool-root "$gray_fog_toolroot"
