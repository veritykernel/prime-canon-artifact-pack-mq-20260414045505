"""Create immutable receipts once; never silently replace prior evidence."""

from __future__ import annotations

import os
from pathlib import Path

import yaml


def assert_new(repo: Path, path: Path) -> None:
    repo = repo.resolve(strict=True)
    if path.parent.is_symlink() or not path.parent.resolve(strict=True).is_relative_to(repo):
        raise SystemExit(f"immutable receipt parent escapes repository: {path}")
    if path.exists() or path.is_symlink():
        raise SystemExit(f"immutable receipt already exists; create a successor generation: {path}")


def write_new(repo: Path, path: Path, obj: dict) -> None:
    assert_new(repo, path)
    payload = yaml.safe_dump(obj, sort_keys=False)
    directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
    try:
        try:
            fd = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                         0o644, dir_fd=directory_fd)
        except FileExistsError as exc:
            raise SystemExit(f"immutable receipt already exists; create a successor generation: {path}") from exc
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(directory_fd)
