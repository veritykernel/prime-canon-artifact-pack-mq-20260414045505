"""Create immutable receipts once; never silently replace prior evidence."""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from secure_projection_path import create_repository_file, repository_file_directory


def assert_new(repo: Path, path: Path) -> None:
    directory_fd, name = repository_file_directory(repo, path)
    try:
        try:
            os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            return
        raise SystemExit(f"immutable receipt already exists; create a successor generation: {path}")
    finally:
        os.close(directory_fd)


def write_new(repo: Path, path: Path, obj: dict) -> None:
    assert_new(repo, path)
    payload = yaml.safe_dump(obj, sort_keys=False)
    try:
        create_repository_file(repo, path, payload.encode("utf-8"))
    except FileExistsError as exc:
        raise SystemExit(f"immutable receipt already exists; create a successor generation: {path}") from exc
