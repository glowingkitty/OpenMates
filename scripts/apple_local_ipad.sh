#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/apple_local_ipad.sh [options]

Build, install, and launch OpenMates on a connected physical iPad using the
reduced Personal Team entitlements. This intentionally avoids paid-team
capabilities such as Associated Domains and App Groups.

Options:
  --device ID                 CoreDevice identifier for devicectl install
  --xcode-destination-id ID   Device UDID/id for xcodebuild -destination
  --team TEAM_ID              Apple Development team id
  --derived-data PATH         Xcode derived data path
                              (default: .derivedData/local-ipad-personal)
  --no-launch                 Install but do not launch
  -h, --help                  Show this help

Environment:
  OPENMATES_DEVICE_ID
  OPENMATES_XCODE_DESTINATION_ID
  OPENMATES_DEVELOPMENT_TEAM
  OPENMATES_IPAD_DERIVED_DATA
EOF
}

log() {
  printf '[openmates:ipad] %s\n' "$*"
}

die() {
  printf '[openmates:ipad] error: %s\n' "$*" >&2
  exit 1
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

device_id="${OPENMATES_DEVICE_ID:-}"
xcode_destination_id="${OPENMATES_XCODE_DESTINATION_ID:-}"
team_id="${OPENMATES_DEVELOPMENT_TEAM:-}"
derived_data="${OPENMATES_IPAD_DERIVED_DATA:-.derivedData/local-ipad-personal}"
launch_app=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --device)
      [[ $# -ge 2 ]] || die "--device requires an id"
      device_id="$2"
      shift 2
      ;;
    --xcode-destination-id)
      [[ $# -ge 2 ]] || die "--xcode-destination-id requires an id"
      xcode_destination_id="$2"
      shift 2
      ;;
    --team)
      [[ $# -ge 2 ]] || die "--team requires a team id"
      team_id="$2"
      shift 2
      ;;
    --derived-data)
      [[ $# -ge 2 ]] || die "--derived-data requires a path"
      derived_data="$2"
      shift 2
      ;;
    --no-launch)
      launch_app=0
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "unknown option: $1"
      ;;
  esac
done

infer_team_id() {
  local xcode_team
  xcode_team="$(defaults read com.apple.dt.Xcode IDEProvisioningTeamManagerLastSelectedTeamID 2>/dev/null || true)"
  if [[ "$xcode_team" =~ ^[A-Z0-9]+$ ]]; then
    printf '%s\n' "$xcode_team"
    return 0
  fi

  local teams=()
  while IFS= read -r team; do
    [[ -n "$team" ]] && teams+=("$team")
  done < <(security find-identity -v -p codesigning | sed -En 's/.*"Apple Development: .* \(([A-Z0-9]+)\)".*/\1/p' | sort -u)

  if [[ "${#teams[@]}" -eq 1 ]]; then
    printf '%s\n' "${teams[0]}"
    return 0
  fi

  return 1
}

detect_ipad() {
  local json_path
  json_path="$(mktemp "${TMPDIR:-/tmp}/openmates-devices.XXXXXX")"
  xcrun devicectl list devices --json-output "$json_path" >/dev/null

  python3 - "$json_path" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as handle:
    payload = json.load(handle)

devices = payload.get("result", {}).get("devices", [])

def is_connected_ios(device):
    hardware = device.get("hardwareProperties", {})
    connection = device.get("connectionProperties", {})
    return (
        hardware.get("platform") == "iOS"
        and hardware.get("deviceType") == "iPad"
        and connection.get("tunnelState") == "connected"
    )

candidates = [device for device in devices if is_connected_ios(device)]
if not candidates:
    candidates = [
        device for device in devices
        if device.get("hardwareProperties", {}).get("platform") == "iOS"
        and device.get("connectionProperties", {}).get("tunnelState") == "connected"
    ]

if not candidates:
    sys.exit(1)

device = candidates[0]
hardware = device.get("hardwareProperties", {})
name = device.get("deviceProperties", {}).get("name", "<unknown>")
print("\t".join([
    device.get("identifier", ""),
    hardware.get("udid", ""),
    name,
]))
PY
}

if [[ -z "$team_id" ]]; then
  if team_id="$(infer_team_id)"; then
    log "Using Apple Development team $team_id from local Xcode signing settings."
  else
    die "Could not infer a single Apple Development team. Pass --team TEAM_ID or set OPENMATES_DEVELOPMENT_TEAM."
  fi
fi

if [[ -z "$device_id" ]]; then
  if detected="$(detect_ipad)"; then
    IFS=$'\t' read -r device_id detected_udid detected_name <<<"$detected"
    if [[ -z "$xcode_destination_id" && -n "$detected_udid" ]]; then
      xcode_destination_id="$detected_udid"
    fi
    log "Using connected device: $detected_name ($device_id)"
  else
    die "No connected iPad/iOS device found. Connect and unlock the iPad, or pass --device."
  fi
fi

if [[ -z "$xcode_destination_id" ]]; then
  xcode_destination_id="$device_id"
fi

log "Building OpenMates_iOS for destination id=$xcode_destination_id..."
build_log="$(mktemp "${TMPDIR:-/tmp}/openmates-ipad-build.XXXXXX")"
if ! xcodebuild \
    -project apple/OpenMates.xcodeproj \
    -scheme OpenMates_iOS \
    -configuration Debug \
    -destination "id=$xcode_destination_id" \
    -derivedDataPath "$derived_data" \
    -allowProvisioningUpdates \
    -allowProvisioningDeviceRegistration \
    CODE_SIGN_STYLE=Automatic \
    DEVELOPMENT_TEAM="$team_id" \
    CODE_SIGN_ENTITLEMENTS=OpenMates/Resources/OpenMatesPersonalTeam.entitlements \
    build 2>&1 | tee "$build_log"; then
  if grep -q "No Accounts" "$build_log"; then
    cat >&2 <<'EOF'

[openmates:ipad] Xcode command-line signing cannot see an Apple account.
[openmates:ipad] The script found a local Apple Development certificate, but
[openmates:ipad] xcodebuild still needs access to the Xcode account token to
[openmates:ipad] create free Personal Team provisioning profiles.
[openmates:ipad]
[openmates:ipad] Try running this same script once from Terminal. If Terminal
[openmates:ipad] shows the same error, open Xcode > Settings > Accounts,
[openmates:ipad] select the Personal Team, and refresh/download profiles.
EOF
  fi
  die "iPad build failed; full log: $build_log"
fi

app_path="$derived_data/Build/Products/Debug-iphoneos/OpenMates.app"
if [[ ! -d "$app_path" ]]; then
  app_path="$(find "$derived_data/Build/Products" -path '*/OpenMates.app' -type d | head -n 1)"
fi
[[ -d "$app_path" ]] || die "built app not found under $derived_data/Build/Products"

log "Installing $app_path on $device_id..."
xcrun devicectl device install app --device "$device_id" "$app_path"

if [[ "$launch_app" -eq 0 ]]; then
  log "Skipping launch (--no-launch)."
  exit 0
fi

log "Launching org.openmates.app on $device_id..."
xcrun devicectl device process launch --device "$device_id" org.openmates.app
log "Done."
