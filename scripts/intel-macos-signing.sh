#!/usr/bin/env bash
# Prepare the Intel runner's temporary Developer ID keychain and notary key.
# With no credentials, keep the existing ad-hoc release path. A partial set,
# invalid credentials, or a signed build requested without them fails early.
set -euo pipefail

signing_dir="${RUNNER_TEMP:?}/zeron-intel-signing"
keychain="$signing_dir/release.keychain-db"

read_keychains() {
  original_keychains=()
  while IFS= read -r item; do
    [ -n "$item" ] && original_keychains+=("$item")
  done <"$signing_dir/keychains.txt"
}

cleanup() {
  [ -d "$signing_dir" ] || return 0
  if [ -f "$signing_dir/keychains.txt" ]; then
    read_keychains
    security list-keychains -d user -s "${original_keychains[@]}"
  fi
  if [ -f "$keychain" ]; then
    security delete-keychain "$keychain"
  fi
  rm -f "$signing_dir/cert.p12" "$signing_dir/notary.p8" "$signing_dir/keychains.txt"
  rmdir "$signing_dir"
}

case "${1:-prepare}" in
  cleanup) cleanup; exit 0 ;;
  prepare) ;;
  *) echo "usage: $0 [prepare|cleanup]" >&2; exit 2 ;;
esac

required=(MACOS_CERT_P12 MACOS_CERT_PASSWORD AC_API_KEY_P8 AC_API_KEY_ID AC_API_ISSUER_ID)
present=0
missing=()
for name in "${required[@]}"; do
  if [ -n "${!name:-}" ]; then
    present=$((present + 1))
  else
    missing+=("$name")
  fi
done

if [ "$present" -eq 0 ] && [ "${REQUIRE_SIGNING:-false}" != true ]; then
  echo 'SIGNING_ENABLED=false' >>"${GITHUB_ENV:?}"
  echo 'Apple signing credentials are not configured; this build will be ad-hoc signed.'
  exit 0
fi
if [ "${#missing[@]}" -ne 0 ]; then
  printf '::error::Apple signing requires all five apple-release secrets. Missing: %s\n' "${missing[*]}" >&2
  exit 1
fi

umask 077
mkdir -m 700 "$signing_dir"
security list-keychains -d user | sed 's/^[[:space:]]*"//; s/"[[:space:]]*$//' >"$signing_dir/keychains.txt"
read_keychains
pass="$(openssl rand -hex 32)"
printf '::add-mask::%s\n' "$pass"
security create-keychain -p "$pass" "$keychain"
security set-keychain-settings -lut 21600 "$keychain"
security unlock-keychain -p "$pass" "$keychain"
printf '%s' "$MACOS_CERT_P12" | base64 -d >"$signing_dir/cert.p12"
security import "$signing_dir/cert.p12" -k "$keychain" -P "$MACOS_CERT_PASSWORD" -T /usr/bin/codesign
rm -f "$signing_dir/cert.p12"
security set-key-partition-list -S apple-tool:,apple: -s -k "$pass" "$keychain" >/dev/null
security list-keychains -d user -s "$keychain" "${original_keychains[@]}"
identity="$(security find-identity -v -p codesigning "$keychain" \
  | sed -nE 's/.* ([0-9A-Fa-f]{40}) "Developer ID Application:.*"/\1/p' | head -1)"
if [ -z "$identity" ]; then
  echo '::error::The certificate must contain a valid Developer ID Application identity and its private key.' >&2
  exit 1
fi
printf '%s' "$AC_API_KEY_P8" >"$signing_dir/notary.p8"
openssl pkey -in "$signing_dir/notary.p8" -noout
# Authenticate before compiling; a successful submission is still required
# by package-zgx-macos.sh for both the app and the DMG.
xcrun notarytool history --key "$signing_dir/notary.p8" \
  --key-id "$AC_API_KEY_ID" --issuer "$AC_API_ISSUER_ID" --output-format json >/dev/null
{
  echo 'SIGNING_ENABLED=true'
  printf 'CODESIGN_IDENTITY=%s\n' "$identity"
  printf 'NOTARY_KEY_PATH=%s\n' "$signing_dir/notary.p8"
  printf 'NOTARY_KEY_ID=%s\n' "$AC_API_KEY_ID"
  printf 'NOTARY_ISSUER_ID=%s\n' "$AC_API_ISSUER_ID"
} >>"${GITHUB_ENV:?}"
