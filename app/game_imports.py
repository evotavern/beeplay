"""Install independently built static games into Beeplay's artifact store."""

from __future__ import annotations

import shutil
import uuid
import zipfile
from io import BytesIO
from pathlib import Path, PurePosixPath


MAX_ARCHIVE_BYTES = 25 * 1024 * 1024
MAX_FILES = 500
MAX_UNPACKED_BYTES = 100 * 1024 * 1024


class GameImportError(ValueError):
    pass


def _checked_paths(entries: list[tuple[str, bytes]]) -> tuple[list[tuple[PurePosixPath, bytes]], bool]:
    if not entries:
        raise GameImportError("请选择一个游戏文件夹或 zip 包")
    if len(entries) > MAX_FILES:
        raise GameImportError("游戏文件过多")
    if sum(len(contents) for _, contents in entries) > MAX_UNPACKED_BYTES:
        raise GameImportError("游戏解包后超过 100 MB")

    paths: list[tuple[PurePosixPath, bytes]] = []
    for name, contents in entries:
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise GameImportError("游戏包含不安全的文件路径")
        paths.append((path, contents))

    names = {path for path, _ in paths}
    roots = {path.parts[0] for path, _ in paths}
    wrapped = len(roots) == 1 and PurePosixPath(next(iter(roots)), "index.html") in names
    if PurePosixPath("index.html") not in names and not wrapped:
        raise GameImportError("游戏需要包含 index.html")
    return paths, wrapped


def _install(entries: list[tuple[str, bytes]], games_dir: Path) -> str:
    paths, wrapped = _checked_paths(entries)
    artifact = uuid.uuid4().hex
    target = games_dir / artifact
    target.mkdir(parents=True)
    try:
        for source, contents in paths:
            relative = PurePosixPath(*source.parts[1:]) if wrapped else source
            output = target.joinpath(*relative.parts)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(contents)
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        raise
    return artifact


def install_zip(bundle: bytes, games_dir: Path) -> str:
    if not bundle:
        raise GameImportError("请选择一个 zip 游戏包")
    if len(bundle) > MAX_ARCHIVE_BYTES:
        raise GameImportError("zip 游戏包超过 25 MB")
    try:
        with zipfile.ZipFile(BytesIO(bundle)) as archive:
            members = [member for member in archive.infolist() if not member.is_dir()]
            if len(members) > MAX_FILES:
                raise GameImportError("游戏文件过多")
            if sum(member.file_size for member in members) > MAX_UNPACKED_BYTES:
                raise GameImportError("游戏解包后超过 100 MB")
            entries: list[tuple[str, bytes]] = []
            for member in members:
                if (member.external_attr >> 16) & 0o170000 == 0o120000:
                    raise GameImportError("游戏不能包含符号链接")
                entries.append((member.filename, archive.read(member)))
    except zipfile.BadZipFile as error:
        raise GameImportError("只能上传 zip 格式的游戏包") from error
    return _install(entries, games_dir)


def install_folder(entries: list[tuple[str, bytes]], games_dir: Path) -> str:
    return _install(entries, games_dir)
