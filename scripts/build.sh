#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo 'Usage: bash scripts/build.sh api|boot|styling|tasker|x11 (Release only)' >&2
    exit 1
fi
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"
addon="$1"
case "$addon" in api|boot|styling|tasker|x11) ;; *) echo 'Invalid addon' >&2; exit 1 ;; esac

export MDTERM_ADDON_GRADLE="$project_dir/gradle/mdterm-addon.gradle"
: "${MDTERM_RELEASE_KEYSTORE_BASE64:?Configure the same signing secrets as MDTerm Release APK}"
export MDTERM_ADDON_STORE_PASSWORD="${MDTERM_RELEASE_STORE_PASSWORD:?Missing release store password}"
export MDTERM_ADDON_KEY_ALIAS="${MDTERM_RELEASE_KEY_ALIAS:?Missing release alias}"
export MDTERM_ADDON_KEY_PASSWORD="${MDTERM_RELEASE_KEY_PASSWORD:?Missing release key password}"

mkdir -p "$HOME/tmp"
umask 077
signing_dir="$(mktemp -d "$HOME/tmp/mdtermaddon-signing.XXXXXXXX")"
trap 'rm -rf -- "$signing_dir"' EXIT
export MDTERM_ADDON_STORE_FILE="$signing_dir/key.p12"
certificate_sha256="$(python3 scripts/signing.py)"

python3 scripts/prepare.py "$addon" --source upstream
gradle_tasks=(:app:assembleRelease)
if [[ "$addon" == x11 ]]; then
    gradle_tasks=(:lorie-app:assembleSharedUidRelease :shell-loader:buildCompanionPackage)
fi
(
    cd upstream
    bash ./gradlew --no-daemon --console=plain "${gradle_tasks[@]}"
)
python3 scripts/verify_apk.py "$addon" \
    --source upstream --output dist --certificate-sha256 "$certificate_sha256"
