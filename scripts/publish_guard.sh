#!/usr/bin/env bash
set -euo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export PYTHONDONTWRITEBYTECODE=1
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"
TRUSTED_PYTHON="${PRIME_CANON_TRUSTED_PYTHON:-}"
# The interpreter and its packages are installed by the operator outside this
# checkout. No candidate .venv file or repository bootstrap code is executed.
/usr/bin/python3 -I -c '
import os, pathlib, stat, sys
repo = pathlib.Path(sys.argv[1]).resolve(strict=True)
path = pathlib.Path(sys.argv[2])
if not path.is_absolute() or ".." in path.parts or path.is_relative_to(repo):
    raise SystemExit("trusted Python must be an absolute path outside the repository")
fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
try:
    for part in path.parts[1:-1]:
        info = os.stat(part, dir_fd=fd, follow_symlinks=False)
        if not stat.S_ISDIR(info.st_mode):
            raise SystemExit("trusted Python has a symlink or non-directory ancestor")
        if info.st_mode & 0o022 and not (info.st_uid == 0 and info.st_mode & stat.S_ISVTX):
            raise SystemExit("trusted Python has a writable ancestor")
        next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
        os.close(fd)
        fd = next_fd
    info = os.stat(path.name, dir_fd=fd, follow_symlinks=False)
    if (not stat.S_ISREG(info.st_mode) or info.st_uid not in (0, os.getuid())
            or info.st_mode & 0o022 or not info.st_mode & stat.S_IXUSR):
        raise SystemExit("trusted Python must be an operator-owned regular executable")
finally:
    os.close(fd)
' "$REPO" "$TRUSTED_PYTHON"
unset PYTHONPATH PYTHONHOME PYTHONUSERBASE VIRTUAL_ENV
export PYTHONNOUSERSITE=1
"$TRUSTED_PYTHON" -I -c 'import yaml, jsonschema'
run_reviewed_script() {
  local script="$1"
  shift
  "$TRUSTED_PYTHON" -I -c '
import pathlib, runpy, sys
repo = pathlib.Path(sys.argv[1])
script = sys.argv[2]
if script not in ("scripts/check_export_prep.py", "scripts/publish_verified_subject.py"):
    raise SystemExit("unreviewed guarded script")
sys.path.append(str(repo / "scripts"))
sys.argv = [str(repo / script), *sys.argv[3:]]
runpy.run_path(str(repo / script), run_name="__main__")
' "$REPO" "$script" "$@"
}
SUBJECT_SLUG="${SUBJECT_SLUG:-subject-0001}"
if [ "${1:-}" = "--" ]; then
  shift
fi
if [ "$#" -eq 0 ]; then
  echo "usage: SUBJECT_SLUG=subject-0001 ./scripts/publish_rendered_subject.sh subject-0001" >&2
  exit 64
fi
# The old arbitrary command mode allowed a green receipt to precede a copy
# that reopened different bytes. Only the publisher that hashes and copies
# one open snapshot is an admitted effect. /usr/bin/true is a dry-run check.
if ! { [ "$#" -eq 4 ] && [ "$1" = python3 ] && [ "$2" = scripts/publish_verified_subject.py ] && [ "$3" = "$REPO" ] && [ "$4" = "$SUBJECT_SLUG" ]; } \
   && ! { [ "$#" -eq 1 ] && [ "$1" = /usr/bin/true ]; }; then
  echo "publish guard accepts only the verified subject publisher" >&2
  exit 64
fi
run_reviewed_script scripts/check_export_prep.py "$REPO" "$SUBJECT_SLUG"
if [ "$#" -eq 1 ]; then
  exec /usr/bin/true
fi
run_reviewed_script scripts/publish_verified_subject.py "$REPO" "$SUBJECT_SLUG"
