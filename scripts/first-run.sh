#!/usr/bin/env bash
# Run with: bash scripts/first-run.sh
set -euo pipefail
cd "$(dirname "$0")/.."

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required. Install Docker Engine and Docker Compose plugin first." >&2
  exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose plugin is required." >&2
  exit 1
fi

if [[ ! -f .env ]]; then
  umask 077
  python3 - <<'PY'
from pathlib import Path
from secrets import token_hex, token_urlsafe
path = Path(".env")
if path.exists():
    raise SystemExit(".env already exists; refusing to overwrite")
path.write_text(
    "POSTGRES_PASSWORD=" + token_hex(32) + "\n" +
    "OMNIXAT_OWNER_PASSWORD=" + token_urlsafe(24) + "\n" +
    "OMNIXAT_SESSION_SECRET=" + token_hex(32) + "\n" +
    "COMPANIES_HOUSE_API_KEY=\n" +
    "OMNIXAT_PORT=3000\n"
)
path.chmod(0o600)
print("Generated a new, untracked .env with independent random secrets.")
PY
else
  echo "Existing .env preserved."
fi
chmod 600 .env
docker compose up --build -d
docker compose ps
echo ""
echo "UI: http://127.0.0.1:3000"
echo "Owner password is saved locally as OMNIXAT_OWNER_PASSWORD in .env."
echo "Optional: add COMPANIES_HOUSE_API_KEY to .env and restart API for official lookup."
echo "Keep the app localhost-only. Do not store real financial records in this alpha."
