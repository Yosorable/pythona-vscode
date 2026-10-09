"""Workspace selection, persistence, and the small frontend command API."""

import errno
import hashlib
import json
from pathlib import Path
import re
import threading

from .filesystem import MAX_FILE_BYTES, RootedFiles, WorkspaceError, parts, revision
from .preferences import Preferences


class WorkspaceApp:
    def __init__(self, documents, state_path, *, language="en"):
        self.documents_path = Path(documents).resolve(strict=True)
        self.documents = RootedFiles(self.documents_path)
        self.state_path = Path(state_path)
        self.language = language
        self.closed = threading.Event()
        self.lock = threading.RLock()
        self.preferences = Preferences(self.state_path.parent)
        self.files = None
        self.workspace = None
        self.recent = []
        self._restore()

    def _restore(self):
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
            if not isinstance(state, dict):
                return
            recent = state.get("recent", [])
            if isinstance(recent, list):
                self.recent = [path for path in recent[:20] if isinstance(path, str)]
            path = state.get("workspace")
            if isinstance(path, str):
                try:
                    self.open_workspace(path, persist=False)
                except (OSError, WorkspaceError):
                    pass
        except (OSError, ValueError):
            pass

    def _persist(self, workspace, recent):
        state = {"workspace": workspace["path"] if workspace else None, "recent": recent}
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.state_path)

    def open_workspace(self, path, *, persist=True):
        segments = parts(path)
        if not segments or segments[0] == ".Trash":
            raise WorkspaceError("NoPermissions", "Choose a project folder inside Documents.")
        files = self.documents.subtree(path)
        workspace = {"id": hashlib.sha256(path.encode("utf-8")).hexdigest()[:24],
                     "name": segments[-1], "path": path}
        recent = [path] + [entry for entry in self.recent if entry != path][:19]
        try:
            if persist:
                self._persist(workspace, recent)
        except Exception:
            files.close()
            raise
        previous = self.files
        self.files, self.workspace, self.recent = files, workspace, recent
        if previous:
            previous.close()
        return self.workspace

    def _storage(self, action, payload):
        key = payload.get("key")
        if not isinstance(key, str) or re.fullmatch(r"[a-z0-9-]{1,80}", key) is None:
            raise WorkspaceError("InvalidRequest", "Invalid settings key.")
        file = self.state_path.parent / "workbench" / (key + ".json")
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not all(isinstance(k, str) and isinstance(v, str)
                                                    for k, v in data.items()):
                data = {}
        except (OSError, ValueError):
            data = {}
        if action == "storage.read":
            return data
        insert, delete = payload.get("insert", {}), payload.get("delete", [])
        if (not isinstance(insert, dict) or not isinstance(delete, list)
                or not all(isinstance(k, str) and isinstance(v, str) for k, v in insert.items())
                or not all(isinstance(k, str) for k in delete)):
            raise WorkspaceError("InvalidRequest", "Invalid settings update.")
        data.update(insert)
        for key in delete:
            data.pop(key, None)
        encoded = json.dumps(data, ensure_ascii=True)
        if len(encoded) > 4 * 1024 * 1024:
            raise WorkspaceError("Unavailable", "Workbench settings exceed the storage limit.")
        file.parent.mkdir(parents=True, exist_ok=True)
        temporary = file.with_suffix(".tmp")
        temporary.write_text(encoded, encoding="utf-8")
        temporary.replace(file)
        return None

    def _browse(self, path):
        segments = parts(path)
        if segments and segments[0] == ".Trash":
            raise WorkspaceError("NoPermissions", "The trash is not a workspace.")
        directories = [name for name, kind in self.documents.list(path)
                       if kind == 2 and not name.startswith(".")]
        return {"path": path, "directories": directories,
                "parent": "/".join(segments[:-1]) if segments else None,
                "canOpen": bool(segments)}

    @staticmethod
    def _boolean(payload, key, default=False):
        value = payload.get(key, default)
        if type(value) is not bool:
            raise WorkspaceError("InvalidRequest", f"{key} must be a boolean.")
        return value

    def _dispatch(self, action, payload):
        if action == "bootstrap":
            return {"workspace": self.workspace, "recent": self.recent, "language": self.language,
                    "maxFileBytes": MAX_FILE_BYTES, "preferences": self.preferences.snapshot()}
        if action == "preferences.update":
            self.preferences.update(payload)
            return None
        if action == "folders.list":
            return self._browse(payload.get("path", ""))
        if action == "folders.create":
            path = payload.get("path")
            segments = parts(path)
            if not segments or segments[0].startswith("."):
                raise WorkspaceError("NoPermissions", "Choose a visible project folder in Documents.")
            self.documents.mkdir(path)
            return None
        if action == "workspace.open":
            return self.open_workspace(payload.get("path"))
        if action == "workspace.close":
            self._persist(None, self.recent)
            if self.files:
                self.files.close()
            self.files = self.workspace = None
            return None
        if action in ("storage.read", "storage.update"):
            return self._storage(action, payload)
        if action == "host.close":
            self.closed.set()
            return None
        if action.startswith("fs."):
            if not self.workspace or payload.get("workspace") != self.workspace["id"]:
                raise WorkspaceError("Unavailable", "This workspace is no longer open.")
            path = payload.get("path")
            parts(path)
            if action == "fs.stat":
                return self.files.stat(path)
            if action == "fs.list":
                return self.files.list(path)
            if action == "fs.read":
                data = self.files.read(path)
                return {"data": data, "revision": revision(data)}
            if action == "fs.write":
                data = payload.get("data")
                if not isinstance(data, bytes) or len(data) > MAX_FILE_BYTES:
                    raise WorkspaceError("InvalidRequest", "Invalid file data.")
                expected = payload.get("expected")
                if expected is not None and (not isinstance(expected, str) or len(expected) != 64):
                    raise WorkspaceError("InvalidRequest", "Invalid file revision.")
                return {"revision": self.files.write(
                    path, data, create=self._boolean(payload, "create"),
                    overwrite=self._boolean(payload, "overwrite"), expected=expected)}
            if action == "fs.mkdir":
                return self.files.mkdir(path)
            if action == "fs.rename":
                return self.files.rename(path, payload.get("target"),
                                         overwrite=self._boolean(payload, "overwrite"))
            if action == "fs.delete":
                return self.files.delete(path, recursive=self._boolean(payload, "recursive"))
        raise WorkspaceError("InvalidRequest", "Unknown command.")

    def dispatch(self, action, payload=None):
        if not isinstance(action, str) or not isinstance(payload if payload is not None else {}, dict):
            raise WorkspaceError("InvalidRequest", "Invalid request.")
        with self.lock:
            if self.closed.is_set():
                raise WorkspaceError("Unavailable", "The session has ended.")
            try:
                return self._dispatch(action, payload or {})
            except OSError as error:
                code = {
                    errno.ENOENT: "FileNotFound", errno.EEXIST: "FileExists",
                    errno.ENOTDIR: "FileNotADirectory", errno.EISDIR: "FileIsADirectory",
                    errno.EACCES: "NoPermissions", errno.EPERM: "NoPermissions",
                    errno.ELOOP: "NoPermissions", errno.ENOTEMPTY: "NoPermissions",
                }.get(error.errno, "Unavailable")
                raise WorkspaceError(code, error.strerror or "The file operation failed.") from None

    def close(self):
        self.closed.set()
        with self.lock:
            if self.files:
                self.files.close()
                self.files = None
            self.documents.close()
