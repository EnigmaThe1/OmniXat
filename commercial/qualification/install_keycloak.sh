#!/usr/bin/env bash
# Test-only, pinned official release. Never downloads or starts on application import.
set -euo pipefail
destination=${1:?Supply a new disposable installation directory}
if test -e "$destination"; then
  printf '%s\n' 'Refusing to replace an existing Keycloak installation' >&2
  exit 1
fi
scratch=$(mktemp -d)
trap 'rm -rf -- "$scratch"' EXIT
curl --fail --location --proto '=https' --tlsv1.2 --retry 2 --max-time 180 \
  https://github.com/keycloak/keycloak/releases/download/26.8.2/keycloak-26.8.2.tar.gz \
  --output "$scratch/keycloak.tar.gz"
printf '%s  %s\n' dd124787283918bc597628887168333465ee2a811a389e0003569e52be7e487f \
  "$scratch/keycloak.tar.gz" | sha256sum --check --status
tar -xzf "$scratch/keycloak.tar.gz" -C "$scratch"
mkdir -p -- "$(dirname -- "$destination")"
mv --no-clobber -- "$scratch/keycloak-26.8.2" "$destination"
test -x "$destination/bin/kc.sh"
