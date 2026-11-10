#!/usr/bin/env bash
# Explicit test-only download of the official Linux amd64 release, not deployment.
set -euo pipefail
destination=${1:?Supply a new disposable binary path}
test "$(uname -s)" = Linux && test "$(uname -m)" = x86_64
if test -e "$destination"; then
  printf '%s\n' 'Refusing to replace an existing OAuth2 Proxy binary' >&2
  exit 1
fi
scratch=$(mktemp -d)
trap 'rm -rf -- "$scratch"' EXIT
curl --fail --location --proto '=https' --tlsv1.2 --retry 2 --max-time 180 \
  https://github.com/oauth2-proxy/oauth2-proxy/releases/download/v7.15.6/oauth2-proxy-v7.15.6.linux-amd64.tar.gz \
  --output "$scratch/proxy.tar.gz"
printf '%s  %s\n' 91b3e86d9c2de679a516e6696704e3fd1acf67e8b8f7be77b618f086f72fb1f0 \
  "$scratch/proxy.tar.gz" | sha256sum --check --status
tar -xzf "$scratch/proxy.tar.gz" -C "$scratch"
mkdir -p -- "$(dirname -- "$destination")"
mv --no-clobber -- "$scratch/oauth2-proxy-v7.15.6.linux-amd64/oauth2-proxy" "$destination"
test -x "$destination"
