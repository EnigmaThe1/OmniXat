#!/usr/bin/env bash
# Pinned, isolated CT600 unit-test evaluation. Never supply HMRC credentials or real tax data.
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
(cd "$repo_root/scripts/evaluation" && python3 -m unittest -q test_taxonomy_gate.py)
UPSTREAM_URL='https://github.com/benhuckvale/ct600-filing.git'
UPSTREAM_SHA='896794599c6cdb213a1122eeaa94b071d777229b'
for command in git docker; do
  if ! command -v "$command" >/dev/null 2>&1; then echo "Missing: $command" >&2; exit 2; fi
done
if ! docker info >/dev/null 2>&1; then echo 'Docker daemon unavailable.' >&2; exit 2; fi
workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT
git clone --quiet --no-checkout "$UPSTREAM_URL" "$workdir/src"
git -C "$workdir/src" checkout --quiet --detach "$UPSTREAM_SHA"
actual_sha="$(git -C "$workdir/src" rev-parse HEAD)"
if [[ "$actual_sha" != "$UPSTREAM_SHA" ]]; then
  echo "Upstream SHA mismatch: $actual_sha" >&2; exit 1
fi
rm -rf "$workdir/src/.git"
cp "$repo_root/scripts/evaluation/test_ct600_contract.py" "$workdir/src/tests/test_omnixat_contract.py"
cat > "$workdir/Dockerfile" <<'DOCKERFILE'
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /src
COPY src/ /src/
RUN python -m pip install --no-cache-dir -e . 'pytest>=8,<10' 'pytest-mock>=3,<4'
USER 65534:65534
CMD ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_build.py", "tests/test_irmark.py", "tests/test_ixbrl.py", "tests/test_omnixat_contract.py"]
DOCKERFILE
image_tag="omnixat-spike-ct600:${UPSTREAM_SHA:0:12}"
# Only upstream download/package installation need network. Use a disposable dev machine.
docker build --quiet --tag "$image_tag" "$workdir"
echo "Testing pinned upstream: $UPSTREAM_SHA"
docker run --rm --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges --pids-limit 128 --memory 512m \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m "$image_tag"
echo 'CT600 unit spike passed. This is NOT HMRC gateway acceptance.'
