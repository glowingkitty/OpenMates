#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/apple_local_macos.sh [options]

Build, ad-hoc sign, install, and optionally launch the macOS app for local
Personal Team testing. This intentionally avoids paid-team capabilities such as
Associated Domains, App Groups, and shared keychain groups.

Options:
  --derived-data PATH          Xcode derived data path
                              (default: .derivedData/local-macos-personal)
  --install-path PATH          Install destination
                              (default: /Applications/OpenMates.app)
  --no-install                 Build and sign only
  --no-launch                  Do not launch after install
  --no-spotlight-check         Skip Spotlight log/mdfind checks
  --spotlight-wait SECONDS     Seconds to wait after launch before checking
                              (default: 70)
  -h, --help                   Show this help

Environment:
  OPENMATES_MACOS_DERIVED_DATA
  OPENMATES_MACOS_INSTALL_PATH
  OPENMATES_SPOTLIGHT_WAIT_SECONDS
EOF
}

log() {
  printf '[openmates:macos] %s\n' "$*"
}

die() {
  printf '[openmates:macos] error: %s\n' "$*" >&2
  exit 1
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

derived_data="${OPENMATES_MACOS_DERIVED_DATA:-.derivedData/local-macos-personal}"
install_path="${OPENMATES_MACOS_INSTALL_PATH:-/Applications/OpenMates.app}"
install_app=1
launch_app=1
spotlight_check=1
spotlight_wait="${OPENMATES_SPOTLIGHT_WAIT_SECONDS:-70}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --derived-data)
      [[ $# -ge 2 ]] || die "--derived-data requires a path"
      derived_data="$2"
      shift 2
      ;;
    --install-path)
      [[ $# -ge 2 ]] || die "--install-path requires a path"
      install_path="$2"
      shift 2
      ;;
    --no-install)
      install_app=0
      launch_app=0
      spotlight_check=0
      shift
      ;;
    --no-launch)
      launch_app=0
      spotlight_check=0
      shift
      ;;
    --no-spotlight-check)
      spotlight_check=0
      shift
      ;;
    --spotlight-wait)
      [[ $# -ge 2 ]] || die "--spotlight-wait requires a number"
      spotlight_wait="$2"
      shift 2
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

[[ "$spotlight_wait" =~ ^[0-9]+$ ]] || die "--spotlight-wait must be a whole number"

app_path="$derived_data/Build/Products/Debug/OpenMates.app"
app_entitlements="apple/OpenMates/Resources/OpenMatesMacOSPersonalTeam.entitlements"
extension_entitlements="apple/OpenMatesShareExtensionMacOS/OpenMatesShareExtensionMacOSPersonalTeam.entitlements"

log "Building OpenMates_macOS without provisioning..."
xcodebuild \
  -project apple/OpenMates.xcodeproj \
  -scheme OpenMates_macOS \
  -configuration Debug \
  -derivedDataPath "$derived_data" \
  CODE_SIGNING_ALLOWED=NO \
  build

[[ -d "$app_path" ]] || die "built app not found at $app_path"

info_plist="$app_path/Contents/Info.plist"
if [[ -f "$info_plist" ]]; then
  # The production Info.plist points KeychainHelper at the shared production
  # access group. A local ad-hoc macOS build does not have that entitlement, so
  # remove the local build artifact's override and let KeychainHelper use the
  # app's default keychain access.
  /usr/libexec/PlistBuddy -c "Delete :OpenMatesKeychainAccessGroup" "$info_plist" 2>/dev/null || true
fi

while IFS= read -r appex_path; do
  log "Ad-hoc signing extension: $appex_path"
  codesign --force --sign - --entitlements "$extension_entitlements" "$appex_path"
done < <(find "$app_path/Contents/PlugIns" -maxdepth 1 -name '*.appex' -type d 2>/dev/null || true)

log "Ad-hoc signing app with local entitlements..."
codesign --force --sign - --entitlements "$app_entitlements" "$app_path"
codesign --verify --deep --strict "$app_path"

bundle_id=$(/usr/libexec/PlistBuddy -c "Print :CFBundleIdentifier" "$info_plist")
signature_summary=$(codesign -dv "$app_path" 2>&1 | sed -n 's/^Identifier=/Identifier=/p; s/^Signature=/Signature=/p; s/^TeamIdentifier=/TeamIdentifier=/p')
log "Built $bundle_id at $app_path"
printf '%s\n' "$signature_summary"

if [[ "$install_app" -eq 0 ]]; then
  log "Skipping install (--no-install)."
  exit 0
fi

log "Installing to $install_path..."
pkill -f "$install_path/Contents/MacOS/OpenMates" 2>/dev/null || true
rm -rf "$install_path"
ditto "$app_path" "$install_path"
touch "$install_path"

if [[ "$launch_app" -eq 0 ]]; then
  log "Skipping launch (--no-launch)."
  exit 0
fi

log "Launching $install_path..."
open "$install_path"

if [[ "$spotlight_check" -eq 0 ]]; then
  log "Skipping Spotlight checks (--no-spotlight-check)."
  exit 0
fi

log "Waiting ${spotlight_wait}s for sync/indexing before Spotlight checks..."
sleep "$spotlight_wait"

log "Recent OpenMates Spotlight logs:"
/usr/bin/log show \
  --predicate 'process == "OpenMates" AND (eventMessage CONTAINS "[Spotlight]" OR eventMessage CONTAINS "phase=spotlightIndex")' \
  --last 10m \
  --style compact || true

log "mdfind results containing OpenMates:"
mdfind 'kMDItemTextContent == "*OpenMates*"cd || kMDItemDisplayName == "*OpenMates*"cd' || true

log "Done."
