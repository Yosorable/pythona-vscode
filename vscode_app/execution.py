"""Run one workspace script in a Python thread, with scoped text I/O."""

from collections import deque
import codecs
from contextlib import suppress
import importlib
from importlib.abc import MetaPathFinder
from importlib.machinery import PathFinder, SourceFileLoader
import io
import os
from pathlib import Path
import shlex
import sys
import threading
import traceback
from types import ModuleType
import uuid

from .filesystem import RootedFiles, WorkspaceError, parts


OUTPUT_LIMIT = 1024 * 1024
POLL_LIMIT = 64 * 1024
_execution_lock = threading.Lock()
_OWNER = "_pythona_vscode_run"


def _under(path, root):
    return isinstance(path, str) and (path == root or path.startswith(root + os.sep))


class _SourceLoader(SourceFileLoader):
    """Read project source without following symlinks or reusing stale bytecode."""

    def __init__(self, name, path, root, files):
        super().__init__(name, path)
        self.root, self.files = root, files

    def get_code(self, fullname):
        source = self.files.read(self.path[len(self.root) + 1:])
        return self.source_to_code(source, self.path)


class _ProjectImports(MetaPathFinder):
    def __init__(self, root, files):
        self.root, self.files = root, files

    def find_spec(self, fullname, path=None, target=None):
        spec = PathFinder.find_spec(fullname, path)
        if (spec and _under(spec.origin, self.root)
                and isinstance(spec.loader, SourceFileLoader)):
            spec.loader = _SourceLoader(fullname, spec.origin, self.root, self.files)
            return spec
        return None


class _Output(io.RawIOBase):
    def __init__(self, run):
        self.run = run
        self.decoder = codecs.getincrementaldecoder("utf-8")("replace")

    def writable(self):
        return True

    def write(self, data):
        if self.closed:
            raise ValueError("I/O operation on closed file")
        raw = bytes(data)
        with self.run.condition:
            self.run.write(self.decoder.decode(raw))
        return len(raw)

    def flush(self):
        pass

    def close(self):
        if not self.closed:
            with self.run.condition:
                self.run.write(self.decoder.decode(b"", final=True))
        super().close()


class _Input(io.RawIOBase):
    def __init__(self, run):
        self.run = run
        self.pending = bytearray()
        self.eof = False

    def readable(self):
        return True

    def readinto(self, buffer):
        if self.closed:
            raise ValueError("I/O operation on closed file")
        if not len(buffer):
            return 0
        run = self.run
        with run.condition:
            while not self.pending and not self.eof and not run.cancelled:
                if run.input_request is None:
                    run.next_input += 1
                    run.input_request = run.next_input
                run.condition.wait()
            run.input_request = None
            if run.cancelled:
                if run.cancellation:
                    run.cancellation.delivered.add(threading.current_thread())
                raise KeyboardInterrupt
            count = min(len(buffer), len(self.pending))
            buffer[:count] = self.pending[:count]
            del self.pending[:count]
            return count


class _ThreadStream:
    """Keep host threads on their existing streams while a script is running."""

    def __init__(self, run, local, original):
        self.run, self.local, self.original = run, local, original

    def __getattr__(self, name):
        stream = self.local if self.run.owns_thread() else self.original
        return getattr(stream, name)

    def __iter__(self):
        return self

    def __next__(self):
        line = self.readline()
        if not line:
            raise StopIteration
        return line


