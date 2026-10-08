"""Descriptor-relative filesystem access for one explicitly opened workspace."""

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import stat
import uuid


MAX_FILE_BYTES = 16 * 1024 * 1024


class WorkspaceError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def parts(path):
    if not isinstance(path, str) or "\0" in path or path.startswith("/"):
        raise WorkspaceError("NoPermissions", "Use a relative workspace path.")
    if path == "":
        return []
    segments = path.split("/")
    if any(segment in ("", ".", "..") for segment in segments):
        raise WorkspaceError("NoPermissions", "The path must stay inside the workspace.")
    return segments


def file_stat(info):
    kind = 2 if stat.S_ISDIR(info.st_mode) else 1
    if stat.S_ISLNK(info.st_mode):
        kind = 64
    return {
        "type": kind,
        "ctime": info.st_ctime_ns // 1_000_000,
        "mtime": info.st_mtime_ns // 1_000_000,
        "size": info.st_size,
    }


def revision(data):
    return hashlib.sha256(data).hexdigest()


class RootedFiles:
    """Keep an open directory descriptor; never follow workspace symlinks."""

    def __init__(self, root=None, *, descriptor=None):
        self.fd = descriptor if descriptor is not None else os.open(
            Path(root), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    @contextmanager
    def directory(self, segments):
        if self.fd is None:
            raise WorkspaceError("Unavailable", "The workspace has closed.")
        descriptor = os.dup(self.fd)
        try:
            for segment in segments:
                child = os.open(segment, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                dir_fd=descriptor)
                os.close(descriptor)
                descriptor = child
            yield descriptor
        finally:
            os.close(descriptor)

    @contextmanager
    def parent(self, path):
        segments = parts(path)
        if not segments:
            raise WorkspaceError("NoPermissions", "The workspace root cannot be changed.")
        with self.directory(segments[:-1]) as descriptor:
            yield descriptor, segments[-1]

    def subtree(self, path):
        with self.directory(parts(path)) as descriptor:
            return RootedFiles(descriptor=os.dup(descriptor))

    def stat(self, path):
        if not parts(path):
            return file_stat(os.fstat(self.fd))
        with self.parent(path) as (descriptor, name):
            return file_stat(os.stat(name, dir_fd=descriptor, follow_symlinks=False))

    def list(self, path):
        with self.directory(parts(path)) as descriptor:
            result = []
            for name in os.listdir(descriptor):
                try:
                    info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                except FileNotFoundError:
                    continue
                result.append([name, file_stat(info)["type"]])
            return sorted(result, key=lambda item: (item[1] != 2, item[0].casefold()))

    @staticmethod
    def _read(descriptor, name):
        handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
        with os.fdopen(handle, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise WorkspaceError("FileIsADirectory" if stat.S_ISDIR(info.st_mode)
                                     else "NoPermissions", "Only regular files can be edited.")
            if info.st_size > MAX_FILE_BYTES:
                raise WorkspaceError("Unavailable", "Files larger than 16 MiB are not supported.")
            data = stream.read(MAX_FILE_BYTES + 1)
            if len(data) > MAX_FILE_BYTES:
                raise WorkspaceError("Unavailable", "Files larger than 16 MiB are not supported.")
            return data

    def read(self, path):
        with self.parent(path) as (descriptor, name):
            return self._read(descriptor, name)

    def write(self, path, data, *, create, overwrite, expected=None):
        if len(data) > MAX_FILE_BYTES:
            raise WorkspaceError("Unavailable", "Files larger than 16 MiB are not supported.")
        with self.parent(path) as (descriptor, name):
            try:
                existing = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            except FileNotFoundError:
                existing = None
            if existing is not None:
                if not stat.S_ISREG(existing.st_mode):
                    raise WorkspaceError("NoPermissions", "Only regular files can be overwritten.")
                if not overwrite:
                    raise FileExistsError(name)
                if expected is not None and revision(self._read(descriptor, name)) != expected:
                    raise WorkspaceError("FileWriteLocked", "The file changed on disk. Reopen it before saving.")
            elif not create:
                raise FileNotFoundError(name)
            elif expected is not None:
                raise WorkspaceError("FileWriteLocked", "The file was removed on disk. Save it under a new name.")

            temporary = f".pythona-vscode-{uuid.uuid4().hex}.tmp"
            handle = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                             0o600, dir_fd=descriptor)
            try:
                with os.fdopen(handle, "wb") as stream:
                    stream.write(data)
                    if existing is not None:
                        os.fchmod(stream.fileno(), stat.S_IMODE(existing.st_mode))
                    stream.flush()
                    os.fsync(stream.fileno())
                if existing is None:
                    # A concurrently created file must not be replaced by a new-file save.
                    os.link(temporary, name, src_dir_fd=descriptor, dst_dir_fd=descriptor,
                            follow_symlinks=False)
                else:
                    os.replace(temporary, name, src_dir_fd=descriptor, dst_dir_fd=descriptor)
            finally:
                try:
                    os.unlink(temporary, dir_fd=descriptor)
                except FileNotFoundError:
                    pass
        return revision(data)

    def mkdir(self, path):
        with self.parent(path) as (descriptor, name):
            os.mkdir(name, dir_fd=descriptor)

    def rename(self, source, target, *, overwrite):
        with self.parent(source) as (source_fd, source_name):
            with self.parent(target) as (target_fd, target_name):
                if not overwrite:
                    try:
                        os.stat(target_name, dir_fd=target_fd, follow_symlinks=False)
                    except FileNotFoundError:
                        pass
                    else:
                        raise FileExistsError(target_name)
                os.rename(source_name, target_name, src_dir_fd=source_fd, dst_dir_fd=target_fd)

    @classmethod
    def _remove(cls, descriptor, name, recursive):
        info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
        if stat.S_ISDIR(info.st_mode):
            if recursive:
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                dir_fd=descriptor)
                try:
                    for entry in os.listdir(child):
                        cls._remove(child, entry, True)
                finally:
                    os.close(child)
            os.rmdir(name, dir_fd=descriptor)
        else:
            os.unlink(name, dir_fd=descriptor)

    def delete(self, path, *, recursive):
        with self.parent(path) as (descriptor, name):
            self._remove(descriptor, name, recursive)
