#!/usr/bin/env bash
# Arelle smoke test ONLY. It is NOT proof of HMRC filing acceptance.
# Run on a disposable Docker-enabled machine: bash scripts/evaluation/arelle_cli_spike.sh
set -euo pipefail
UPSTREAM_URL='https://github.com/Arelle/Arelle.git'
UPSTREAM_SHA='00d378b4dadc5ab3eb6e6b1d3ffb0e32eddbc92f'
for command in git docker; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "Missing: $command" >&2
    exit 2
  fi
done
if ! docker info >/dev/null 2>&1; then
  echo "Docker daemon unavailable" >&2
  exit 2
fi
workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT
git clone --quiet --no-checkout "$UPSTREAM_URL" "$workdir/src"
git -C "$workdir/src" checkout --quiet --detach "$UPSTREAM_SHA"
if [[ "$(git -C "$workdir/src" rev-parse HEAD)" != "$UPSTREAM_SHA" ]]; then
  echo 'Source SHA mismatch' >&2
  exit 1
fi
rm -rf "$workdir/src/.git"
cat > "$workdir/Dockerfile" <<'DOCKERFILE'
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /opt/arelle
COPY src/ /opt/arelle/
RUN python -m pip install --no-cache-dir /opt/arelle
USER 65534:65534
CMD ["arelleCmdLine", "--help"]
DOCKERFILE
image_tag="omnixat-spike-arelle:${UPSTREAM_SHA:0:12}"
# Build fetches dependencies; do not pass project .env/secrets into this build.
docker build --quiet --tag "$image_tag" "$workdir"
# Network-disabled runtime validates only the CLI / available features.
docker run --rm --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges --pids-limit 128 --memory 1g \
  --tmpfs /tmp:rw,noexec,nosuid,size=128m "$image_tag" \
  arelleCmdLine --help > "$workdir/cli-help.txt"
for flag in hmrc validate internetConnectivity validationExitCode; do
  if ! grep -qi "$flag" "$workdir/cli-help.txt"; then
    echo "Missing expected Arelle CLI flag: $flag" >&2
    exit 1
  fi
done
echo "Pinned Arelle CLI smoke test passed: $UPSTREAM_SHA"
echo "No financial document was validated. Obtain official taxonomy packages and run actual HMRC iXBRL tests before integration."