class _Cancellation:
    """Request KeyboardInterrupt at Python execution boundaries, never in imports.

    CPython monitoring has no execution overhead until Stop is requested. The
    older desktop-preview fallback traces only threads belonging to this run.
    Neither mechanism can interrupt a native call before it returns to Python.
    """

    def __init__(self, run):
        self.run = run
        self.tool = None
        self.delivered = set()
        self.monitoring = getattr(sys, "monitoring", None)
        if self.monitoring:
            for identifier in (3, 4, 0, 1, 2, 5):
                try:
                    self.monitoring.use_tool_id(identifier, "Pythona VSCode")
                except ValueError:
                    continue
                self.tool = identifier
                self.events = (self.monitoring.events.LINE, self.monitoring.events.JUMP,
                               self.monitoring.events.PY_START, self.monitoring.events.PY_RESUME)
                for event in self.events:
                    self.monitoring.register_callback(identifier, event, self.check)
                break

    def check(self, *_args, frame=None):
        run = self.run
        if not run.cancelled or not run.owns_thread():
            return
        thread = threading.current_thread()
        if thread in self.delivered or (thread is run.thread and not run.executing):
            return
        frame = frame or sys._getframe(1)
        if frame.f_code.co_filename == __file__:
            return
        while frame is not None and frame.f_code is not Run._execute.__code__:
            filename = frame.f_code.co_filename
            # Do not inject into our stream locks, importlib, or an import's
            # module body. An interruption there can leave shared modules broken.
            if (filename == __file__ or filename.startswith("<frozen importlib")
                    or frame.f_globals.get("__name__", "").startswith("importlib.")):
                return
            frame = frame.f_back
        self.delivered.add(thread)
        raise KeyboardInterrupt

    def trace(self, frame, event, arg):
        if self.run.owns_thread():
            self.check(frame=frame)
            return self.trace
        return None

    def request(self):
        if self.tool is not None:
            events = 0
            for event in self.events:
                events |= event
            self.monitoring.set_events(self.tool, events)

    def close(self):
        if self.tool is not None:
            self.monitoring.set_events(self.tool, 0)
            for event in self.events:
                self.monitoring.register_callback(self.tool, event, None)
            self.monitoring.free_tool_id(self.tool)
            self.tool = None


