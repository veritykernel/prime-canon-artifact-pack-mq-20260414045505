#!/usr/bin/env bash
set -euo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export PYTHONDONTWRITEBYTECODE=1
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"
rm -rf scripts/__pycache__
SUBJECT_SLUG="${1:-subject-0001}"
SUBJECT_SLUG="$SUBJECT_SLUG" ./scripts/publish_guard.sh -- /usr/bin/true
unset PYTHONPATH PYTHONHOME PYTHONUSERBASE VIRTUAL_ENV
export PYTHONNOUSERSITE=1
"$PRIME_CANON_TRUSTED_PYTHON" scripts/validate_pack.py .
git diff --exit-code -- control schemas
rm -rf scripts/__pycache__
git add scripts/publish_guard.sh scripts/publish_guard_commit.sh
git commit -m "projection: add fail-closed publish guard for $SUBJECT_SLUG"