class Run:
    def __init__(self, identity, workspace, path, root, files, source, arguments, cwd):
        self.id, self.workspace, self.path = identity, workspace, path
        self.root, self.files, self.source = str(root), files, source
        self.arguments, self.cwd = arguments, cwd
        self.condition = threading.Condition(threading.RLock())
        self.done = threading.Event()
        self.cancelled = False
        self.executing = False
        self.cancellation = None
        self.exit_code = None
        self.output = deque()
        self.output_start = self.output_end = 0
        self.input_request = None
        self.next_input = 0
        self.input = _Input(self)
        self.children = []
        self.thread = threading.Thread(target=self._execute, name="PythonaVSCodeRun", daemon=True)
        setattr(self.thread, _OWNER, self)

    def owns_thread(self):
        return getattr(threading.current_thread(), _OWNER, None) is self

    def write(self, text):
        with self.condition:
            for offset in range(0, len(text), 8192):
                chunk = text[offset:offset + 8192]
                if self.output and len(self.output[-1]) + len(chunk) <= 8192:
                    self.output[-1] += chunk
                else:
                    self.output.append(chunk)
                self.output_end += len(chunk)
                while self.output_end - self.output_start > OUTPUT_LIMIT:
                    self.output_start += len(self.output.popleft())

    def snapshot(self, after=0):
        if type(after) is not int or after < 0:
            raise WorkspaceError("InvalidRequest", "Invalid output position.")
        with self.condition:
            start = max(self.output_start, min(after, self.output_end))
            text = "".join(self.output)[start - self.output_start:start - self.output_start + POLL_LIMIT]
            state = ("finished" if self.done.is_set() else "stopping" if self.cancelled
                     else "input" if self.input_request is not None else "running")
            return {"id": self.id, "path": self.path, "state": state,
                    "exitCode": self.exit_code, "input": self.input_request,
                    "output": text, "next": start + len(text),
                    "more": start + len(text) < self.output_end, "truncated": after < self.output_start}

    def send_input(self, request, text, eof):
        if (type(request) is not int or not isinstance(text, str)
                or len(text) > POLL_LIMIT or type(eof) is not bool):
            raise WorkspaceError("InvalidRequest", "Invalid Python input.")
        with self.condition:
            if (self.done.is_set() or self.cancelled or self.input.eof
                    or request != self.input_request):
                raise WorkspaceError("Unavailable", "This input request has ended.")
            self.input.pending.extend((text if eof else text + "\n").encode("utf-8"))
            self.input.eof = eof
            self.input_request = None
            if text or not eof:
                self.write(text + "\n")
            self.condition.notify_all()

    def stop(self):
        with self.condition:
            if not self.done.is_set():
                self.cancelled = True
                self.condition.notify_all()
                if self.cancellation:
                    self.cancellation.delivered.clear()
                    self.cancellation.request()

    def _project_module(self, name, module):
        if name == "__main__" or name == "vscode_app" or name.startswith("vscode_app."):
            return False
        namespace = vars(module) if isinstance(module, ModuleType) else {}
        return _under(namespace.get("__file__"), self.root) or any(
            _under(path, self.root) for path in (namespace.get("__path__") or ()))

    def _execute(self):
        old_streams = sys.stdin, sys.stdout, sys.stderr
        old_argv, old_path, old_meta = sys.argv, sys.path, sys.meta_path
        old_main = sys.modules.get("__main__")
        old_start = threading.Thread.start
        old_trace, old_thread_trace = sys.gettrace(), threading.gettrace()
        old_directory = None
        removed_modules = {}
        input_stream = io.TextIOWrapper(io.BufferedReader(self.input), encoding="utf-8")
        output_stream, error_stream = (
            io.TextIOWrapper(_Output(self), encoding="utf-8", errors="replace", write_through=True)
            for _ in range(2))
        try:
            old_directory = os.open(".", os.O_RDONLY | os.O_DIRECTORY)
            with self.files.directory(parts(self.cwd)) as descriptor:
                os.fchdir(descriptor)
            source_path = str(Path(self.root) / self.path)
            namespace = ModuleType("__main__")
            namespace.__dict__.update(__file__=source_path, __package__=None,
                                      __spec__=None, __cached__=None)
            sys.modules["__main__"] = namespace
            sys.argv = [source_path, *self.arguments]
            sys.path = list(dict.fromkeys([str(Path(source_path).parent), self.root, *old_path]))
            for name, module in list(sys.modules.items()):
                if self._project_module(name, module):
                    removed_modules[name] = sys.modules.pop(name)
            importlib.invalidate_caches()
            sys.meta_path = [_ProjectImports(self.root, self.files), *old_meta]
            sys.stdin = _ThreadStream(self, input_stream, old_streams[0])
            sys.stdout = _ThreadStream(self, output_stream, old_streams[1])
            sys.stderr = _ThreadStream(self, error_stream, old_streams[2])
            with self.condition:
                self.cancellation = _Cancellation(self)
                if self.cancelled:
                    self.cancellation.request()

            def start_child(thread, *args, **kwargs):
                if self.owns_thread():
                    setattr(thread, _OWNER, self)
                    with self.condition:
                        self.children.append(thread)
                return old_start(thread, *args, **kwargs)

            threading.Thread.start = start_child
            if self.cancellation.tool is None:
                sys.settrace(self.cancellation.trace)
                threading.settrace(self.cancellation.trace)
            self.executing = True
            if self.cancelled:
                raise KeyboardInterrupt
            exec(compile(self.source, source_path, "exec"), namespace.__dict__)
            self.exit_code = 0
        except SystemExit as error:
            self.exit_code = (0 if error.code is None else error.code
                              if isinstance(error.code, int) else 1)
            if error.code is not None and not isinstance(error.code, int):
                self.write(str(error.code) + "\n")
        except KeyboardInterrupt:
            self.exit_code = 130
        except BaseException as error:
            self.exit_code = 1
            summary = traceback.TracebackException.from_exception(error)
            summary.stack = traceback.StackSummary.from_list(
                frame for frame in summary.stack if frame.filename != __file__)
            self.write("".join(summary.format()).replace(
                self.root + os.sep, "/Documents/" + self.workspace["path"] + "/"))
        finally:
            self.executing = False
            # A script's threads retain its streams and environment until they
            # finish. Do not advertise completion or start another run early.
            while True:
                with self.condition:
                    children = [thread for thread in self.children if thread.is_alive()]
                if not children:
                    break
                for thread in children:
                    thread.join(0.05)
            with self.condition:
                if self.cancellation:
                    self.cancellation.close()
                sys.settrace(old_trace)
                threading.settrace(old_thread_trace)
                threading.Thread.start = old_start
                sys.stdin, sys.stdout, sys.stderr = old_streams
                sys.argv, sys.path, sys.meta_path = old_argv, old_path, old_meta
                for name, module in list(sys.modules.items()):
                    if self._project_module(name, module):
                        sys.modules.pop(name, None)
                sys.modules.update(removed_modules)
                if old_main is not None:
                    sys.modules["__main__"] = old_main
                else:
                    sys.modules.pop("__main__", None)
                try:
                    if old_directory is not None:
                        os.fchdir(old_directory)
                finally:
                    if old_directory is not None:
                        os.close(old_directory)
                    self.files.close()
                    for stream in (input_stream, output_stream, error_stream, self.input):
                        # A script may close or detach a standard stream. Its
                        # replacement must not prevent the host from recovering.
                        with suppress(ValueError, OSError):
                            stream.close()
                    self.input_request = None
                    if self.cancelled:
                        self.exit_code = 130
                    _execution_lock.release()
                    self.done.set()
                    self.condition.notify_all()


class PythonRunner:
    def __init__(self):
        self.current = None

    def require_idle(self):
        if self.current and not self.current.done.is_set():
            raise WorkspaceError("Unavailable", "Stop the running Python file first.")

    def start(self, files, workspace, root, payload):
        identity, path = payload.get("id"), payload.get("path")
        try:
            if not isinstance(identity, str) or str(uuid.UUID(identity)) != identity:
                raise ValueError
        except ValueError:
            raise WorkspaceError("InvalidRequest", "Invalid Python run identifier.") from None
        if self.current and self.current.id == identity:
            return self.current.snapshot()
        self.require_idle()
        parts(path)
        if not path.endswith(".py"):
            raise WorkspaceError("InvalidRequest", "Choose a Python file in this workspace.")
        arguments, cwd = payload.get("arguments", []), payload.get("cwd", "")
        if isinstance(arguments, str):
            if len(arguments) > POLL_LIMIT:
                raise WorkspaceError("InvalidRequest", "Python arguments are too long.")
            try:
                arguments = shlex.split(arguments)
            except ValueError as error:
                raise WorkspaceError("InvalidRequest", str(error)) from None
        if (not isinstance(arguments, list) or len(arguments) > 128
                or not all(isinstance(arg, str) and "\0" not in arg for arg in arguments)
                or sum(map(len, arguments)) > POLL_LIMIT):
            raise WorkspaceError("InvalidRequest", "Invalid Python arguments.")
        with files.directory(parts(cwd)):
            pass
        if not os.path.samestat(os.fstat(files.fd), os.stat(root, follow_symlinks=False)):
            raise WorkspaceError("Unavailable", "The workspace moved. Reopen it before running Python.")
        source = files.read(path)
        if not _execution_lock.acquire(blocking=False):
            raise WorkspaceError("Unavailable", "Another Python file is still running.")
        owned_files = None
        try:
            owned_files = RootedFiles(descriptor=os.dup(files.fd))
            run = Run(identity, dict(workspace), path, root, owned_files, source, arguments, cwd)
            run.thread.start()
        except BaseException:
            if owned_files:
                owned_files.close()
            _execution_lock.release()
            raise
        self.current = run
        return run.snapshot()

    def dispatch(self, action, payload):
        run = self.current
        if action == "run.status" and not run:
            return None
        if not run or (payload.get("id") is not None and payload["id"] != run.id):
            raise WorkspaceError("Unavailable", "This Python run is no longer available.")
        if action == "run.status":
            return run.snapshot(payload.get("after", 0))
        if payload.get("id") != run.id:
            raise WorkspaceError("InvalidRequest", "A Python run identifier is required.")
        if action == "run.stop":
            run.stop()
        elif action == "run.input":
            run.send_input(payload.get("request"), payload.get("text", ""), payload.get("eof", False))
        else:
            raise WorkspaceError("InvalidRequest", "Unknown Python command.")
        return None

    def clear(self):
        self.require_idle()
        self.current = None

    def close(self):
        if self.current:
            self.current.stop()
            self.current.done.wait()
